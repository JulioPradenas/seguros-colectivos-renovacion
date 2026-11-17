"""GLM de frecuencia (Poisson, offset log-exposición) y severidad (Gamma, link log) por tipo de prestación."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from colectivos.config import CLAIM_TYPES

logger = logging.getLogger(__name__)

FACTORS: tuple[str, ...] = ("age_band", "sex", "health_system", "role", "industry", "region")
REFERENCE_YEAR = 2023
RHS = " + ".join(f"C({factor})" for factor in FACTORS) + " + year_c"
FREQ_FORMULA = f"n_claims ~ {RHS}"
SEV_FORMULA = f"avg_severity ~ {RHS}"
# Severidad de cola pesada y pocos siniestros: no se segmenta por factores (solo nivel y tendencia).
UNSEGMENTED_SEVERITY: frozenset[str] = frozenset({"alto_costo"})
SEV_FORMULA_UNSEGMENTED = "avg_severity ~ year_c"
RIDGE_ALPHA = 1e-4

GLMResults = Any  # GLMResultsWrapper o RegularizedResultsWrapper de statsmodels


@dataclass(frozen=True)
class FactorLevels:
    """Niveles vistos al entrenar; un nivel no visto se predice con el nivel de mayor peso (fallback)."""

    freq: dict[str, set[str]]
    sev: dict[str, set[str]]
    freq_fallback: dict[str, str]
    sev_fallback: dict[str, str]


@dataclass(frozen=True)
class FreqSevModel:
    claim_type: str
    freq: GLMResults
    sev: GLMResults
    train_years: tuple[int, int]
    levels: FactorLevels
    freq_regularized: bool


def _prepare(cells: pd.DataFrame, claim_type: str) -> pd.DataFrame:
    data = cells[(cells.claim_type == claim_type) & (cells.exposure_years > 0)].copy()
    data["year_c"] = data.year - REFERENCE_YEAR
    for factor in FACTORS:
        data[factor] = data[factor].astype(str)
    return data.reset_index(drop=True)


def _has_empty_level(data: pd.DataFrame) -> bool:
    return any((data.groupby(factor).n_claims.sum() == 0).any() for factor in FACTORS)


def fit_frequency(cells: pd.DataFrame, claim_type: str) -> GLMResults:
    data = _prepare(cells, claim_type)
    model = smf.glm(FREQ_FORMULA, data=data, family=sm.families.Poisson(), offset=np.log(data.exposure_years))
    if _has_empty_level(data):
        logger.warning("%s: hay niveles sin siniestros; se ajusta con ridge (alpha=%s)", claim_type, RIDGE_ALPHA)
        return model.fit_regularized(alpha=RIDGE_ALPHA, L1_wt=0.0)
    return model.fit()


def fit_severity(cells: pd.DataFrame, claim_type: str) -> GLMResults:
    data = _prepare(cells, claim_type)
    data = data[data.n_claims > 0].reset_index(drop=True)
    data["avg_severity"] = data.reimbursed_uf / data.n_claims
    formula = SEV_FORMULA_UNSEGMENTED if claim_type in UNSEGMENTED_SEVERITY else SEV_FORMULA
    model = smf.glm(formula, data=data, family=sm.families.Gamma(sm.families.links.Log()),
                    var_weights=data.n_claims)
    return model.fit()


def _levels(data: pd.DataFrame, weight: str) -> tuple[dict[str, set[str]], dict[str, str]]:
    seen = {factor: set(data[factor].astype(str)) for factor in FACTORS}
    fallback = {factor: str(data.groupby(factor)[weight].sum().idxmax()) for factor in FACTORS}
    return seen, fallback


def fit_all(cells: pd.DataFrame, train_years: tuple[int, int]) -> dict[str, FreqSevModel]:
    first, last = train_years
    train = cells[cells.year.between(first, last)]
    models = {}
    for claim_type in CLAIM_TYPES:
        data = _prepare(train, claim_type)
        if data.empty:
            continue
        freq_seen, freq_fallback = _levels(data, "exposure_years")
        sev_seen, sev_fallback = _levels(data[data.n_claims > 0], "n_claims")
        freq = fit_frequency(train, claim_type)
        models[claim_type] = FreqSevModel(
            claim_type=claim_type,
            freq=freq,
            sev=fit_severity(train, claim_type),
            train_years=(first, last),
            levels=FactorLevels(freq_seen, sev_seen, freq_fallback, sev_fallback),
            freq_regularized=_has_empty_level(data),
        )
    return models


def _align_levels(profile: pd.DataFrame, seen: dict[str, set[str]], fallback: dict[str, str]) -> pd.DataFrame:
    aligned = profile.copy()
    for factor in FACTORS:
        values = aligned[factor].astype(str)
        aligned[factor] = values.where(values.isin(seen[factor]), fallback[factor])
    return aligned


def predict_cost_per_year(models: dict[str, FreqSevModel], profile: pd.DataFrame, year_c: float) -> pd.DataFrame:
    """Costo esperado por persona-año (UF) por tipo y total, para cada fila de perfil de factores."""
    out = profile.copy()
    total = np.zeros(len(profile))
    for claim_type, model in models.items():
        freq_x = _align_levels(profile, model.levels.freq, model.levels.freq_fallback).assign(year_c=year_c)
        sev_x = _align_levels(profile, model.levels.sev, model.levels.sev_fallback).assign(year_c=year_c)
        rate = np.asarray(model.freq.predict(freq_x, offset=np.zeros(len(freq_x))), dtype=float)
        severity = np.asarray(model.sev.predict(sev_x), dtype=float)
        cost = rate * severity
        out[f"expected_cost_{claim_type}_uf"] = cost
        total += cost
    out["expected_health_cost_uf"] = total
    return out


def relativities(result: GLMResults) -> pd.DataFrame:
    params = pd.Series(result.params)
    try:
        ci = pd.DataFrame(result.conf_int())
        low, high = np.exp(ci.iloc[:, 0]), np.exp(ci.iloc[:, 1])
    except (AttributeError, NotImplementedError, ValueError):
        low = high = pd.Series(np.nan, index=params.index)
    return pd.DataFrame(
        {
            "term": params.index,
            "relativity": np.exp(params.to_numpy()),
            "ci_low": np.asarray(low, dtype=float),
            "ci_high": np.asarray(high, dtype=float),
        }
    )

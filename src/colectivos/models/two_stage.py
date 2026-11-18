"""Etapa 2: relatividades por segmento (GLM de frecuencia y severidad sin año), con la tendencia de la etapa 1
fija como offset. El costo esperado de un perfil en year_c es relatividades x tendencia llevada a year_c."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from colectivos.config import CLAIM_TYPES, PricingConfig
from colectivos.models.glm import (
    FACTORS,
    UNSEGMENTED_SEVERITY,
    FactorLevels,
    FreqSevModel,
    align_levels,
    fitted_levels,
    frequency_levels,
    prepare_cells,
)
from colectivos.models.trend import TrendModel, fit_trends, trend_log_offset

logger = logging.getLogger(__name__)

FACTOR_RHS = " + ".join(f"C({factor})" for factor in FACTORS)
SUM_COLUMNS = ("exposure_years", "n_claims_ult", "reimbursed_capped_ult_uf")


@dataclass(frozen=True)
class TwoStageModel:
    trends: dict[str, TrendModel]
    relativities: dict[str, FreqSevModel]
    train_years: tuple[int, int]

    def predict_cost(self, profile: pd.DataFrame, year_c: float | pd.Series) -> pd.DataFrame:
        """Costo esperado por persona-año (UF) por tipo y total; unseen_level_flag marca filas tarificadas con
        algún nivel de respaldo."""
        out = profile.copy()
        total = np.zeros(len(profile))
        unseen = np.zeros(len(profile), dtype=bool)
        for claim_type, model in self.relativities.items():
            unseen |= _unseen_mask(profile, model.levels.freq)
            if claim_type not in UNSEGMENTED_SEVERITY:
                unseen |= _unseen_mask(profile, model.levels.sev)
            freq_x = align_levels(profile, model.levels.freq, model.levels.freq_fallback)
            sev_x = align_levels(profile, model.levels.sev, model.levels.sev_fallback)
            freq_offset = trend_log_offset(self.trends, profile, claim_type, year_c, "freq")
            sev_offset = trend_log_offset(self.trends, profile, claim_type, year_c, "sev")
            rate = np.asarray(model.freq.predict(freq_x, offset=freq_offset), dtype=float)
            severity = np.asarray(model.sev.predict(sev_x, offset=sev_offset), dtype=float)
            cost = rate * severity
            out[f"expected_cost_{claim_type}_uf"] = cost
            total += cost
        for claim_type in set(CLAIM_TYPES) - set(self.relativities):
            out[f"expected_cost_{claim_type}_uf"] = 0.0
        out["expected_health_cost_uf"] = total
        out["unseen_level_flag"] = unseen
        if unseen.any():
            logger.warning("%d perfiles con niveles no vistos al entrenar: tarificados con el nivel de respaldo", unseen.sum())
        return out


    def predict_frequency(self, profile: pd.DataFrame, year_c: float | pd.Series) -> pd.DataFrame:
        """Frecuencia esperada por persona-año por tipo (expected_freq_{tipo}), para la devianza de Poisson."""
        out = pd.DataFrame(index=profile.index)
        for claim_type, model in self.relativities.items():
            freq_x = align_levels(profile, model.levels.freq, model.levels.freq_fallback)
            offset = trend_log_offset(self.trends, profile, claim_type, year_c, "freq")
            out[f"expected_freq_{claim_type}"] = np.asarray(model.freq.predict(freq_x, offset=offset), dtype=float)
        return out


def _unseen_mask(profile: pd.DataFrame, seen: dict[str, set[str]]) -> np.ndarray:
    mask = np.zeros(len(profile), dtype=bool)
    for factor in FACTORS:
        mask |= ~profile[factor].astype(str).isin(seen[factor]).to_numpy()
    return mask


def _training_cells(cells_yearly: pd.DataFrame, claim_type: str, train_years: tuple[int, int]) -> pd.DataFrame:
    """Sin efecto empresa en la etapa 2: se agregan las empresas por año x factores (la tendencia por rubro
    depende solo de year e industry, que quedan en la llave)."""
    first, last = train_years
    data = cells_yearly[(cells_yearly.claim_type == claim_type) & cells_yearly.year.between(first, last)]
    data = data.groupby(["claim_type", "year", *FACTORS], as_index=False, observed=True)[list(SUM_COLUMNS)].sum()
    return prepare_cells(data, claim_type)


def _fit_relativities(
    data: pd.DataFrame, claim_type: str, trends: dict[str, TrendModel], train_years: tuple[int, int]
) -> FreqSevModel:
    freq_seen, freq_fallback = frequency_levels(data, count="n_claims_ult")
    merged = {f: sorted(set(data[f]) - freq_seen[f]) for f in FACTORS if set(data[f]) - freq_seen[f]}
    if merged:
        logger.warning("%s: niveles sin siniestros fusionados con el nivel base: %s", claim_type, merged)
    freq_data = align_levels(data, freq_seen, freq_fallback)
    freq_offset = np.log(freq_data.exposure_years) + trend_log_offset(
        trends, freq_data, claim_type, freq_data.year_c, "freq"
    )
    freq = smf.glm(
        f"n_claims_ult ~ {FACTOR_RHS}", data=freq_data, family=sm.families.Poisson(), offset=freq_offset
    ).fit()

    sev_data = data[(data.n_claims_ult > 0) & (data.reimbursed_capped_ult_uf > 0)].reset_index(drop=True)
    sev_data["avg_severity"] = sev_data.reimbursed_capped_ult_uf / sev_data.n_claims_ult
    sev_seen, sev_fallback = fitted_levels(sev_data, "n_claims_ult")
    rhs = "1" if claim_type in UNSEGMENTED_SEVERITY else FACTOR_RHS
    sev = smf.glm(
        f"avg_severity ~ {rhs}",
        data=sev_data,
        family=sm.families.Gamma(sm.families.links.Log()),
        var_weights=sev_data.n_claims_ult,
        offset=trend_log_offset(trends, sev_data, claim_type, sev_data.year_c, "sev"),
    ).fit()
    return FreqSevModel(
        claim_type=claim_type,
        freq=freq,
        sev=sev,
        train_years=train_years,
        levels=FactorLevels(freq_seen, sev_seen, freq_fallback, sev_fallback),
    )


def fit_two_stage(cells_yearly: pd.DataFrame, train_years: tuple[int, int], cfg: PricingConfig) -> TwoStageModel:
    trends = fit_trends(cells_yearly, train_years, cfg)
    relativities = {
        claim_type: _fit_relativities(_training_cells(cells_yearly, claim_type, train_years), claim_type, trends, train_years)
        for claim_type in trends
    }
    return TwoStageModel(trends=trends, relativities=relativities, train_years=train_years)

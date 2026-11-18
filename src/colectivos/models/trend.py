"""Etapa 1: tendencia anual de frecuencia y severidad estimada dentro de cada empresa (efecto fijo por empresa),
para que un cambio en el mix de clientes no se lea como tendencia. Prueba opcional de tendencia por rubro."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

from colectivos.config import CLAIM_TYPES, PricingConfig
from colectivos.models.glm import REFERENCE_YEAR

logger = logging.getLogger(__name__)

NO_CLAIMS_COMPANY = "__sin_siniestros__"
# Pocos siniestros por empresa: el efecto fijo por empresa no se estima (solo factores y tendencia).
NO_COMPANY_EFFECT: frozenset[str] = frozenset({"alto_costo"})
GROUP_KEYS: tuple[str, ...] = ("year", "company_id", "industry", "age_band", "sex", "role", "health_system")
INDIVIDUAL_ALPHA = 0.05


@dataclass(frozen=True)
class TrendModel:
    claim_type: str
    freq_trend: float
    sev_trend: float
    industry_freq_trend: dict[str, float] = field(default_factory=dict)
    lr_pvalue: float | None = None


def _rhs(claim_type: str) -> str:
    terms = ["C(age_band)", "C(sex)", "C(role)", "C(health_system)", "year_c"]
    if claim_type not in NO_COMPANY_EFFECT:
        terms.insert(0, "C(company_id)")
    return " + ".join(terms)


def _training_data(cells_yearly: pd.DataFrame, claim_type: str, train_years: tuple[int, int]) -> pd.DataFrame:
    first, last = train_years
    data = cells_yearly[
        (cells_yearly.claim_type == claim_type)
        & cells_yearly.year.between(first, last)
        & (cells_yearly.exposure_years > 0)
    ]
    claims_by_company = data.groupby("company_id").n_claims_ult.transform("sum")
    data = data.assign(company_id=data.company_id.where(claims_by_company > 0, NO_CLAIMS_COMPANY))
    grouped = data.groupby(list(GROUP_KEYS), as_index=False, observed=True)[
        ["exposure_years", "n_claims_ult", "reimbursed_capped_ult_uf"]
    ].sum()
    return grouped.assign(year_c=grouped.year - REFERENCE_YEAR)


def _fit_poisson(formula: str, data: pd.DataFrame):
    return smf.glm(formula, data=data, family=sm.families.Poisson(), offset=np.log(data.exposure_years)).fit()


def _industry_interaction(
    freq_data: pd.DataFrame, base_formula: str, base_llf: float, base_df: float, alpha: float
) -> tuple[dict[str, float], float, float | None]:
    """Prueba global (LR, gl = rubros - 1) y, si rechaza, retiene los rubros cuya tendencia difiere del resto
    al 5% individual. Devuelve (tendencias adicionales, p-valor LR, tendencia base del modelo conjunto)."""
    full = _fit_poisson(f"{base_formula} + C(industry):year_c", freq_data)
    df = full.df_model - base_df
    lr_pvalue = float(stats.chi2.sf(2 * (full.llf - base_llf), df)) if df > 0 else 1.0
    if lr_pvalue >= alpha:
        return {}, lr_pvalue, None

    industries = sorted(freq_data.industry.unique())
    columns = {industry: f"trend_x_{index}" for index, industry in enumerate(industries)}
    data = freq_data.assign(
        **{column: (freq_data.industry == industry) * freq_data.year_c for industry, column in columns.items()}
    )
    pvalues = {
        industry: _fit_poisson(f"{base_formula} + {column}", data).pvalues[column]
        for industry, column in columns.items()
    }
    candidates = sorted((p, industry) for industry, p in pvalues.items() if p < INDIVIDUAL_ALPHA)
    candidates = [industry for _, industry in candidates][: len(industries) - 1]
    if not candidates:
        return {}, lr_pvalue, None
    joint = _fit_poisson(f"{base_formula} + " + " + ".join(columns[i] for i in candidates), data)
    retained = {
        industry: float(np.exp(joint.params[columns[industry]]) - 1)
        for industry in candidates
        if joint.pvalues[columns[industry]] < INDIVIDUAL_ALPHA
    }
    return retained, lr_pvalue, float(joint.params["year_c"]) if retained else None


def fit_trend(
    cells_yearly: pd.DataFrame,
    claim_type: str,
    train_years: tuple[int, int],
    test_interaction: bool,
    alpha: float,
) -> TrendModel:
    data = _training_data(cells_yearly, claim_type, train_years)
    rhs = _rhs(claim_type)
    freq_formula = f"n_claims_ult ~ {rhs}"
    freq = _fit_poisson(freq_formula, data)

    sev_data = data[(data.n_claims_ult > 0) & (data.reimbursed_capped_ult_uf > 0)]
    sev_data = sev_data.assign(avg_severity=sev_data.reimbursed_capped_ult_uf / sev_data.n_claims_ult)
    sev = smf.glm(
        f"avg_severity ~ {rhs}",
        data=sev_data,
        family=sm.families.Gamma(sm.families.links.Log()),
        var_weights=sev_data.n_claims_ult,
    ).fit()

    industry_trend: dict[str, float] = {}
    lr_pvalue = None
    base_log_trend = float(freq.params["year_c"])
    if test_interaction:
        industry_trend, lr_pvalue, joint_log_trend = _industry_interaction(
            data, freq_formula, freq.llf, freq.df_model, alpha
        )
        if joint_log_trend is not None:
            base_log_trend = joint_log_trend
    trend = TrendModel(
        claim_type=claim_type,
        freq_trend=float(np.exp(base_log_trend) - 1),
        sev_trend=float(np.exp(sev.params["year_c"]) - 1),
        industry_freq_trend=industry_trend,
        lr_pvalue=lr_pvalue,
    )
    logger.info("Tendencia %s: %s", claim_type, trend)
    return trend


def fit_trends(cells_yearly: pd.DataFrame, train_years: tuple[int, int], cfg: PricingConfig) -> dict[str, TrendModel]:
    return {
        claim_type: fit_trend(
            cells_yearly,
            claim_type,
            train_years,
            test_interaction=claim_type in cfg.trend_interaction_claim_types,
            alpha=cfg.interaction_alpha,
        )
        for claim_type in CLAIM_TYPES
    }


def trend_log_offset(
    trends: dict[str, TrendModel],
    profile: pd.DataFrame,
    claim_type: str,
    year_c: float | pd.Series,
    part: Literal["freq", "sev"],
) -> np.ndarray:
    """year_c x log(1 + tendencia), más la tendencia adicional del rubro en frecuencia cuando fue retenida."""
    trend = trends[claim_type]
    year_c = np.broadcast_to(np.asarray(year_c, dtype=float), (len(profile),))
    if part == "sev":
        return year_c * np.log1p(trend.sev_trend)
    extra = profile.industry.map(trend.industry_freq_trend).fillna(0.0).to_numpy(dtype=float)
    return year_c * (np.log1p(trend.freq_trend) + np.log1p(extra))

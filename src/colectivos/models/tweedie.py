"""Retador: GLM Tweedie de costo puro (monto limitado último por año-persona) por tipo, con los 6 factores y la
tendencia de la etapa 1 como offset. La potencia se elige por log-verosimilitud perfilada en una grilla."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from colectivos.config import CLAIM_TYPES
from colectivos.models.glm import FACTORS, FactorLevels, GLMResults, align_levels, frequency_levels
from colectivos.models.trend import TrendModel, trend_log_offset
from colectivos.models.two_stage import FACTOR_RHS, _training_cells, _unseen_mask

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TweedieModel:
    trends: dict[str, TrendModel]
    results: dict[str, GLMResults]
    powers: dict[str, float]
    levels: dict[str, FactorLevels]
    train_years: tuple[int, int]

    def predict_cost(self, profile: pd.DataFrame, year_c: float | pd.Series) -> pd.DataFrame:
        out = profile.copy()
        total = np.zeros(len(profile))
        unseen = np.zeros(len(profile), dtype=bool)
        for claim_type, result in self.results.items():
            levels = self.levels[claim_type]
            unseen |= _unseen_mask(profile, levels.freq)
            x = align_levels(profile, levels.freq, levels.freq_fallback)
            offset = _trend_offset(self.trends, profile, claim_type, year_c)
            cost = np.asarray(result.predict(x, offset=offset), dtype=float)
            out[f"expected_cost_{claim_type}_uf"] = cost
            total += cost
        out["expected_health_cost_uf"] = total
        out["unseen_level_flag"] = unseen
        return out


def _trend_offset(
    trends: dict[str, TrendModel], profile: pd.DataFrame, claim_type: str, year_c: float | pd.Series
) -> np.ndarray:
    return trend_log_offset(trends, profile, claim_type, year_c, "freq") + trend_log_offset(
        trends, profile, claim_type, year_c, "sev"
    )


def _fit_power(data: pd.DataFrame, offset: np.ndarray, power: float) -> GLMResults:
    family = sm.families.Tweedie(var_power=power, link=sm.families.links.Log())
    return smf.glm(
        f"pure_premium ~ {FACTOR_RHS}", data=data, family=family, var_weights=data.exposure_years, offset=offset
    ).fit()


def fit_tweedie(
    cells_yearly: pd.DataFrame,
    train_years: tuple[int, int],
    trends: dict[str, TrendModel],
    powers: tuple[float, ...],
) -> TweedieModel:
    results, chosen, levels = {}, {}, {}
    for claim_type in CLAIM_TYPES:
        data = _training_cells(cells_yearly, claim_type, train_years)
        # Un nivel sin costo llevaría su coeficiente a -infinito: se fusiona con el de mayor exposición.
        seen, fallback = frequency_levels(data, count="reimbursed_capped_ult_uf")
        data = align_levels(data, seen, fallback)
        data["pure_premium"] = data.reimbursed_capped_ult_uf / data.exposure_years
        offset = _trend_offset(trends, data, claim_type, data.year_c)
        fits = {power: _fit_power(data, offset, power) for power in powers}
        best = max(fits, key=lambda power: fits[power].llf)
        logger.info("Tweedie %s: potencia %.2f (llf %s)", claim_type, best, {p: round(f.llf, 1) for p, f in fits.items()})
        results[claim_type], chosen[claim_type] = fits[best], best
        levels[claim_type] = FactorLevels(seen, seen, fallback, fallback)
    return TweedieModel(trends=trends, results=results, powers=chosen, levels=levels, train_years=train_years)

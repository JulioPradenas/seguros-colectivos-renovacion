"""Validación fuera de tiempo: línea base de la Fase 1, campeón de dos etapas y retador Tweedie contra el costo
limitado último del año de prueba, por tipo, por segmento y por contrato."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from colectivos.config import CLAIM_TYPES
from colectivos.models.glm import FACTORS, REFERENCE_YEAR, FreqSevModel, align_levels, predict_cost_per_year
from colectivos.models.two_stage import _unseen_mask

SEGMENT_FACTORS: tuple[str, ...] = ("industry", "age_band", "health_system", "company_size")


class CostPredictor(Protocol):
    def predict_cost(self, profile: pd.DataFrame, year_c: float | pd.Series) -> pd.DataFrame: ...


@dataclass(frozen=True)
class BaselineModel:
    """GLM de la Fase 1 (pagados, tendencia como covariable) sin cambios, con la interfaz de CostPredictor."""

    models: dict[str, FreqSevModel]

    def predict_cost(self, profile: pd.DataFrame, year_c: float | pd.Series) -> pd.DataFrame:
        out = predict_cost_per_year(self.models, profile, year_c)
        unseen = np.zeros(len(profile), dtype=bool)
        for model in self.models.values():
            unseen |= _unseen_mask(profile, model.levels.freq)
        out["unseen_level_flag"] = unseen
        return out

    def predict_frequency(self, profile: pd.DataFrame, year_c: float | pd.Series) -> pd.DataFrame:
        out = pd.DataFrame(index=profile.index)
        for claim_type, model in self.models.items():
            x = align_levels(profile, model.levels.freq, model.levels.freq_fallback).assign(year_c=year_c)
            out[f"expected_freq_{claim_type}"] = np.asarray(model.freq.predict(x, offset=np.zeros(len(x))), dtype=float)
        return out


def gini(predicted_rate: np.ndarray, actual: np.ndarray, exposure: np.ndarray) -> float:
    """Gini de la curva de Lorenz ordenada por tasa predicha ascendente (empates agrupados): 1 - 2 x área."""
    frame = pd.DataFrame({"rate": predicted_rate, "actual": actual, "exposure": exposure})
    grouped = frame.groupby("rate", sort=True)[["actual", "exposure"]].sum()
    x = np.concatenate([[0.0], grouped.exposure.cumsum().to_numpy() / grouped.exposure.sum()])
    y = np.concatenate([[0.0], grouped.actual.cumsum().to_numpy() / grouped.actual.sum()])
    area = float(np.sum((x[1:] - x[:-1]) * (y[1:] + y[:-1]) / 2))
    return 1.0 - 2.0 * area


def _poisson_deviance(actual: np.ndarray, expected: np.ndarray) -> float:
    with np.errstate(divide="ignore", invalid="ignore"):
        log_term = np.where(actual > 0, actual * np.log(actual / expected), 0.0)
    return float(2 * np.sum(log_term - (actual - expected)))


def _expected_by_row(predictor: CostPredictor, test_cells: pd.DataFrame, year_c: float) -> pd.DataFrame:
    """expected_uf (costo esperado de la fila, en su tipo) y, si el modelo da frecuencia, expected_n."""
    cost = predictor.predict_cost(test_cells, year_c)
    rows = test_cells.copy()
    rows["expected_uf"] = 0.0
    rows["expected_n"] = np.nan
    frequency = predictor.predict_frequency(test_cells, year_c) if hasattr(predictor, "predict_frequency") else None
    for claim_type in CLAIM_TYPES:
        mask = rows.claim_type == claim_type
        rows.loc[mask, "expected_uf"] = cost.loc[mask, f"expected_cost_{claim_type}_uf"] * rows.loc[mask, "exposure_years"]
        if frequency is not None:
            rows.loc[mask, "expected_n"] = (
                frequency.loc[mask, f"expected_freq_{claim_type}"] * rows.loc[mask, "exposure_years"]
            )
    return rows


def _deviance(predictor: CostPredictor, rows: pd.DataFrame, claim_type: str) -> float:
    """Poisson sobre conteos si el modelo predice frecuencia (línea base, campeón); Tweedie sobre el costo si no."""
    if rows.expected_n.notna().all():
        return _poisson_deviance(rows.n_claims_ult.to_numpy(float), rows.expected_n.to_numpy(float))
    result = predictor.results[claim_type]
    exposure = rows.exposure_years.to_numpy(float)
    return float(
        result.family.deviance(
            rows.reimbursed_capped_ult_uf.to_numpy(float) / exposure,
            rows.expected_uf.to_numpy(float) / exposure,
            var_weights=exposure,
        )
    )


def _company_size(test_cells: pd.DataFrame) -> pd.Series:
    one_type = test_cells[test_cells.claim_type == CLAIM_TYPES[0]]
    exposure = one_type.groupby("company_id").exposure_years.sum()
    quartile = pd.qcut(exposure.rank(method="first"), 4, labels=["Q1", "Q2", "Q3", "Q4"]).astype(str)
    return test_cells.company_id.map(quartile)


def out_of_time_report(
    predictors: dict[str, CostPredictor], test_cells: pd.DataFrame, test_year: int
) -> dict[str, pd.DataFrame]:
    test_cells = test_cells.reset_index(drop=True)
    for factor in FACTORS:
        test_cells[factor] = test_cells[factor].astype(str)
    test_cells["company_size"] = _company_size(test_cells)
    year_c = float(test_year - REFERENCE_YEAR)
    by_type, by_segment, contract = [], [], []
    for name, predictor in predictors.items():
        rows = _expected_by_row(predictor, test_cells, year_c)
        rows["actual_uf"] = rows.reimbursed_capped_ult_uf
        for claim_type, group in rows.groupby("claim_type"):
            by_type.append(
                {
                    "model": name, "claim_type": claim_type,
                    "actual_uf": group.actual_uf.sum(), "expected_uf": group.expected_uf.sum(),
                    "deviance": _deviance(predictor, group, claim_type),
                }
            )
        for factor in SEGMENT_FACTORS:
            totals = rows.groupby(factor)[["actual_uf", "expected_uf"]].sum()
            by_segment.extend(
                {"model": name, "factor": factor, "level": level, "actual_uf": r.actual_uf,
                 "expected_uf": r.expected_uf, "ae": r.actual_uf / r.expected_uf}
                for level, r in totals.iterrows()
            )
        per_contract = rows.groupby("contract_id")[["actual_uf", "expected_uf"]].sum()
        per_contract["exposure"] = rows[rows.claim_type == CLAIM_TYPES[0]].groupby("contract_id").exposure_years.sum()
        per_contract = per_contract[per_contract.exposure > 0]
        actual_rate = per_contract.actual_uf / per_contract.exposure
        expected_rate = per_contract.expected_uf / per_contract.exposure
        contract.append(
            {
                "model": name,
                "gini": gini(expected_rate.to_numpy(), per_contract.actual_uf.to_numpy(), per_contract.exposure.to_numpy()),
                "rmse_per_py": float(np.sqrt(np.average((actual_rate - expected_rate) ** 2, weights=per_contract.exposure))),
                "ae": per_contract.actual_uf.sum() / per_contract.expected_uf.sum(),
            }
        )
    by_type_frame = pd.DataFrame(by_type)
    by_type_frame["ae"] = by_type_frame.actual_uf / by_type_frame.expected_uf
    return {"by_type": by_type_frame, "by_segment": pd.DataFrame(by_segment), "contract": pd.DataFrame(contract)}

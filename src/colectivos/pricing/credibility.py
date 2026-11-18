"""Credibilidad Bühlmann-Straub por contrato sobre el A/E (costo limitado último / esperado del modelo), y recargo
por siniestros grandes (exceso sobre el umbral) que se suma a la prima técnica de toda la cartera."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from colectivos.models.glm import REFERENCE_YEAR
from colectivos.models.oot import CostPredictor, _expected_by_row

logger = logging.getLogger(__name__)

CENTER_TOLERANCE = 0.02


@dataclass(frozen=True)
class CredibilityResult:
    s2: float
    a: float
    k: float
    center: float
    by_contract: pd.DataFrame


def buhlmann_straub(experience: pd.DataFrame) -> CredibilityResult:
    data = experience[experience.weight > 0]
    data = data.assign(weighted_ratio=data.weight * data.ratio)
    by_contract = data.groupby("contract_id").agg(
        weight=("weight", "sum"), weighted_ratio=("weighted_ratio", "sum"), n_years=("year", "nunique")
    )
    by_contract["experience_ae"] = by_contract.weighted_ratio / by_contract.weight
    total_weight = by_contract.weight.sum()
    grand_mean = float((by_contract.weight * by_contract.experience_ae).sum() / total_weight)

    within = data.ratio - data.contract_id.map(by_contract.experience_ae)
    dof_within = int((by_contract.n_years - 1).sum())
    s2 = float((data.weight * within**2).sum() / dof_within) if dof_within > 0 else np.nan
    n_contracts = len(by_contract)
    between = float((by_contract.weight * (by_contract.experience_ae - grand_mean) ** 2).sum())
    denominator = total_weight - float((by_contract.weight**2).sum()) / total_weight
    a = (between - (n_contracts - 1) * s2) / denominator if denominator > 0 and np.isfinite(s2) else np.nan

    center = 1.0
    if abs(grand_mean - 1.0) > CENTER_TOLERANCE:
        center = grand_mean
        logger.warning("center = %.4f: el A/E medio de la cartera se aleja más de %.0f%% de 1", grand_mean, 100 * CENTER_TOLERANCE)

    if not np.isfinite(a) or a <= 0:
        logger.warning("Bühlmann-Straub: a <= 0 (o no estimable, a = %s): Z = 0 para todos los contratos", a)
        k = np.inf
        z = np.zeros(n_contracts)
    else:
        k = s2 / a
        z = (by_contract.weight / (by_contract.weight + k)).to_numpy()
    by_contract["credibility_z"] = z
    by_contract["credibility_factor"] = z * by_contract.experience_ae + (1 - z) * center
    result = by_contract.reset_index()[
        ["contract_id", "weight", "experience_ae", "credibility_z", "credibility_factor", "n_years"]
    ]
    return CredibilityResult(s2=s2, a=float(a), k=float(k), center=center, by_contract=result)


def _rows_with_expected(cells_yearly: pd.DataFrame, model: CostPredictor, years: tuple[int, int]) -> pd.DataFrame:
    first, last = years
    rows = cells_yearly[cells_yearly.year.between(first, last) & (cells_yearly.exposure_years > 0)].reset_index(drop=True)
    return _expected_by_row(model, rows, rows.year - REFERENCE_YEAR)


def contract_experience(cells_yearly: pd.DataFrame, model: CostPredictor, years: tuple[int, int]) -> pd.DataFrame:
    """X_cy = costo limitado último observado / esperado del modelo; w_cy = esperado limitado (UF)."""
    rows = _rows_with_expected(cells_yearly, model, years)
    totals = rows.groupby(["contract_id", "year"], as_index=False).agg(
        actual=("reimbursed_capped_ult_uf", "sum"), weight=("expected_uf", "sum")
    )
    totals = totals[totals.weight > 0]
    return totals.assign(ratio=totals.actual / totals.weight).drop(columns="actual")


def large_loss_load(cells_yearly: pd.DataFrame, model: CostPredictor, years: tuple[int, int]) -> float:
    """Exceso último total sobre el umbral / esperado limitado total del modelo en los mismos años."""
    rows = _rows_with_expected(cells_yearly, model, years)
    excess = float((rows.reimbursed_ult_uf - rows.reimbursed_capped_ult_uf).sum())
    return excess / float(rows.expected_uf.sum())

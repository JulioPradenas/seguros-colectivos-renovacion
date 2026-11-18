"""Descomposición multiplicativa del reajuste agregado (spec Fase 2, 5.8). Es una identidad que telescopea: el
producto de los factores es exactamente Σ prima técnica / Σ prima vigente de los contratos que renuevan."""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from colectivos.config import PricingConfig
from colectivos.models.glm import REFERENCE_YEAR
from colectivos.models.oot import CostPredictor
from colectivos.pricing.technical_premium import load_renewal_inputs, renewal_rows

FACTOR_ORDER: tuple[str, ...] = (
    "Brecha de siniestralidad",
    "Ajuste del modelo",
    "Perfil",
    "Tendencia",
    "Credibilidad y siniestros grandes",
    "Vida",
    "Prima por persona",
)


def _earned_premium(db_path: Path, contracts: pd.Index, year: int) -> float:
    with duckdb.connect(str(db_path), read_only=True) as con:
        premium = con.execute(
            "SELECT contract_id, SUM(earned_premium_uf) AS earned_premium_uf "
            "FROM marts.mart_loss_ratio_contract_year WHERE year = ? GROUP BY contract_id",
            [year],
        ).df()
    return float(premium[premium.contract_id.isin(contracts)].earned_premium_uf.sum())


def rate_change_decomposition(
    db_path: Path,
    model: CostPredictor,
    cells_yearly: pd.DataFrame,
    renewal: pd.DataFrame,
    pricing: PricingConfig,
) -> pd.DataFrame:
    reference_year = pricing.reference_year
    reference_year_c = float(reference_year - REFERENCE_YEAR)
    contracts = pd.Index(renewal.contract_id)
    loading = 1 - pricing.expense_ratio - pricing.commission_ratio - pricing.target_margin

    history = cells_yearly[
        (cells_yearly.year == reference_year) & cells_yearly.contract_id.isin(contracts) & (cells_yearly.exposure_years > 0)
    ].reset_index(drop=True)
    cost_reference = float(history.reimbursed_ult_uf.sum())
    exposure_reference = float(history.groupby("claim_type").exposure_years.sum().iloc[0])
    premium_reference = _earned_premium(db_path, contracts, reference_year)
    history_cost = model.predict_cost(history, reference_year_c)
    model_history = float(
        sum(
            (history_cost.loc[history.claim_type == claim_type, f"expected_cost_{claim_type}_uf"]
             * history.loc[history.claim_type == claim_type, "exposure_years"]).sum()
            for claim_type in history.claim_type.unique()
        )
    )

    profile, terms, _ = load_renewal_inputs(db_path, pricing)
    active = renewal_rows(profile, terms[terms.contract_id.isin(contracts)])
    model_active_reference = float(model.predict_cost(active, reference_year_c).expected_health_cost_uf.sum())
    n_active = float(renewal.n_insured_active.sum())

    model_2026 = float(renewal.expected_health_cost_model_uf.sum())
    health_2026 = float(renewal.expected_health_cost_uf.sum())
    life_2026 = float(renewal.expected_life_cost_uf.sum())
    current_premium = float(renewal.current_premium_annual_uf.sum())

    multipliers = [
        (cost_reference / premium_reference) / loading,
        model_history / cost_reference,
        (model_active_reference / n_active) / (model_history / exposure_reference),
        model_2026 / model_active_reference,
        health_2026 / model_2026,
        (health_2026 + life_2026) / health_2026,
        (premium_reference / exposure_reference) / (current_premium / n_active),
    ]
    logs = np.log(multipliers)
    total_log = logs.sum()
    log_share = logs / total_log if abs(total_log) > 1e-12 else np.full(len(logs), np.nan)
    return pd.DataFrame({"factor": FACTOR_ORDER, "multiplier": multipliers, "log_share": log_share})

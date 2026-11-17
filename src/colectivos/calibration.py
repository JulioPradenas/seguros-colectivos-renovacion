"""Compara métricas agregadas del warehouse contra objetivos de calibración (CMF/INE/supuestos)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import yaml

CALIBRATION_YEARS = (2021, 2024)  # 2025 excluido: incompleto por IBNR al corte

METRIC_SQL = {
    "loss_ratio_health_annual": """
        SELECT SUM(health_claims_uf) / SUM(earned_premium_uf)
        FROM marts.mart_loss_ratio_contract_year
        WHERE year BETWEEN {first} AND {last}
    """,
    "claims_cost_per_insured_uf": """
        SELECT SUM(health_claims_uf) / SUM(exposure_years)
        FROM marts.mart_loss_ratio_contract_year
        WHERE year BETWEEN {first} AND {last}
    """,
    "health_severity_trend": """
        WITH severity AS (
            SELECT
                year,
                SUM(reimbursed_uf) / SUM(n_claims) AS mean_severity
            FROM marts.mart_model_cells
            WHERE year IN ({first}, {last})
            GROUP BY year
        )
        SELECT POWER(
            MAX(CASE WHEN year = {last} THEN mean_severity END)
                / MAX(CASE WHEN year = {first} THEN mean_severity END),
            1.0 / ({last} - {first})
        ) - 1
        FROM severity
    """,
    "fonasa_share_start": """
        SELECT SUM(CASE WHEN health_system = 'fonasa' THEN exposure_years ELSE 0 END) / SUM(exposure_years)
        FROM marts.mart_model_cells
        WHERE year = {first} AND claim_type = 'ambulatoria'
    """,
}


def is_within(value: float, low: float, high: float) -> bool:
    return low <= value <= high


def calibration_report(db_path: Path, targets_path: Path) -> pd.DataFrame:
    targets = yaml.safe_load(Path(targets_path).read_text())
    first, last = CALIBRATION_YEARS
    rows = []
    with duckdb.connect(str(db_path), read_only=True) as con:
        for metric, spec in targets.items():
            generated = con.execute(METRIC_SQL[metric].format(first=first, last=last)).fetchone()[0]
            rows.append(
                {
                    "metric": metric,
                    "generated": float(generated),
                    "target_low": spec["target_low"],
                    "target_high": spec["target_high"],
                    "source": " ".join(spec["source"].split()),
                    "assumption": spec["assumption"],
                    "within_range": is_within(float(generated), spec["target_low"], spec["target_high"]),
                }
            )
    return pd.DataFrame(rows)

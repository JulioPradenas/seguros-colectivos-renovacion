"""Patrones plantados en la cartera para que el análisis los detecte (verdad documentada en truth/patterns.json)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from colectivos.config import CLAIM_TYPES, GeneratorConfig

BASE_YEAR = 2021


def select_pattern_targets(
    cfg: GeneratorConfig, companies: pd.DataFrame, contracts: pd.DataFrame, rng: np.random.Generator
) -> dict[str, dict[str, Any]]:
    """Elige empresas y contratos afectados por cada patrón y devuelve la verdad a documentar."""
    patterns = cfg.patterns
    active_2023 = companies[companies.client_since <= pd.Timestamp("2023-01-01")]

    adverse = patterns["adverse_selection"]
    small = active_2023[active_2023.n_holders_target < adverse["max_holders"]].company_id.to_numpy()
    adverse_companies = rng.choice(small, size=min(adverse["n_companies"], len(small)), replace=False)

    cat = patterns["catastrophic_event"]
    year_start = pd.Timestamp(year=cat["year"], month=1, day=1)
    eligible = companies[
        companies.n_holders_target.between(cat["min_holders"], cat["max_holders"])
        & (companies.client_since <= year_start)
        & (companies.lapse_date.isna() | (companies.lapse_date > year_start + pd.DateOffset(years=1)))
    ]
    cat_company = str(rng.choice(eligible.company_id.to_numpy()))

    inadequate = patterns["inadequate_rate_changes"]
    contract_ids = contracts.contract_id.drop_duplicates().to_numpy()
    n_inadequate = max(1, int(round(inadequate["share"] * len(contract_ids))))
    inadequate_contracts = rng.choice(contract_ids, size=n_inadequate, replace=False)

    return {
        "industry_hospital_trend": dict(patterns["industry_hospital_trend"]),
        "adverse_selection": {**adverse, "from_date": str(adverse["from_date"]),
                              "companies": sorted(map(str, adverse_companies))},
        "catastrophic_event": {**cat, "company_id": cat_company},
        "inadequate_rate_changes": {**inadequate, "contracts": sorted(map(str, inadequate_contracts))},
        "fonasa_shift": dict(patterns["fonasa_shift"]),
    }


def pattern_multipliers(
    cfg: GeneratorConfig, exposure_enriched: pd.DataFrame, targets: dict[str, dict[str, Any]]
) -> dict[str, pd.Series]:
    rows = exposure_enriched
    multipliers = {t: pd.Series(1.0, index=rows.index) for t in CLAIM_TYPES}

    trend = cfg.patterns["industry_hospital_trend"]
    years = rows.month.dt.year - BASE_YEAR
    in_industry = rows.industry == trend["industry"]
    multipliers[trend["claim_type"]] = multipliers[trend["claim_type"]].where(
        ~in_industry, trend["annual_factor"] ** years
    )

    adverse = cfg.patterns["adverse_selection"]
    late_entrant = rows.company_id.isin(targets["adverse_selection"]["companies"]) & (
        rows.enrollment_date >= pd.Timestamp(adverse["from_date"])
    )
    for claim_type in CLAIM_TYPES:
        multipliers[claim_type] = multipliers[claim_type].where(~late_entrant, multipliers[claim_type] * adverse["factor"])
    return multipliers


def inject_catastrophic_claim(
    cfg: GeneratorConfig,
    claims: pd.DataFrame,
    exposure_enriched: pd.DataFrame,
    targets: dict[str, dict[str, Any]],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Agrega un siniestro de alto costo pagado completo (beneficio catastrófico, sin tope de plan)."""
    event = targets["catastrophic_event"]
    candidates = exposure_enriched[
        (exposure_enriched.company_id == event["company_id"])
        & (exposure_enriched.month.dt.year == event["year"])
        & (exposure_enriched.role == "titular")
        & (exposure_enriched.covered_days > 0)
    ]
    row = candidates.iloc[int(rng.integers(0, len(candidates)))]
    occurrence = row.covered_first_day + pd.Timedelta(days=int(rng.integers(0, row.covered_days)))
    lag = cfg.payment_lag_days["alto_costo"]
    payment = occurrence + pd.Timedelta(days=int(round(rng.lognormal(lag["mu"], lag["sigma"]))))
    amount = float(event["amount_uf"])
    covered = amount * cfg.system_coverage[row.health_system]["alto_costo"]
    claim = pd.DataFrame(
        {
            "claim_id": [f"S{len(claims) + 1:08d}"],
            "insured_id": [row.insured_id],
            "company_id": [row.company_id],
            "contract_id": [row.contract_id],
            "claim_type": ["alto_costo"],
            "occurrence_date": [occurrence],
            "payment_date": [payment],
            "billed_uf": [covered + amount],
            "system_covered_uf": [covered],
            "reimbursed_uf": [amount],
        }
    )
    event["insured_id"] = str(row.insured_id)
    event["occurrence_date"] = str(occurrence.date())
    return pd.concat([claims, claim.astype(claims.dtypes.to_dict())], ignore_index=True)

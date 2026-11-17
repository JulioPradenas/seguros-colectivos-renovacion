"""Primas: precio inicial a partir del costo esperado verdadero, reajustes históricos y prima devengada mensual."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from colectivos.config import CLAIM_TYPES, GeneratorConfig
from colectivos.generator.health_claims import expected_frequency
from colectivos.generator.life_claims import holder_qx

BASE_YEAR = 2021


def mean_billed_uf(cfg: GeneratorConfig, claim_type: str, year: np.ndarray) -> np.ndarray:
    spec = cfg.severity[claim_type]
    if spec["dist"] == "pareto":
        alpha = cfg.catastrophic["pareto_alpha"]
        base = cfg.catastrophic["threshold_uf"] * alpha / (alpha - 1)
    else:
        base = spec["mean_uf"]
    return base * np.maximum((1 + cfg.annual_trend[claim_type]) ** (year - BASE_YEAR), 1.0)


def expected_annual_cost(
    cfg: GeneratorConfig,
    exposure_enriched: pd.DataFrame,
    company_effects: pd.Series,
    multipliers: dict[str, pd.Series],
    plans: pd.DataFrame,
    contracts: pd.DataFrame,
    mortality: pd.DataFrame,
    life_loadings: pd.Series,
) -> pd.DataFrame:
    """Costo esperado verdadero por persona-año, por empresa x rol x año (ignora deducible y tope)."""
    rows = exposure_enriched
    year = rows.month.dt.year.to_numpy()
    pct = plans.set_index(["plan_id", "claim_type"]).reimbursement_pct
    health = np.zeros(len(rows))
    for claim_type in CLAIM_TYPES:
        lam = expected_frequency(cfg, rows, claim_type, company_effects, multipliers[claim_type]).to_numpy()
        uncovered = 1 - rows.health_system.map({hs: cov[claim_type] for hs, cov in cfg.system_coverage.items()})
        plan_pct = pct.reindex(pd.MultiIndex.from_arrays([rows.plan_id, np.full(len(rows), claim_type)]))
        health += lam * mean_billed_uf(cfg, claim_type, year) * uncovered.to_numpy() * plan_pct.to_numpy()

    capital = contracts.drop_duplicates("contract_id").set_index("contract_id").life_capital_uf
    is_holder = (rows.role == "titular").to_numpy()
    qx = holder_qx(rows, mortality).to_numpy() * rows.company_id.map(life_loadings).to_numpy()
    life = np.where(is_holder, qx * rows.contract_id.map(capital).to_numpy() * rows.exposure.to_numpy() / 12, 0.0)

    frame = pd.DataFrame(
        {"company_id": rows.company_id, "role": rows.role, "year": year,
         "cost": health + life, "exposure_years": rows.exposure / 12}
    )
    grouped = frame.groupby(["company_id", "role", "year"], as_index=False)[["cost", "exposure_years"]].sum()
    grouped["expected_cost_per_year_uf"] = grouped.cost / grouped.exposure_years
    return grouped[["company_id", "role", "year", "expected_cost_per_year_uf"]]


def price_contracts(
    cfg: GeneratorConfig,
    contracts: pd.DataFrame,
    expected_cost: pd.DataFrame,
    targets: dict[str, dict[str, Any]],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Prima mensual por titular y por carga: inicial = costo esperado x (1 + loading) x ruido; luego reajustes."""
    priced = contracts.sort_values(["contract_id", "term_start"]).reset_index(drop=True)
    first_year = expected_cost.groupby(["company_id", "role"]).year.transform("min")
    base_cost = (
        expected_cost[expected_cost.year == first_year]
        .pivot(index="company_id", columns="role", values="expected_cost_per_year_uf")
    )
    inadequate = set(targets["inadequate_rate_changes"]["contracts"])
    sigma = cfg.initial_premium_noise_sigma
    change_spec = cfg.historic_rate_change

    holder_premium, dependent_premium, changes = [], [], []
    for contract_id, terms in priced.groupby("contract_id", sort=False):
        company_id = terms.company_id.iloc[0]
        noise = rng.lognormal(-sigma**2 / 2, sigma)
        holder = base_cost.loc[company_id, "titular"] * (1 + cfg.initial_loading) * noise / 12
        dep_cost = base_cost.loc[company_id].get("carga", np.nan)
        dependent = (dep_cost if pd.notna(dep_cost) else base_cost.loc[company_id, "titular"]) \
            * (1 + cfg.initial_loading) * noise / 12
        draws = rng.normal(change_spec["mean"], change_spec["sd"], len(terms))
        for k, term_start in enumerate(terms.term_start):
            if k == 0:
                change = np.nan
            elif term_start.year > cfg.end.year:
                change = np.nan
            else:
                change = 0.0 if contract_id in inadequate else float(draws[k])
                holder *= 1 + change
                dependent *= 1 + change
            holder_premium.append(holder)
            dependent_premium.append(dependent)
            changes.append(change)

    priced["premium_holder_uf"] = holder_premium
    priced["premium_dependent_uf"] = dependent_premium
    priced["rate_change_applied"] = changes
    return priced


def generate_premiums(contracts: pd.DataFrame, exposure_enriched: pd.DataFrame) -> pd.DataFrame:
    """Prima devengada por contrato x mes = exposición x prima mensual del rol en la vigencia del mes."""
    terms = contracts[["contract_id", "term_start", "premium_holder_uf", "premium_dependent_uf"]]
    terms = terms.astype({"term_start": "datetime64[ns]"}).sort_values("term_start")
    rows = exposure_enriched[["contract_id", "month", "role", "exposure"]].astype({"month": "datetime64[ns]"})
    rows = pd.merge_asof(rows.sort_values("month"), terms, left_on="month", right_on="term_start",
                         by="contract_id", direction="backward")
    rate = np.where(rows.role == "titular", rows.premium_holder_uf, rows.premium_dependent_uf)
    rows["earned_premium_uf"] = rows.exposure * rate
    premiums = rows.groupby(["contract_id", "month"], as_index=False).earned_premium_uf.sum()
    return premiums.sort_values(["contract_id", "month"]).reset_index(drop=True)

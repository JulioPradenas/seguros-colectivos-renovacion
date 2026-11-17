"""Cartera sintética: empresas cliente, planes, contratos anuales y asegurados."""

from __future__ import annotations

import numpy as np
import pandas as pd

from colectivos.config import CLAIM_TYPES, GeneratorConfig

PRE_PERIOD_CLIENT_START = pd.Timestamp("2015-01-01")
NEW_CLIENT_LAST_START = pd.Timestamp("2025-06-01")
LAST_PRICING_TERM_START = pd.Timestamp("2026-12-31")
DAYS_PER_YEAR = 365.25


def _random_month_starts(rng: np.random.Generator, first: pd.Timestamp, last: pd.Timestamp, size: int) -> pd.Series:
    months = pd.date_range(first, last, freq="MS")
    return pd.Series(months[rng.integers(0, len(months), size=size)])


def generate_companies(cfg: GeneratorConfig, rng: np.random.Generator) -> pd.DataFrame:
    n = cfg.n_companies
    size = cfg.company_size_lognormal
    holders = np.clip(np.round(rng.lognormal(size["mu"], size["sigma"], n)), size["min"], size["max"]).astype(int)

    is_new = rng.random(n) < cfg.new_client_share
    start = pd.Timestamp(cfg.start)
    old_since = _random_month_starts(rng, PRE_PERIOD_CLIENT_START, start - pd.DateOffset(months=1), n)
    new_since = _random_month_starts(rng, start, NEW_CLIENT_LAST_START, n)
    client_since = old_since.where(~is_new, new_since)

    end = pd.Timestamp(cfg.end)
    years = range(start.year, end.year + 1)
    lapse_draws = rng.random((n, len(years)))
    lapse_dates = []
    for i, since in enumerate(client_since):
        lapse = pd.NaT
        for k, year in enumerate(years):
            anniversary = pd.Timestamp(year=year, month=since.month, day=1)
            if since < anniversary <= end and lapse_draws[i, k] < cfg.company_lapse_rate:
                lapse = anniversary
                break
        lapse_dates.append(lapse)

    return pd.DataFrame(
        {
            "company_id": [f"EMP{i + 1:04d}" for i in range(n)],
            "industry": rng.choice(list(cfg.industries), size=n, p=list(cfg.industries.values())),
            "region": rng.choice(list(cfg.regions), size=n, p=list(cfg.regions.values())),
            "n_holders_target": holders,
            "client_since": client_since.to_numpy(),
            "lapse_date": pd.to_datetime(pd.Series(lapse_dates, dtype="datetime64[ns]")),
        }
    )


def generate_plans(cfg: GeneratorConfig) -> pd.DataFrame:
    rows = [
        {
            "plan_id": plan["plan_id"],
            "claim_type": claim_type,
            "reimbursement_pct": plan["reimbursement_pct"][claim_type],
            "deductible_uf": plan["deductible_uf"][claim_type],
            "annual_cap_uf": plan["annual_cap_uf"][claim_type],
        }
        for plan in cfg.plans
        for claim_type in CLAIM_TYPES
    ]
    return pd.DataFrame(rows)


def generate_contracts(cfg: GeneratorConfig, companies: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    plan_ids = [p["plan_id"] for p in cfg.plans]
    plan_weights = [p["weight"] for p in cfg.plans]
    chosen_plans = rng.choice(plan_ids, size=len(companies), p=plan_weights)
    capitals = rng.choice(cfg.life_capital_uf, size=len(companies))
    start = pd.Timestamp(cfg.start)

    rows = []
    for company, plan_id, capital in zip(companies.itertuples(index=False), chosen_plans, capitals):
        term_start = company.client_since
        while term_start <= LAST_PRICING_TERM_START:
            if pd.notna(company.lapse_date) and term_start >= company.lapse_date:
                break
            term_end = term_start + pd.DateOffset(years=1) - pd.Timedelta(days=1)
            if term_end >= start:
                rows.append(
                    {
                        "contract_id": company.company_id.replace("EMP", "CTR"),
                        "company_id": company.company_id,
                        "plan_id": plan_id,
                        "term_start": term_start,
                        "term_end": term_end,
                        "life_capital_uf": float(capital),
                        "expense_ratio": cfg.expense_ratio,
                        "commission_ratio": cfg.commission_ratio,
                    }
                )
            term_start = term_start + pd.DateOffset(years=1)
    return pd.DataFrame(rows)


def _holder_chains(cfg: GeneratorConfig, companies: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Cada puesto de titular lo ocupa una cadena de titulares: cuando uno se va, entra un reemplazo."""
    company_pos = np.repeat(np.arange(len(companies)), companies.n_holders_target.to_numpy())
    enrollment = companies.client_since.to_numpy().astype("datetime64[D]")[company_pos]
    horizon_end = np.datetime64(pd.Timestamp(cfg.end).date(), "D")
    lapse = companies.lapse_date.to_numpy().astype("datetime64[D]")[company_pos]
    has_lapse = ~np.isnat(lapse)
    coverage_end = np.where(has_lapse, lapse - np.timedelta64(1, "D"), horizon_end)

    generations = []
    while len(company_pos):
        tenure_days = np.ceil(rng.exponential(DAYS_PER_YEAR / cfg.annual_turnover, len(company_pos))).astype("int64")
        termination = enrollment + tenure_days.astype("timedelta64[D]") - np.timedelta64(1, "D")
        stays = termination >= coverage_end
        final_termination = np.where(
            stays,
            np.where(has_lapse, coverage_end, np.datetime64("NaT", "D")),
            termination,
        )
        generations.append(
            pd.DataFrame(
                {
                    "company_pos": company_pos,
                    "enrollment_date": enrollment.astype("datetime64[ns]"),
                    "termination_date": final_termination.astype("datetime64[ns]"),
                }
            )
        )
        replace = ~stays
        company_pos = company_pos[replace]
        enrollment = termination[replace] + np.timedelta64(1, "D")
        coverage_end = coverage_end[replace]
        has_lapse = has_lapse[replace]
    return pd.concat(generations, ignore_index=True)


def _ages(rng: np.random.Generator, spec: dict, size: int) -> np.ndarray:
    return np.clip(rng.normal(spec["mean"], spec["sd"], size), spec["min"], spec["max"])


def generate_insureds(cfg: GeneratorConfig, companies: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    holders = _holder_chains(cfg, companies, rng)
    holders = holders[holders.termination_date.isna() | (holders.termination_date >= pd.Timestamp(cfg.start))]
    holders = holders.sort_values(["company_pos", "enrollment_date"], kind="stable").reset_index(drop=True)
    n_holders = len(holders)

    fonasa_prob = np.full(n_holders, cfg.fonasa_share)
    shift = cfg.patterns.get("fonasa_shift")
    if shift:
        late = (holders.enrollment_date.dt.year >= shift["from_year"]).to_numpy()
        fonasa_prob[late] = min(cfg.fonasa_share * shift["share_multiplier"], 1.0)
    holders["health_system"] = np.where(rng.random(n_holders) < fonasa_prob, "fonasa", "isapre")
    holders["sex"] = rng.choice(["F", "M"], size=n_holders)
    holders["age_at_enrollment"] = _ages(rng, cfg.holder_age, n_holders)
    holders["role"] = "titular"
    holders["insured_id"] = [f"A{i + 1:07d}" for i in range(n_holders)]
    holders["holder_id"] = pd.Series(pd.NA, index=holders.index, dtype="string")

    n_deps = rng.poisson(cfg.dependents_per_holder, n_holders)
    dep_parent = np.repeat(np.arange(n_holders), n_deps)
    deps = holders.iloc[dep_parent][
        ["company_pos", "enrollment_date", "termination_date", "health_system"]
    ].reset_index(drop=True)
    n_total_deps = len(deps)
    is_child = rng.random(n_total_deps) < cfg.dependent_age["child_share"]
    deps["age_at_enrollment"] = np.where(
        is_child, rng.uniform(0, 24, n_total_deps), _ages(rng, cfg.dependent_age["adult"], n_total_deps)
    )
    deps["sex"] = rng.choice(["F", "M"], size=n_total_deps)
    deps["role"] = "carga"
    deps["insured_id"] = [f"A{n_holders + i + 1:07d}" for i in range(n_total_deps)]
    deps["holder_id"] = pd.Series(holders.insured_id.to_numpy()[dep_parent], dtype="string")

    insureds = pd.concat([holders, deps], ignore_index=True)
    insureds["company_id"] = companies.company_id.to_numpy()[insureds.company_pos.to_numpy()]
    age_days = np.round(insureds.age_at_enrollment.to_numpy() * DAYS_PER_YEAR).astype("int64")
    insureds["birth_date"] = insureds.enrollment_date - pd.to_timedelta(age_days, unit="D")
    return insureds[
        [
            "insured_id",
            "company_id",
            "holder_id",
            "role",
            "sex",
            "birth_date",
            "health_system",
            "enrollment_date",
            "termination_date",
        ]
    ].reset_index(drop=True)

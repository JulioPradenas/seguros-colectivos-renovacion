"""Siniestros de salud: frecuencia Poisson, severidad, cobertura de la previsión, reembolso y desfase de pago."""

from __future__ import annotations

import numpy as np
import pandas as pd

from colectivos.config import CLAIM_TYPES, GeneratorConfig
from colectivos.generator.exposure import assign_age_band

BASE_YEAR = 2021
FACTOR_COLUMNS = ("age_band", "sex", "health_system", "role", "industry", "region")
CLAIM_COLUMNS = [
    "claim_id", "insured_id", "company_id", "contract_id", "claim_type", "occurrence_date",
    "payment_date", "billed_uf", "system_covered_uf", "reimbursed_uf",
]


def enrich_exposure(
    exposure: pd.DataFrame, insureds: pd.DataFrame, companies: pd.DataFrame, contracts: pd.DataFrame
) -> pd.DataFrame:
    """Une la exposición con atributos del asegurado, la empresa y el contrato; agrega los días cubiertos del mes."""
    contract_of_company = contracts.drop_duplicates("company_id")[["company_id", "contract_id", "plan_id"]]
    enriched = (
        exposure.merge(
            insureds[["insured_id", "sex", "health_system", "role", "enrollment_date", "termination_date"]],
            on="insured_id",
        )
        .merge(companies[["company_id", "industry", "region"]], on="company_id")
        .merge(contract_of_company, on="company_id")
    )
    enriched["age_band"] = assign_age_band(enriched.age)
    month_end = enriched.month + pd.offsets.MonthEnd(0)
    enriched["covered_first_day"] = enriched[["month", "enrollment_date"]].max(axis=1)
    covered_last_day = pd.concat([month_end, enriched.termination_date], axis=1).min(axis=1)
    enriched["covered_days"] = (covered_last_day - enriched.covered_first_day).dt.days + 1
    return enriched.drop(columns=["enrollment_date", "termination_date"]).reset_index(drop=True)


def draw_company_effects(cfg: GeneratorConfig, companies: pd.DataFrame, rng: np.random.Generator) -> pd.Series:
    shape = cfg.company_effect_shape
    return pd.Series(rng.gamma(shape, 1 / shape, len(companies)), index=companies.company_id.to_numpy(),
                     name="company_effect")


def expected_frequency(
    cfg: GeneratorConfig,
    exposure_enriched: pd.DataFrame,
    claim_type: str,
    company_effect: pd.Series,
    pattern_multiplier: pd.Series | None = None,
) -> pd.Series:
    rows = exposure_enriched
    lam = np.full(len(rows), cfg.base_frequency[claim_type] / 12)
    for factor in FACTOR_COLUMNS:
        lam = lam * rows[factor].map(cfg.relativities[factor]).to_numpy(dtype=float)
    years_since_base = rows.month.dt.year.to_numpy() - BASE_YEAR
    lam = lam * (1 + cfg.frequency_trend[claim_type]) ** years_since_base
    lam = lam * rows.company_id.map(company_effect).to_numpy(dtype=float)
    season = cfg.seasonality
    if claim_type in season["claim_types"]:
        lam = lam * np.where(rows.month.dt.month.isin(season["months"]), season["factor"], 1.0)
    lam = lam * rows.exposure.to_numpy(dtype=float)
    if pattern_multiplier is not None:
        lam = lam * pattern_multiplier.to_numpy(dtype=float)
    return pd.Series(lam, index=rows.index, name=f"lambda_{claim_type}")


def draw_severity(cfg: GeneratorConfig, claim_type: str, years: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Monto presentado en UF, con la inflación médica del tipo aplicada desde el año base."""
    size = len(years)
    spec = cfg.severity[claim_type]
    if spec["dist"] == "gamma":
        shape = 1 / spec["cv"] ** 2
        amounts = rng.gamma(shape, spec["mean_uf"] / shape, size)
    elif spec["dist"] == "lognormal":
        sigma2 = np.log(1 + spec["cv"] ** 2)
        amounts = rng.lognormal(np.log(spec["mean_uf"]) - sigma2 / 2, np.sqrt(sigma2), size)
    elif spec["dist"] == "pareto":
        cat = cfg.catastrophic
        amounts = (rng.pareto(cat["pareto_alpha"], size) + 1) * cat["threshold_uf"]
    else:
        raise ValueError(f"distribución desconocida: {spec['dist']}")
    trend = (1 + cfg.annual_trend[claim_type]) ** (np.asarray(years) - BASE_YEAR)
    return amounts * np.maximum(trend, 1.0)


def compute_system_coverage(
    cfg: GeneratorConfig, billed_uf: pd.Series, health_system: pd.Series, claim_type: pd.Series
) -> pd.Series:
    share = pd.Series(
        [cfg.system_coverage[hs][ct] for hs, ct in zip(health_system, claim_type)], index=billed_uf.index
    )
    return billed_uf * share


def draw_claim_lines(
    cfg: GeneratorConfig,
    exposure_enriched: pd.DataFrame,
    company_effects: pd.Series,
    rng: np.random.Generator,
    pattern_multipliers: dict[str, pd.Series] | None = None,
) -> pd.DataFrame:
    """Líneas de prestación brutas (antes de cobertura y reembolso)."""
    pattern_multipliers = pattern_multipliers or {}
    parts = []
    for claim_type in CLAIM_TYPES:
        lam = expected_frequency(cfg, exposure_enriched, claim_type, company_effects,
                                 pattern_multipliers.get(claim_type))
        counts = rng.poisson(lam.to_numpy())
        rows = exposure_enriched.iloc[np.repeat(np.arange(len(exposure_enriched)), counts)]
        day_offset = (rng.random(len(rows)) * rows.covered_days.to_numpy()).astype("int64")
        occurrence = rows.covered_first_day.to_numpy() + day_offset.astype("timedelta64[D]")
        parts.append(
            pd.DataFrame(
                {
                    "insured_id": rows.insured_id.to_numpy(),
                    "company_id": rows.company_id.to_numpy(),
                    "contract_id": rows.contract_id.to_numpy(),
                    "health_system": rows.health_system.to_numpy(),
                    "claim_type": claim_type,
                    "occurrence_date": occurrence,
                    "billed_uf": draw_severity(cfg, claim_type, rows.month.dt.year.to_numpy(), rng),
                }
            )
        )
    return pd.concat(parts, ignore_index=True)


def apply_reimbursement(claims: pd.DataFrame, plans: pd.DataFrame, contracts: pd.DataFrame) -> pd.DataFrame:
    """Deducible y tope anuales por asegurado x tipo x vigencia, consumidos en orden de ocurrencia."""
    terms = contracts[["contract_id", "plan_id", "term_start"]].astype({"term_start": "datetime64[ns]"})
    terms = terms.sort_values("term_start")
    work = claims.reset_index(names="_order").astype({"occurrence_date": "datetime64[ns]"})
    work = work.sort_values("occurrence_date")
    work = pd.merge_asof(work, terms, left_on="occurrence_date", right_on="term_start", by="contract_id",
                         direction="backward")
    work = work.merge(plans, on=["plan_id", "claim_type"], how="left")

    keys = ["insured_id", "claim_type", "term_start"]
    work = work.sort_values([*keys, "occurrence_date", "_order"], kind="stable")
    copay = work.billed_uf - work.system_covered_uf
    over_deductible = (copay.groupby([work[k] for k in keys]).cumsum() - work.deductible_uf).clip(lower=0)
    eligible = over_deductible - over_deductible.groupby([work[k] for k in keys]).shift(fill_value=0.0)
    cum_reimbursable = (eligible * work.reimbursement_pct).groupby([work[k] for k in keys]).cumsum()
    capped = cum_reimbursable.clip(upper=work.annual_cap_uf)
    work["reimbursed_uf"] = capped - capped.groupby([work[k] for k in keys]).shift(fill_value=0.0)

    out = claims.copy()
    out["reimbursed_uf"] = work.set_index("_order").reimbursed_uf.reindex(range(len(claims))).to_numpy()
    return out


def generate_health_claims(
    cfg: GeneratorConfig,
    exposure: pd.DataFrame,
    insureds: pd.DataFrame,
    companies: pd.DataFrame,
    contracts: pd.DataFrame,
    plans: pd.DataFrame,
    company_effects: pd.Series,
    rng: np.random.Generator,
    pattern_multipliers: dict[str, pd.Series] | None = None,
) -> pd.DataFrame:
    enriched = enrich_exposure(exposure, insureds, companies, contracts)
    lines = draw_claim_lines(cfg, enriched, company_effects, rng, pattern_multipliers)
    lines["system_covered_uf"] = compute_system_coverage(cfg, lines.billed_uf, lines.health_system,
                                                         lines.claim_type)
    lines = apply_reimbursement(lines.reset_index(drop=True), plans, contracts)

    lag_days = np.empty(len(lines), dtype="int64")
    for claim_type, idx in lines.groupby("claim_type").indices.items():
        lag = cfg.payment_lag_days[claim_type]
        lag_days[idx] = np.round(rng.lognormal(lag["mu"], lag["sigma"], len(idx))).astype("int64")
    lines["payment_date"] = lines.occurrence_date + pd.to_timedelta(lag_days, unit="D")

    paid = lines[lines.reimbursed_uf > 1e-9].sort_values(["occurrence_date", "insured_id"], kind="stable")
    paid = paid.reset_index(drop=True)
    paid["claim_id"] = [f"S{i + 1:08d}" for i in range(len(paid))]
    return paid[CLAIM_COLUMNS]

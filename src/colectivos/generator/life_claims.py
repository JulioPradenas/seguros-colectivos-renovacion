"""Siniestros de vida colectiva: fallecimiento de titulares según tabla de mortalidad y recargo por grupo."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from colectivos.config import GeneratorConfig


def load_mortality(path: Path) -> pd.DataFrame:
    mortality = pd.read_csv(path, dtype={"age": "int64", "sex": "string", "qx": "float64"})
    return mortality[["age", "sex", "qx"]]


def holder_qx(exposure_enriched: pd.DataFrame, mortality: pd.DataFrame) -> pd.Series:
    """qx anual por fila de exposición (edad entera al inicio del mes, edades sobre la tabla toman la última)."""
    max_age = int(mortality.age.max())
    lookup = mortality.set_index(["age", "sex"]).qx
    keys = pd.MultiIndex.from_arrays([exposure_enriched.age.clip(upper=max_age), exposure_enriched.sex])
    return pd.Series(lookup.reindex(keys).to_numpy(), index=exposure_enriched.index)


def draw_life_group_loadings(cfg: GeneratorConfig, companies: pd.DataFrame, rng: np.random.Generator) -> pd.Series:
    spec = cfg.life_group_loading
    loading = np.clip(rng.normal(spec["mean"], spec["sd"], len(companies)), 0.3, None)
    return pd.Series(loading, index=companies.company_id.to_numpy(), name="life_group_loading")


def generate_life_claims(
    cfg: GeneratorConfig,
    exposure_enriched: pd.DataFrame,
    contracts: pd.DataFrame,
    mortality: pd.DataFrame,
    group_loadings: pd.Series,
    rng: np.random.Generator,
) -> pd.DataFrame:
    holders = exposure_enriched[exposure_enriched.role == "titular"]
    qx = holder_qx(holders, mortality) * holders.company_id.map(group_loadings).to_numpy()
    monthly_prob = 1 - (1 - qx.clip(upper=1.0)) ** (holders.exposure / 12)
    deaths = holders[rng.random(len(holders)) < monthly_prob.to_numpy()]
    deaths = deaths.sort_values("month").drop_duplicates("insured_id")

    day_offset = (rng.random(len(deaths)) * deaths.covered_days.to_numpy()).astype("int64")
    capital = contracts.drop_duplicates("contract_id").set_index("contract_id").life_capital_uf
    life = pd.DataFrame(
        {
            "insured_id": deaths.insured_id.to_numpy(),
            "contract_id": deaths.contract_id.to_numpy(),
            "death_date": deaths.covered_first_day.to_numpy() + day_offset.astype("timedelta64[D]"),
            "capital_paid_uf": deaths.contract_id.map(capital).to_numpy(dtype=float),
        }
    ).sort_values("death_date", kind="stable").reset_index(drop=True)
    life.insert(0, "claim_id", [f"V{i + 1:06d}" for i in range(len(life))])
    return life


def apply_deaths(insureds: pd.DataFrame, life_claims: pd.DataFrame) -> pd.DataFrame:
    """El fallecimiento termina la cobertura del titular y de sus cargas en la fecha de muerte."""
    deaths = life_claims.set_index("insured_id").death_date
    updated = insureds.copy()
    cutoff = updated.insured_id.map(deaths).fillna(updated.holder_id.map(deaths))
    has_cutoff = cutoff.notna()
    current = updated.loc[has_cutoff, "termination_date"]
    updated.loc[has_cutoff, "termination_date"] = current.where(
        current.notna() & (current <= cutoff[has_cutoff]), cutoff[has_cutoff]
    )
    return updated

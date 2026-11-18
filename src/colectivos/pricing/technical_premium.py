"""Prima técnica de renovación 2026 por contrato (modelo x credibilidad + recargo por siniestros grandes), reajuste
requerido e índice de suficiencia."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import logging

import duckdb
import numpy as np
import pandas as pd

from colectivos.config import PricingConfig
from colectivos.generator.exposure import assign_age_band
from colectivos.models.glm import REFERENCE_YEAR
from colectivos.models.oot import CostPredictor
from colectivos.pricing.credibility import CredibilityResult

logger = logging.getLogger(__name__)

DEFAULT_VALUATION_DATE = date(2025, 12, 31)
DAYS_PER_YEAR = 365.25
RENEWAL_COLUMNS = [
    "contract_id", "company_id", "industry", "term_start_2026", "n_insured_active",
    "current_premium_annual_uf", "expected_health_cost_uf", "expected_life_cost_uf",
    "technical_premium_annual_uf", "required_rate_change", "sufficiency_index",
    "exposure_years_hist", "low_exposure_flag", "expected_health_cost_model_uf", "experience_ae",
    "credibility_z", "credibility_factor", "large_loss_load_uf", "unseen_level_flag",
]


def technical_premium(
    health_cost_uf: float | pd.Series,
    life_cost_uf: float | pd.Series,
    expense_ratio: float,
    commission_ratio: float,
    target_margin: float,
) -> float | pd.Series:
    return (health_cost_uf + life_cost_uf) / (1 - expense_ratio - commission_ratio - target_margin)


def expected_life_cost(profile: pd.DataFrame, mortality: pd.DataFrame, capital_uf: pd.Series) -> pd.Series:
    """Costo anual esperado de vida = qx(edad, sexo) x capital, solo titulares."""
    max_age = int(mortality.age.max())
    lookup = mortality.set_index(["age", "sex"]).qx
    keys = pd.MultiIndex.from_arrays([profile.age.clip(upper=max_age).astype(int), profile.sex])
    qx = lookup.reindex(keys).to_numpy()
    is_holder = (profile.role == "titular").to_numpy()
    return pd.Series(np.where(is_holder, qx * capital_uf.to_numpy(), 0.0), index=profile.index)


def _term_midpoint(term_start: pd.Series) -> pd.Series:
    return term_start + pd.DateOffset(months=6)


def projection_year_c(term_start: pd.Series) -> pd.Series:
    """year_c del punto medio de la vigencia, en la escala de entrenamiento.

    En el GLM year_c = año calendario - 2023 promedia la exposición de todo el año, cuyo centro es la
    mitad del año: year_c = 0 corresponde a 2023-07-01, por eso se resta REFERENCE_YEAR + 0,5.
    """
    midpoint = _term_midpoint(term_start)
    fractional_year = midpoint.dt.year + (midpoint.dt.day_of_year - 1) / DAYS_PER_YEAR
    return fractional_year - (REFERENCE_YEAR + 0.5)


def renewal_rows(profile: pd.DataFrame, terms: pd.DataFrame) -> pd.DataFrame:
    """Vigentes al corte con edad y tramo al punto medio de la vigencia 2026, y su year_c de proyección."""
    rows = profile.merge(terms[["contract_id", "term_start", "life_capital_uf"]], on="contract_id", how="inner")
    midpoint = _term_midpoint(rows.term_start)
    rows["age"] = np.floor((midpoint - rows.birth_date).dt.days / DAYS_PER_YEAR).astype(int).clip(lower=0)
    rows["age_band"] = assign_age_band(rows.age)
    rows["year_c"] = projection_year_c(rows.term_start)
    return rows


def price_renewals(
    profile: pd.DataFrame,
    terms: pd.DataFrame,
    exposure_hist: pd.Series,
    model: CostPredictor,
    credibility: CredibilityResult,
    large_loss_load: float,
    mortality: pd.DataFrame,
    pricing: PricingConfig,
) -> pd.DataFrame:
    """Tarifica las vigencias 2026. `profile` = asegurados vigentes al corte; contratos sin vigentes se excluyen."""
    rows = renewal_rows(profile, terms)
    if rows.empty:
        return pd.DataFrame(columns=RENEWAL_COLUMNS)

    priced_parts = [
        model.predict_cost(group, float(year_c)) for year_c, group in rows.groupby("year_c")
    ]
    priced = pd.concat(priced_parts).sort_index()
    priced["expected_life_cost_uf"] = expected_life_cost(priced, mortality, priced.life_capital_uf)
    priced["is_holder"] = priced.role == "titular"

    by_contract = priced.groupby("contract_id").agg(
        n_insured_active=("insured_id", "size"),
        n_holders=("is_holder", "sum"),
        expected_health_cost_model_uf=("expected_health_cost_uf", "sum"),
        expected_life_cost_uf=("expected_life_cost_uf", "sum"),
        unseen_level_flag=("unseen_level_flag", "any"),
    )
    table = terms.set_index("contract_id").join(by_contract, how="inner").reset_index()
    experience = credibility.by_contract.set_index("contract_id")
    table["experience_ae"] = table.contract_id.map(experience.experience_ae).astype(float)
    table["credibility_z"] = table.contract_id.map(experience.credibility_z).fillna(0.0).astype(float)
    table["credibility_factor"] = (
        table.contract_id.map(experience.credibility_factor).fillna(credibility.center).astype(float)
    )
    table["large_loss_load_uf"] = large_loss_load * table.expected_health_cost_model_uf
    table["expected_health_cost_uf"] = (
        table.expected_health_cost_model_uf * table.credibility_factor + table.large_loss_load_uf
    )
    table["unseen_level_flag"] = table.unseen_level_flag.astype(bool)
    if table.unseen_level_flag.any():
        flagged = sorted(table.loc[table.unseen_level_flag, "contract_id"])
        logger.warning("Contratos tarificados con niveles no vistos al entrenar (nivel de respaldo): %s", flagged)
    n_dependents = table.n_insured_active - table.n_holders
    table["current_premium_annual_uf"] = 12 * (
        table.n_holders * table.premium_holder_uf + n_dependents * table.premium_dependent_uf
    )
    table["technical_premium_annual_uf"] = technical_premium(
        table.expected_health_cost_uf, table.expected_life_cost_uf,
        pricing.expense_ratio, pricing.commission_ratio, pricing.target_margin,
    )
    table["required_rate_change"] = table.technical_premium_annual_uf / table.current_premium_annual_uf - 1
    table["sufficiency_index"] = table.current_premium_annual_uf / table.technical_premium_annual_uf
    table["exposure_years_hist"] = table.contract_id.map(exposure_hist).fillna(0.0).astype(float)
    table["low_exposure_flag"] = table.exposure_years_hist < pricing.low_exposure_threshold_years
    table = table.rename(columns={"term_start": "term_start_2026"})
    return table[RENEWAL_COLUMNS].sort_values("contract_id").reset_index(drop=True)


def load_renewal_inputs(
    db_path: Path, pricing: PricingConfig, valuation_date: date = DEFAULT_VALUATION_DATE
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Lee del warehouse los asegurados vigentes al corte, las vigencias que empiezan en pricing_year y la
    exposición histórica por contrato."""
    with duckdb.connect(str(db_path), read_only=True) as con:
        profile = con.execute(
            """
            WITH contract_of_company AS (
                SELECT DISTINCT company_id, contract_id
                FROM staging.stg_contracts
            )
            SELECT
                contract_of_company.contract_id,
                insureds.insured_id,
                insureds.role,
                insureds.sex,
                insureds.birth_date,
                insureds.health_system,
                companies.industry,
                companies.region
            FROM staging.stg_insureds AS insureds
            INNER JOIN staging.stg_companies AS companies
                ON insureds.company_id = companies.company_id
            INNER JOIN contract_of_company
                ON insureds.company_id = contract_of_company.company_id
            WHERE insureds.enrollment_date <= ?
                AND (insureds.termination_date IS NULL OR insureds.termination_date > ?)
            """,
            [valuation_date, valuation_date],
        ).df()
        terms = con.execute(
            """
            SELECT
                contracts.contract_id,
                contracts.company_id,
                companies.industry,
                contracts.term_start,
                contracts.premium_holder_uf,
                contracts.premium_dependent_uf,
                contracts.life_capital_uf
            FROM staging.stg_contracts AS contracts
            INNER JOIN staging.stg_companies AS companies
                ON contracts.company_id = companies.company_id
            WHERE YEAR(contracts.term_start) = ?
            """,
            [pricing.pricing_year],
        ).df()
        exposure_hist = con.execute(
            """
            SELECT contract_id, SUM(exposure_years) AS exposure_years
            FROM intermediate.int_exposure_contract_year
            GROUP BY contract_id
            """
        ).df().set_index("contract_id").exposure_years
    for frame, column in ((profile, "birth_date"), (terms, "term_start")):
        frame[column] = pd.to_datetime(frame[column])
    return profile, terms, exposure_hist


def renewal_table(
    db_path: Path,
    model: CostPredictor,
    credibility: CredibilityResult,
    large_loss_load: float,
    mortality: pd.DataFrame,
    pricing: PricingConfig,
    valuation_date: date = DEFAULT_VALUATION_DATE,
) -> pd.DataFrame:
    profile, terms, exposure_hist = load_renewal_inputs(db_path, pricing, valuation_date)
    return price_renewals(profile, terms, exposure_hist, model, credibility, large_loss_load, mortality, pricing)


def save_renewal_mart(db_path: Path, renewal: pd.DataFrame) -> None:
    with duckdb.connect(str(db_path)) as con:
        con.register("renewal_frame", renewal)
        con.execute("CREATE OR REPLACE TABLE marts.mart_renewal_2026 AS SELECT * FROM renewal_frame")
        con.unregister("renewal_frame")

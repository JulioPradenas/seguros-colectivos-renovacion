import json

import numpy as np
import pandas as pd
import pytest

from colectivos.config import PricingConfig, load_pricing_config
from colectivos.generator.life_claims import load_mortality
from colectivos.models.oot import BaselineModel
from colectivos.pricing.credibility import CredibilityResult, neutral_credibility
from colectivos.pricing.technical_premium import (
    expected_life_cost,
    price_renewals,
    renewal_table,
    technical_premium,
)
from tests.conftest import CONFIG_DIR

PRICING = load_pricing_config(CONFIG_DIR / "pricing.yaml")
MORTALITY = load_mortality(CONFIG_DIR / "mortality" / "makeham_supuesto.csv")
NEUTRAL = neutral_credibility()


def _credibility(factors: dict[str, float], center: float = 1.0) -> CredibilityResult:
    by_contract = pd.DataFrame(
        {
            "contract_id": list(factors),
            "weight": 100.0,
            "experience_ae": list(factors.values()),
            "credibility_z": 1.0,
            "credibility_factor": list(factors.values()),
            "n_years": 3,
        }
    )
    return CredibilityResult(s2=1.0, a=1.0, k=1.0, center=center, by_contract=by_contract)


def _profile(contract_id: str, roles: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "contract_id": contract_id,
            "insured_id": [f"{contract_id}-{i}" for i in range(len(roles))],
            "role": roles,
            "sex": "M",
            "birth_date": pd.Timestamp("1985-01-01"),
            "health_system": "isapre",
            "industry": "retail",
            "region": "metropolitana",
        }
    )


def _terms(contract_ids: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "contract_id": contract_ids,
            "company_id": [c.replace("CTR", "EMP") for c in contract_ids],
            "industry": "retail",
            "term_start": pd.Timestamp("2026-03-01"),
            "premium_holder_uf": 1.0,
            "premium_dependent_uf": 0.5,
            "life_capital_uf": 200.0,
        }
    )


def test_technical_premium_formula():
    assert technical_premium(1.0, 0.1, 0.12, 0.08, 0.05) == pytest.approx(1.1 / 0.75)


def test_required_rate_change_and_sufficiency(models):
    table = price_renewals(_profile("CTR1", ["titular", "carga"]), _terms(["CTR1"]),
                           pd.Series({"CTR1": 5.0}), BaselineModel(models), NEUTRAL, 0.0, MORTALITY, PRICING)
    row = table.iloc[0]
    assert row.current_premium_annual_uf == pytest.approx(12 * (1.0 + 0.5))
    assert row.required_rate_change == pytest.approx(row.technical_premium_annual_uf / row.current_premium_annual_uf - 1)
    assert row.sufficiency_index == pytest.approx(row.current_premium_annual_uf / row.technical_premium_annual_uf)
    assert row.n_insured_active == 2


def test_contract_without_active_insureds_excluded(models):
    table = price_renewals(_profile("CTR1", ["titular"]), _terms(["CTR1", "CTR2"]),
                           pd.Series({"CTR1": 5.0, "CTR2": 3.0}), BaselineModel(models), NEUTRAL, 0.0,
                           MORTALITY, PRICING)
    assert table.contract_id.tolist() == ["CTR1"]
    # experience_ae es NaN para un contrato sin experiencia (no hay A/E que mostrar).
    assert np.isfinite(table.select_dtypes("number").drop(columns="experience_ae").to_numpy()).all()


def test_low_exposure_flag(models):
    profile = pd.concat([_profile("CTR1", ["titular"]), _profile("CTR2", ["titular"])])
    table = price_renewals(profile, _terms(["CTR1", "CTR2"]), pd.Series({"CTR1": 0.4, "CTR2": 3.0}),
                           BaselineModel(models), NEUTRAL, 0.0, MORTALITY, PRICING).set_index("contract_id")
    assert table.loc["CTR1", "low_exposure_flag"]
    assert not table.loc["CTR2", "low_exposure_flag"]


def test_life_cost_only_holders():
    profile = pd.DataFrame({"role": ["titular", "carga"], "sex": ["M", "M"], "age": [41, 41]})
    cost = expected_life_cost(profile, MORTALITY, pd.Series([200.0, 200.0]))
    qx = MORTALITY.set_index(["age", "sex"]).qx.loc[(41, "M")]
    assert cost.tolist() == pytest.approx([qx * 200.0, 0.0])


def test_renewal_table_from_warehouse(db_path, models):
    table = renewal_table(db_path, BaselineModel(models), NEUTRAL, 0.0, MORTALITY, PRICING)
    assert not table.empty
    assert (table.term_start_2026.dt.year == 2026).all()
    assert (table.n_insured_active > 0).all()
    assert table.contract_id.is_unique
    assert (table.technical_premium_annual_uf > 0).all()


@pytest.mark.slow
def test_inadequate_contracts_need_higher_rate_change(medium_db_path):
    # Con 20 empresas (small) el GLM es demasiado ruidoso; el patrón se valida con 100 empresas.
    import duckdb

    from colectivos.models.glm import fit_all

    with duckdb.connect(str(medium_db_path), read_only=True) as con:
        medium_models = fit_all(con.execute("SELECT * FROM marts.mart_model_cells").df(), (2021, 2024))
    table = renewal_table(medium_db_path, BaselineModel(medium_models), NEUTRAL, 0.0, MORTALITY, PRICING)
    truth = medium_db_path.parent / "truth" / "patterns.json"
    inadequate = json.loads(truth.read_text())["inadequate_rate_changes"]["contracts"]
    flagged = table.contract_id.isin(inadequate)
    assert flagged.any()
    assert table[flagged].required_rate_change.median() > table[~flagged].required_rate_change.median()


def test_save_renewal_mart_is_exported(db_path, models, tmp_path):
    import shutil

    from colectivos.pricing.technical_premium import save_renewal_mart
    from colectivos.warehouse.export import export_marts

    db_copy = tmp_path / "w.duckdb"
    shutil.copy(db_path, db_copy)
    table = renewal_table(db_copy, BaselineModel(models), NEUTRAL, 0.0, MORTALITY, PRICING)
    save_renewal_mart(db_copy, table)
    exported = {p.name for p in export_marts(db_copy, tmp_path / "csv")}
    assert "mart_renewal_2026.csv" in exported
    assert len(pd.read_csv(tmp_path / "csv" / "mart_renewal_2026.csv")) == len(table)


def test_projection_year_c_matches_training_scale():
    from colectivos.pricing.technical_premium import projection_year_c

    # En entrenamiento year_c = año calendario - 2023, centrado a mitad de año: year_c = 0 es 2023-07-01.
    starts = pd.Series(pd.to_datetime(["2023-01-01", "2026-01-01", "2026-07-01"]))
    assert projection_year_c(starts).round(2).tolist() == [0.0, 3.0, 3.5]


def _two_contracts() -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    profile = pd.concat([_profile("CTR1", ["titular", "carga"]), _profile("CTR2", ["titular"])], ignore_index=True)
    return profile, _terms(["CTR1", "CTR2"]), pd.Series({"CTR1": 5.0, "CTR2": 3.0})


def test_neutral_credibility_equals_model_only(models):
    from colectivos.pricing.technical_premium import RENEWAL_COLUMNS

    profile, terms, exposure = _two_contracts()
    table = price_renewals(profile, terms, exposure, BaselineModel(models), NEUTRAL, 0.0, MORTALITY, PRICING)
    assert list(table.columns) == RENEWAL_COLUMNS
    assert table.expected_health_cost_uf.tolist() == table.expected_health_cost_model_uf.tolist()
    assert (table.credibility_z == 0).all() and (table.credibility_factor == 1).all()
    assert (table.large_loss_load_uf == 0).all()
    model_cost = BaselineModel(models).predict_cost(profile.assign(
        age=40, age_band="30-44"), 3.17).groupby(profile.contract_id).expected_health_cost_uf.sum()
    assert table.set_index("contract_id").expected_health_cost_model_uf.to_numpy() == pytest.approx(
        model_cost.to_numpy(), rel=0.05
    )


def test_credibility_factor_scales_health_cost_only(models):
    profile, terms, exposure = _two_contracts()
    model = BaselineModel(models)
    neutral = price_renewals(profile, terms, exposure, model, NEUTRAL, 0.0, MORTALITY, PRICING).set_index("contract_id")
    credible = price_renewals(
        profile, terms, exposure, model, _credibility({"CTR1": 1.3, "CTR2": 0.8}), 0.0, MORTALITY, PRICING
    ).set_index("contract_id")
    assert credible.expected_health_cost_uf.to_numpy() == pytest.approx(
        neutral.expected_health_cost_uf.to_numpy() * np.array([1.3, 0.8])
    )
    assert credible.expected_life_cost_uf.tolist() == neutral.expected_life_cost_uf.tolist()
    assert credible.credibility_factor.tolist() == [1.3, 0.8]


def test_large_loss_load_added(models):
    profile, terms, exposure = _two_contracts()
    table = price_renewals(
        profile, terms, exposure, BaselineModel(models), _credibility({"CTR1": 1.3, "CTR2": 0.8}), 0.05,
        MORTALITY, PRICING,
    )
    assert table.large_loss_load_uf.to_numpy() == pytest.approx(0.05 * table.expected_health_cost_model_uf.to_numpy())
    expected = table.expected_health_cost_model_uf * table.credibility_factor + table.large_loss_load_uf
    assert table.expected_health_cost_uf.to_numpy() == pytest.approx(expected.to_numpy())


def test_contract_without_experience_gets_center(models):
    profile, terms, exposure = _two_contracts()
    table = price_renewals(
        profile, terms, exposure, BaselineModel(models), _credibility({"CTR2": 0.8}, center=1.1), 0.0,
        MORTALITY, PRICING,
    ).set_index("contract_id")
    assert table.loc["CTR1", "credibility_z"] == 0.0
    assert table.loc["CTR1", "credibility_factor"] == pytest.approx(1.1)
    assert np.isnan(table.loc["CTR1", "experience_ae"])
    assert table.loc["CTR2", "credibility_factor"] == pytest.approx(0.8)


def test_unseen_level_flag_propagates_to_contract(two_stage_model, caplog):
    import logging

    profile, terms, exposure = _two_contracts()
    profile.loc[profile.contract_id == "CTR2", "region"] = "region_inexistente"
    with caplog.at_level(logging.WARNING):
        table = price_renewals(profile, terms, exposure, two_stage_model, NEUTRAL, 0.0, MORTALITY, PRICING)
    flags = table.set_index("contract_id").unseen_level_flag
    assert bool(flags.loc["CTR2"]) is True
    assert "CTR2" in caplog.text
    assert np.isfinite(table.technical_premium_annual_uf).all()

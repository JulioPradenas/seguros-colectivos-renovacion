import logging

import duckdb
import numpy as np
import pandas as pd
import pytest

from colectivos.config import load_pricing_config
from colectivos.models.ibnr import estimate_ibnr
from colectivos.models.two_stage import fit_two_stage
from colectivos.models.ultimates import cells_to_ultimate, to_yearly
from colectivos.pricing.credibility import (
    CredibilityResult,
    buhlmann_straub,
    contract_experience,
    large_loss_load,
)

PRICING_CONFIG = "config/pricing.yaml"


def _experience(weights: dict[str, list[float]], ratios: dict[str, list[float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"contract_id": contract, "year": 2021 + j, "weight": weight, "ratio": ratios[contract][j]}
            for contract, contract_weights in weights.items()
            for j, weight in enumerate(contract_weights)
        ]
    )


def test_buhlmann_straub_textbook_values(caplog):
    experience = _experience(
        {"A": [100, 120, 140], "B": [50, 60, 70], "C": [200, 200, 200]},
        {"A": [0.9, 1.1, 1.0], "B": [1.4, 1.2, 1.3], "C": [0.8, 0.85, 0.75]},
    )
    with caplog.at_level(logging.WARNING):
        result = buhlmann_straub(experience)
    assert isinstance(result, CredibilityResult)
    assert result.s2 == pytest.approx(0.713889, abs=1e-6)
    assert result.a == pytest.approx(0.050553, abs=1e-6)
    assert result.k == pytest.approx(14.121478, abs=1e-6)
    assert result.center == pytest.approx(0.942982, abs=1e-6)
    assert "center" in caplog.text
    by_contract = result.by_contract.set_index("contract_id")
    assert by_contract.credibility_z.to_numpy() == pytest.approx([0.962254, 0.927254, 0.977005], abs=1e-6)
    assert by_contract.experience_ae.to_numpy() == pytest.approx([1.005556, 1.294444, 0.8], abs=1e-6)
    expected_factor = by_contract.credibility_z * by_contract.experience_ae + (1 - by_contract.credibility_z) * 0.942982
    assert by_contract.credibility_factor.to_numpy() == pytest.approx(expected_factor.to_numpy(), abs=1e-6)
    assert by_contract.n_years.tolist() == [3, 3, 3]
    assert by_contract.weight.tolist() == [360, 180, 600]


def test_zero_between_variance_gives_zero_credibility(caplog):
    experience = _experience(
        {"A": [100, 100], "B": [100, 100], "C": [100, 100]},
        {"A": [0.9, 1.1], "B": [1.1, 0.9], "C": [0.95, 1.05]},
    )
    with caplog.at_level(logging.WARNING):
        result = buhlmann_straub(experience)
    assert result.k == np.inf
    assert (result.by_contract.credibility_z == 0).all()
    assert result.by_contract.credibility_factor.to_numpy() == pytest.approx(np.full(3, result.center))
    assert result.center == 1.0
    assert "a <= 0" in caplog.text


def test_single_year_and_tiny_weight_contract_is_finite():
    experience = _experience(
        {"A": [100, 120, 140], "B": [50, 60, 70], "C": [200, 200, 200], "D": [1e-6]},
        {"A": [0.9, 1.1, 1.0], "B": [1.4, 1.2, 1.3], "C": [0.8, 0.85, 0.75], "D": [5.0]},
    )
    result = buhlmann_straub(experience)
    new_contract = result.by_contract.set_index("contract_id").loc["D"]
    assert new_contract.n_years == 1
    assert new_contract.credibility_z == pytest.approx(0.0, abs=1e-6)
    assert np.isfinite(new_contract.credibility_factor)
    assert np.isfinite(result.by_contract[["credibility_z", "credibility_factor"]].to_numpy()).all()


def test_contract_experience_ratio_is_actual_over_expected(cells_yearly, two_stage_model):
    experience = contract_experience(cells_yearly, two_stage_model, (2021, 2024))
    assert {"contract_id", "year", "ratio", "weight"} <= set(experience.columns)
    assert (experience.weight > 0).all()
    assert set(experience.year) == {2021, 2022, 2023, 2024}
    actual = cells_yearly[cells_yearly.year.between(2021, 2024)].reimbursed_capped_ult_uf.sum()
    assert (experience.ratio * experience.weight).sum() == pytest.approx(actual, rel=1e-9)


def test_large_loss_load_counts_excess_once(cells_yearly, two_stage_model):
    years = (2021, 2024)
    load = large_loss_load(cells_yearly, two_stage_model, years)
    expected_capped = contract_experience(cells_yearly, two_stage_model, years).weight.sum()
    train = cells_yearly[cells_yearly.year.between(*years)]
    excess = (train.reimbursed_ult_uf - train.reimbursed_capped_ult_uf).sum()
    assert excess > 0
    assert load * expected_capped == pytest.approx(excess, rel=1e-9)


def _medium_yearly(db_path) -> pd.DataFrame:
    with duckdb.connect(str(db_path), read_only=True) as con:
        cells = con.execute("SELECT * FROM marts.mart_model_cells_company").df()
        development = con.execute("SELECT * FROM marts.mart_development_quarterly").df()
    exposure = cells.groupby(["claim_type", "origin_quarter"], as_index=False).exposure_years.sum()
    ibnr = estimate_ibnr(development, exposure, load_pricing_config(PRICING_CONFIG))
    return to_yearly(cells_to_ultimate(cells, ibnr))


@pytest.mark.slow
def test_credibility_reduces_rate_change_correlation_with_company_effect(medium_db_path):
    cfg = load_pricing_config(PRICING_CONFIG)
    yearly = _medium_yearly(medium_db_path)
    model = fit_two_stage(yearly, cfg.train_years_final, cfg)
    result = buhlmann_straub(contract_experience(yearly, model, cfg.train_years_final))
    company_of_contract = yearly.drop_duplicates("contract_id").set_index("contract_id").company_id
    effects = pd.read_parquet(medium_db_path.parent / "truth" / "company_effects.parquet").set_index("company_id")
    by_contract = result.by_contract.assign(company_id=lambda d: d.contract_id.map(company_of_contract))
    effect = by_contract.company_id.map(effects.company_effect)
    correlation = np.corrcoef(np.log(by_contract.credibility_factor), np.log(effect))[0, 1]
    assert correlation > 0.3, correlation


def test_contract_experience_detail_matches_credibility_input(cells_yearly, two_stage_model):
    from colectivos.pricing.credibility import contract_experience_detail

    years = (2021, 2024)
    detail = contract_experience_detail(cells_yearly, two_stage_model, years)
    assert {
        "contract_id", "year", "claim_type", "exposure_years", "n_claims", "n_claims_ult", "reimbursed_uf",
        "reimbursed_ult_uf", "reimbursed_capped_ult_uf", "expected_uf", "ratio",
    } <= set(detail.columns)
    assert not detail.duplicated(["contract_id", "year", "claim_type"]).any()
    by_contract_year = detail.groupby(["contract_id", "year"])[["reimbursed_capped_ult_uf", "expected_uf"]].sum()
    experience = contract_experience(cells_yearly, two_stage_model, years).set_index(["contract_id", "year"])
    assert by_contract_year.expected_uf.loc[experience.index].to_numpy() == pytest.approx(experience.weight.to_numpy())
    assert (by_contract_year.reimbursed_capped_ult_uf / by_contract_year.expected_uf).loc[experience.index].to_numpy() == pytest.approx(
        experience.ratio.to_numpy()
    )
    assert detail.reimbursed_ult_uf.sum() == pytest.approx(
        cells_yearly[cells_yearly.year.between(*years)].reimbursed_ult_uf.sum()
    )

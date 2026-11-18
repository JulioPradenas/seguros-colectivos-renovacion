import duckdb
import numpy as np
import pytest

from colectivos.config import CLAIM_TYPES
from colectivos.models.glm import REFERENCE_YEAR, actual_vs_expected
from colectivos.models.oot import BaselineModel, gini, out_of_time_report

TEST_YEAR = 2025


def test_gini_perfect_order_positive_and_reversed_negative():
    actual = np.array([1.0, 2.0, 3.0, 4.0])
    exposure = np.ones(4)
    perfect = gini(np.array([1.0, 2.0, 3.0, 4.0]), actual, exposure)
    reversed_ = gini(np.array([4.0, 3.0, 2.0, 1.0]), actual, exposure)
    assert perfect == pytest.approx(0.25)
    assert reversed_ == pytest.approx(-perfect)
    assert gini(np.full(4, 7.0), actual, exposure) == pytest.approx(0.0)


@pytest.fixture(scope="module")
def report(models, two_stage_model, tweedie_model, cells_yearly):
    predictors = {"baseline": BaselineModel(models), "two_stage": two_stage_model, "tweedie": tweedie_model}
    return out_of_time_report(predictors, cells_yearly[cells_yearly.year == TEST_YEAR], TEST_YEAR)


def test_oot_report_has_all_models_and_types(report):
    assert set(report) == {"by_type", "by_segment", "contract", "contract_predictions"}
    by_type = report["by_type"]
    assert set(by_type.model) == {"baseline", "two_stage", "tweedie"}
    assert set(by_type.claim_type) == set(CLAIM_TYPES)
    assert {"actual_uf", "expected_uf", "ae", "deviance"} <= set(by_type.columns)
    assert np.isfinite(by_type[["actual_uf", "expected_uf", "ae", "deviance"]].to_numpy()).all()
    assert by_type.ae.to_numpy() == pytest.approx((by_type.actual_uf / by_type.expected_uf).to_numpy())
    segments = report["by_segment"]
    assert set(segments.factor) == {"industry", "age_band", "health_system", "company_size"}
    assert set(segments[segments.factor == "company_size"].level) == {"Q1", "Q2", "Q3", "Q4"}
    contract = report["contract"].set_index("model")
    assert set(contract.index) == {"baseline", "two_stage", "tweedie"}
    assert np.isfinite(contract[["gini", "rmse_per_py", "ae"]].to_numpy()).all()


def test_report_totals_are_consistent_across_views(report):
    total_actual = report["by_type"].groupby("model").actual_uf.sum()
    total_expected = report["by_type"].groupby("model").expected_uf.sum()
    contract = report["contract"].set_index("model")
    assert contract.ae.to_numpy() == pytest.approx((total_actual / total_expected).loc[contract.index].to_numpy())


def test_baseline_matches_phase1_ae(models, db_path):
    with duckdb.connect(str(db_path), read_only=True) as con:
        cells = con.execute("SELECT * FROM marts.mart_model_cells").df()
    phase1 = actual_vs_expected(models, cells, TEST_YEAR).set_index("claim_type")
    test = cells[cells.year == TEST_YEAR].reset_index(drop=True)
    frequency = BaselineModel(models).predict_frequency(test, TEST_YEAR - REFERENCE_YEAR)
    for claim_type in phase1.index:
        rows = test.claim_type == claim_type
        expected = (frequency.loc[rows, f"expected_freq_{claim_type}"] * test.loc[rows, "exposure_years"]).sum()
        ae = test.loc[rows, "n_claims"].sum() / expected
        assert ae == pytest.approx(phase1.loc[claim_type, "ae_frequency"], rel=1e-9), claim_type


def _contract_frame(model: str, expected: list[float]) -> "pd.DataFrame":
    import pandas as pd

    return pd.DataFrame(
        {"model": model, "contract_id": [f"C{i}" for i in range(len(expected))],
         "actual_uf": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0][: len(expected)], "expected_uf": expected, "exposure": 1.0}
    )


def test_gini_bootstrap_identical_models_give_zero_difference():
    import pandas as pd

    from colectivos.models.oot import gini_bootstrap

    contracts = pd.concat([_contract_frame("a", [1, 2, 3, 4, 5, 6]), _contract_frame("b", [1, 2, 3, 4, 5, 6])])
    result = gini_bootstrap(contracts, champion="a", challenger="b", n_boot=200, seed=0)
    assert result["diff_mean"] == pytest.approx(0.0)
    assert result["diff_low"] == pytest.approx(0.0) and result["diff_high"] == pytest.approx(0.0)


def test_gini_bootstrap_detects_better_challenger_and_is_reproducible():
    import pandas as pd

    from colectivos.models.oot import gini_bootstrap

    contracts = pd.concat([_contract_frame("a", [6, 5, 4, 3, 2, 1]), _contract_frame("b", [1, 2, 3, 4, 5, 6])])
    first = gini_bootstrap(contracts, champion="a", challenger="b", n_boot=200, seed=0)
    second = gini_bootstrap(contracts, champion="a", challenger="b", n_boot=200, seed=0)
    assert first == second
    assert first["diff_low"] > 0
    assert first["p_challenger_better"] == pytest.approx(1.0)
    assert first["gini_challenger"] > first["gini_champion"]


def test_report_includes_contract_predictions(report):
    contracts = report["contract_predictions"]
    assert {"model", "contract_id", "actual_uf", "expected_uf", "exposure"} <= set(contracts.columns)
    assert set(contracts.model) == {"baseline", "two_stage", "tweedie"}

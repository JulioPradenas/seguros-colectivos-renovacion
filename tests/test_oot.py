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
    assert set(report) == {"by_type", "by_segment", "contract"}
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

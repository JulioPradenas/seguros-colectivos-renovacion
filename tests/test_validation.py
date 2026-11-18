import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from colectivos.config import CLAIM_TYPES, load_pricing_config
from colectivos.generator.life_claims import load_mortality
from colectivos.models.ibnr import estimate_ibnr
from colectivos.models.oot import BaselineModel
from colectivos.models.ultimates import save_ibnr_mart
from colectivos.pricing.credibility import buhlmann_straub, contract_experience
from colectivos.pricing.technical_premium import renewal_table
from colectivos.validation.truth_checks import (
    credibility_gain,
    ibnr_error,
    oot_against_truth,
    pattern_detection,
    relativity_recovery,
    trend_recovery,
)
from tests.conftest import CONFIG_DIR

PRICING = load_pricing_config(CONFIG_DIR / "pricing.yaml")
MORTALITY = load_mortality(CONFIG_DIR / "mortality" / "makeham_supuesto.csv")
SRC = Path(__file__).resolve().parents[1] / "src" / "colectivos"


@pytest.fixture(scope="module")
def db_with_ibnr(db_path, tmp_path_factory) -> Path:
    import duckdb

    db_copy = tmp_path_factory.mktemp("validation") / "warehouse.duckdb"
    shutil.copy(db_path, db_copy)
    with duckdb.connect(str(db_copy), read_only=True) as con:
        cells = con.execute("SELECT * FROM marts.mart_model_cells_company").df()
        development = con.execute("SELECT * FROM marts.mart_development_quarterly").df()
    exposure = cells.groupby(["claim_type", "origin_quarter"], as_index=False).exposure_years.sum()
    save_ibnr_mart(db_copy, estimate_ibnr(development, exposure, PRICING))
    return db_copy


def test_ibnr_error_rows_cover_all_types_and_quarters(db_with_ibnr, truth_dir):
    errors = ibnr_error(db_with_ibnr, truth_dir)
    assert {"claim_type", "origin_quarter", "ibnr_est_uf", "ibnr_true_uf", "error_uf", "error_rel"} <= set(errors.columns)
    assert set(errors.claim_type) == set(CLAIM_TYPES)
    assert errors.groupby("claim_type").origin_quarter.nunique().eq(20).all()
    assert errors.error_uf.to_numpy() == pytest.approx((errors.ibnr_est_uf - errors.ibnr_true_uf).to_numpy())


def test_true_ibnr_nonnegative(db_with_ibnr, truth_dir):
    errors = ibnr_error(db_with_ibnr, truth_dir)
    assert (errors.ibnr_true_uf >= -1e-9).all()
    recent = errors[pd.to_datetime(errors.origin_quarter) == pd.Timestamp("2025-10-01")]
    assert (recent.ibnr_true_uf > 0).any()


def test_trend_and_relativity_recovery_against_parameters(two_stage_model, truth_dir):
    trends = trend_recovery(two_stage_model.trends, truth_dir)
    assert set(trends.claim_type) == set(CLAIM_TYPES)
    assert {"freq_est", "freq_true", "sev_est", "sev_true", "total_est", "total_true"} <= set(trends.columns)
    relativities = relativity_recovery(two_stage_model, truth_dir)
    assert {"claim_type", "factor", "level", "base_level", "estimated", "true"} <= set(relativities.columns)
    base_rows = relativities[relativities.level == relativities.base_level]
    assert (base_rows.estimated == 1.0).all() and (base_rows.true == 1.0).all()


def test_pattern_detection_reports_five_patterns(db_path, two_stage_model, cells_yearly, truth_dir):
    credibility = buhlmann_straub(contract_experience(cells_yearly, two_stage_model, two_stage_model.train_years))
    renewal = renewal_table(db_path, two_stage_model, credibility, 0.0, MORTALITY, PRICING)
    patterns = pattern_detection(db_path, two_stage_model, renewal, truth_dir)
    assert patterns.pattern.tolist() == [
        "industry_hospital_trend", "adverse_selection", "catastrophic_event", "inadequate_rate_changes", "fonasa_shift",
    ]
    assert patterns.detected.dtype == bool
    assert patterns.evidence.str.len().gt(0).all()


def test_credibility_gain_has_both_columns(cells_yearly, truth_dir):
    gain = credibility_gain(cells_yearly, PRICING, truth_dir)
    assert list(gain.columns) == ["metric", "model_only", "with_credibility"]
    assert gain.metric.tolist() == ["rmse_per_py", "ae", "corr_log_factor_log_effect"]
    assert np.isfinite(gain.set_index("metric").loc[["rmse_per_py", "ae"]].to_numpy()).all()


def test_oot_against_truth_has_ae_shift_per_model_and_type(models, two_stage_model, tweedie_model, cells_yearly, db_path, truth_dir):
    predictors = {"baseline": BaselineModel(models), "two_stage": two_stage_model, "tweedie": tweedie_model}
    report = oot_against_truth(predictors, cells_yearly[cells_yearly.year == 2025], db_path, truth_dir)
    by_type = report["by_type"]
    assert {"ae", "ae_shift"} <= set(by_type.columns)
    assert len(by_type) == 3 * len(CLAIM_TYPES)
    assert np.isfinite(by_type.ae_shift).all()
    assert (by_type.actual_uf > 0).all()


def test_pricing_modules_do_not_read_truth():
    files = [*(SRC / "models").rglob("*.py"), *(SRC / "pricing").rglob("*.py"), *(SRC / "report").rglob("*.py"),
             SRC / "pipeline.py"]
    offending = [
        f"{path.name}:{number}"
        for path in files
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        # El pipeline solo le pasa al generador la carpeta donde escribe la verdad; no la lee.
        if re.search(r"truth", line) and "run_generator(" not in line
    ]
    assert offending == []


def test_rate_change_effect_correlation(db_path, two_stage_model, cells_yearly, truth_dir):
    from colectivos.validation.truth_checks import rate_change_effect_correlation

    credibility = buhlmann_straub(contract_experience(cells_yearly, two_stage_model, two_stage_model.train_years))
    renewal = renewal_table(db_path, two_stage_model, credibility, 0.0, MORTALITY, PRICING)
    result = rate_change_effect_correlation(renewal, truth_dir)
    assert list(result.columns) == ["metric", "value"]
    values = result.set_index("metric").value
    assert -1 <= values.loc["corr_log_rate_change_log_effect"] <= 1
    assert values.loc["n_contracts"] == len(renewal)

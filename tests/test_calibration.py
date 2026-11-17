import pytest
import yaml

from colectivos.calibration import calibration_report, is_within
from tests.conftest import CONFIG_DIR

TARGETS = CONFIG_DIR / "calibration_targets.yaml"
METRICS = {"loss_ratio_health_annual", "claims_cost_per_insured_uf", "health_severity_trend", "fonasa_share_start"}


def test_report_has_all_targets(db_path):
    report = calibration_report(db_path, TARGETS)
    assert set(report.metric) == METRICS
    assert list(report.columns) == ["metric", "generated", "target_low", "target_high", "source", "assumption",
                                    "within_range"]
    assert report.generated.notna().all()


def test_every_target_has_source_or_assumption():
    targets = yaml.safe_load(TARGETS.read_text())
    for name, spec in targets.items():
        assert spec["source"].strip(), name
        assert isinstance(spec["assumption"], bool), name
        assert spec["target_low"] < spec["target_high"], name


def test_within_range_logic():
    assert is_within(0.85, 0.80, 0.95)
    assert not is_within(0.97, 0.80, 0.95)
    assert is_within(0.80, 0.80, 0.95)


def test_generated_values_are_plausible(db_path):
    report = calibration_report(db_path, TARGETS).set_index("metric")
    assert 0 < report.loc["loss_ratio_health_annual", "generated"] < 3
    assert 0 <= report.loc["fonasa_share_start", "generated"] <= 1

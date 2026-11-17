from datetime import date
from pathlib import Path

import pytest
import yaml

from colectivos.config import load_generator_config, load_pricing_config
from tests.conftest import CONFIG_DIR

CLAIM_TYPES = {"ambulatoria", "hospitalaria", "dental", "farmacia", "alto_costo"}


def test_load_generator_config_small():
    cfg = load_generator_config(CONFIG_DIR / "generator_small.yaml")
    assert cfg.n_companies == 20
    assert cfg.valuation_date == date(2025, 12, 31)
    assert set(cfg.claim_types) == CLAIM_TYPES
    assert set(cfg.system_coverage) == {"isapre", "fonasa"}


def test_full_config_has_300_companies():
    cfg = load_generator_config(CONFIG_DIR / "generator.yaml")
    assert cfg.n_companies == 300


def test_config_rejects_unknown_claim_type(tmp_path: Path):
    raw = yaml.safe_load((CONFIG_DIR / "generator_small.yaml").read_text())
    raw["claim_types"] = [*raw["claim_types"], "optica"]
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="optica"):
        load_generator_config(bad)


def test_config_rejects_weights_not_summing_to_one(tmp_path: Path):
    raw = yaml.safe_load((CONFIG_DIR / "generator_small.yaml").read_text())
    first = next(iter(raw["industries"]))
    raw["industries"][first] += 0.5
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="industries"):
        load_generator_config(bad)


def test_load_pricing_config():
    pc = load_pricing_config(CONFIG_DIR / "pricing.yaml")
    assert 0 < pc.expense_ratio + pc.commission_ratio + pc.target_margin < 1
    assert pc.pricing_year == 2026
    assert pc.low_exposure_threshold_years == 1.0

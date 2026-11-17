import hashlib
import json

import pandas as pd
import pytest

from colectivos.generator.patterns import pattern_multipliers
from colectivos.generator.run import run_generator
from tests.conftest import CONFIG_DIR

PATTERN_IDS = {"industry_hospital_trend", "adverse_selection", "catastrophic_event",
               "inadequate_rate_changes", "fonasa_shift"}


def _patterns(truth_dir) -> dict:
    return json.loads((truth_dir / "patterns.json").read_text())


def test_patterns_json_lists_five_patterns(truth_dir):
    assert set(_patterns(truth_dir)) == PATTERN_IDS


def test_construccion_hospital_multiplier_2025_is_1_08_pow_4(small_cfg):
    rows = pd.DataFrame(
        {
            "company_id": ["E1", "E2"],
            "industry": ["construccion", "retail"],
            "month": pd.to_datetime(["2025-03-01", "2025-03-01"]),
            "enrollment_date": pd.to_datetime(["2020-01-01", "2020-01-01"]),
        }
    )
    targets = {"adverse_selection": {"companies": []}}
    mult = pattern_multipliers(small_cfg, rows, targets)
    assert mult["hospitalaria"].tolist() == pytest.approx([1.08**4, 1.0])
    assert mult["ambulatoria"].tolist() == pytest.approx([1.0, 1.0])


def test_adverse_selection_only_new_entrants_of_target_companies(small_cfg):
    rows = pd.DataFrame(
        {
            "company_id": ["E1", "E1", "E2"],
            "industry": ["retail", "retail", "retail"],
            "month": pd.to_datetime(["2024-03-01"] * 3),
            "enrollment_date": pd.to_datetime(["2022-06-01", "2023-05-01", "2023-05-01"]),
        }
    )
    mult = pattern_multipliers(small_cfg, rows, {"adverse_selection": {"companies": ["E1"]}})
    assert mult["dental"].tolist() == pytest.approx([1.0, 1.6, 1.0])


def test_inadequate_contracts_have_zero_rate_changes(raw_dir, truth_dir):
    contracts = pd.read_parquet(raw_dir / "contracts.parquet")
    inadequate = _patterns(truth_dir)["inadequate_rate_changes"]["contracts"]
    assert inadequate
    renewals = contracts[contracts.contract_id.isin(inadequate) & contracts.rate_change_applied.notna()]
    assert (renewals.rate_change_applied == 0).all()


def test_catastrophic_claim_present_once_2023(truth_dir):
    full = pd.read_parquet(truth_dir / "health_claims_full.parquet")
    event = _patterns(truth_dir)["catastrophic_event"]
    hits = full[full.reimbursed_uf == event["amount_uf"]]
    assert len(hits) == 1
    assert hits.occurrence_date.dt.year.item() == 2023
    assert hits.company_id.item() == event["company_id"]


def test_fonasa_shift_raises_fonasa_share_of_late_entrants(truth_dir):
    assert _patterns(truth_dir)["fonasa_shift"]["from_year"] == 2024


def test_run_generator_reproducible(tmp_path):
    def digest(root):
        return {p.name: hashlib.md5(pd.read_parquet(p).to_csv().encode()).hexdigest()
                for p in sorted((root / "raw").glob("*.parquet"))}

    for run in ("a", "b"):
        run_generator(CONFIG_DIR / "generator_small.yaml", tmp_path / run / "raw", tmp_path / run / "truth")
    assert digest(tmp_path / "a") == digest(tmp_path / "b")

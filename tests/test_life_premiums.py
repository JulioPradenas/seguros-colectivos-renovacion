import pandas as pd
import pytest

from colectivos.generator.life_claims import load_mortality
from tests.conftest import CONFIG_DIR


def _raw(raw_dir, name: str) -> pd.DataFrame:
    return pd.read_parquet(raw_dir / f"{name}.parquet")


def test_load_mortality_has_both_sexes_and_increasing_adult_qx():
    mortality = load_mortality(CONFIG_DIR / "mortality" / "makeham_supuesto.csv")
    assert set(mortality.sex) == {"M", "F"}
    adult_m = mortality[(mortality.sex == "M") & mortality.age.between(20, 100)].sort_values("age")
    assert adult_m.qx.is_monotonic_increasing
    assert mortality.qx.between(0, 1).all()


def test_raw_dir_has_all_tables(raw_dir):
    expected = {"companies", "plans", "contracts", "insureds", "exposure_monthly", "health_claims",
                "life_claims", "premiums_monthly"}
    assert {p.stem for p in raw_dir.glob("*.parquet")} == expected


def test_valuation_cut_excludes_late_payments(raw_dir, truth_dir):
    raw = _raw(raw_dir, "health_claims")
    full = pd.read_parquet(truth_dir / "health_claims_full.parquet")
    assert raw.payment_date.max() <= pd.Timestamp("2025-12-31")
    assert len(full) > len(raw)


def test_life_claims_only_holders_and_one_per_insured(raw_dir):
    life = _raw(raw_dir, "life_claims")
    insureds = _raw(raw_dir, "insureds").set_index("insured_id")
    assert life.insured_id.is_unique
    assert (insureds.loc[life.insured_id, "role"] == "titular").all()
    assert (life.capital_paid_uf > 0).all()


def test_earned_premium_equals_exposure_times_rate(raw_dir):
    premiums = _raw(raw_dir, "premiums_monthly")
    exposure = _raw(raw_dir, "exposure_monthly").merge(
        _raw(raw_dir, "insureds")[["insured_id", "role"]], on="insured_id"
    )
    contracts = _raw(raw_dir, "contracts")
    month = pd.Timestamp("2023-06-01")
    row = premiums[premiums.month == month].iloc[0]
    term = contracts[(contracts.contract_id == row.contract_id) & (contracts.term_start <= month)
                     & (contracts.term_end >= month)].iloc[0]
    company_exposure = exposure[(exposure.company_id == term.company_id) & (exposure.month == month)]
    by_role = company_exposure.groupby("role").exposure.sum()
    expected = by_role.get("titular", 0) * term.premium_holder_uf + by_role.get("carga", 0) * term.premium_dependent_uf
    assert row.earned_premium_uf == pytest.approx(expected)


def test_2026_term_exists_with_null_rate_change(raw_dir):
    contracts = _raw(raw_dir, "contracts")
    terms_2026 = contracts[contracts.term_start.dt.year == 2026]
    assert not terms_2026.empty
    assert terms_2026.rate_change_applied.isna().all()
    previous = contracts.sort_values("term_start").groupby("contract_id").nth(-2).set_index("contract_id")
    current = terms_2026.set_index("contract_id")
    shared = current.index.intersection(previous.index)
    assert (current.loc[shared, "premium_holder_uf"] == previous.loc[shared, "premium_holder_uf"]).all()


def test_renewals_apply_rate_change(raw_dir):
    contracts = _raw(raw_dir, "contracts").sort_values(["contract_id", "term_start"])
    renewals = contracts[contracts.rate_change_applied.notna()]
    prev_premium = contracts.groupby("contract_id").premium_holder_uf.shift().loc[renewals.index]
    assert renewals.premium_holder_uf.to_numpy() == pytest.approx(
        (prev_premium * (1 + renewals.rate_change_applied)).to_numpy()
    )


def test_death_ends_coverage_of_holder_and_dependents(raw_dir):
    life = _raw(raw_dir, "life_claims")
    insureds = _raw(raw_dir, "insureds")
    assert not life.empty
    deaths = life.set_index("insured_id").death_date
    holders = insureds.set_index("insured_id").loc[deaths.index]
    assert (holders.termination_date == deaths).all()
    dependents = insureds[insureds.holder_id.isin(deaths.index)]
    assert (dependents.termination_date <= dependents.holder_id.map(deaths)).all()


def test_no_health_claims_after_death(raw_dir):
    life = _raw(raw_dir, "life_claims")[["insured_id", "death_date"]]
    claims = _raw(raw_dir, "health_claims").merge(life, on="insured_id")
    assert (claims.occurrence_date <= claims.death_date).all()
    exposure = _raw(raw_dir, "exposure_monthly").merge(life, on="insured_id")
    assert (exposure.month <= exposure.death_date).all()

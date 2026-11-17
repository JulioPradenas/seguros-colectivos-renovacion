import numpy as np
import pandas as pd

from colectivos.config import CLAIM_TYPES
from colectivos.generator.portfolio import (
    generate_companies,
    generate_contracts,
    generate_insureds,
    generate_plans,
)


def test_companies_count_and_domains(small_cfg):
    companies = generate_companies(small_cfg, np.random.default_rng(1))
    assert len(companies) == 20
    assert companies.company_id.is_unique
    assert set(companies.industry) <= set(small_cfg.industries)
    assert set(companies.region) <= set(small_cfg.regions)
    size = small_cfg.company_size_lognormal
    assert companies.n_holders_target.between(size["min"], size["max"]).all()


def test_plans_have_one_row_per_plan_and_type(small_cfg):
    plans = generate_plans(small_cfg)
    assert len(plans) == len(small_cfg.plans) * len(CLAIM_TYPES)
    assert plans.reimbursement_pct.between(0, 1).all()


def test_dependents_belong_to_holder_of_same_company(insureds):
    deps = insureds[insureds.role == "carga"]
    holders = insureds.set_index("insured_id")
    assert (holders.loc[deps.holder_id, "company_id"].to_numpy() == deps.company_id.to_numpy()).all()
    assert (holders.loc[deps.holder_id, "role"] == "titular").all()


def test_dependents_share_holder_health_system(insureds):
    deps = insureds[insureds.role == "carga"]
    holders = insureds.set_index("insured_id")
    assert (holders.loc[deps.holder_id, "health_system"].to_numpy() == deps.health_system.to_numpy()).all()


def test_dependent_terminates_no_later_than_holder(insureds):
    deps = insureds[insureds.role == "carga"]
    holder_term = insureds.set_index("insured_id").loc[deps.holder_id, "termination_date"].to_numpy()
    far = pd.Timestamp("2100-01-01")
    dep_term = deps.termination_date.fillna(far).to_numpy()
    assert (dep_term <= pd.Series(holder_term).fillna(far).to_numpy()).all()


def test_birth_dates_give_ages_0_to_80_at_enrollment(insureds):
    age = (insureds.enrollment_date - insureds.birth_date).dt.days / 365.25
    assert age.between(0, 81).all()


def test_holders_never_enrolled_after_company_lapse(insureds, companies):
    merged = insureds.merge(companies[["company_id", "lapse_date"]], on="company_id")
    lapsed = merged.dropna(subset=["lapse_date"])
    assert (lapsed.enrollment_date < lapsed.lapse_date).all()
    assert (lapsed.termination_date < lapsed.lapse_date).all()


def test_contract_terms_are_annual_and_contiguous(contracts):
    for _, terms in contracts.sort_values("term_start").groupby("contract_id"):
        assert ((terms.term_end - terms.term_start).dt.days.between(364, 365)).all()
        gaps = (terms.term_start.iloc[1:].to_numpy() - terms.term_end.iloc[:-1].to_numpy())
        assert (gaps == np.timedelta64(1, "D")).all()


def test_contract_term_starts_on_client_anniversary(contracts, companies):
    merged = contracts.merge(companies[["company_id", "client_since"]], on="company_id")
    assert (merged.term_start.dt.month == merged.client_since.dt.month).all()
    assert (merged.term_start.dt.day == 1).all()


def test_non_lapsed_companies_have_2026_term(contracts, companies):
    active = companies[companies.lapse_date.isna()].company_id
    with_2026 = contracts[contracts.term_start.dt.year == 2026].company_id
    assert set(active) == set(with_2026)


def test_same_seed_same_output(small_cfg):
    def build():
        rng = np.random.default_rng(3)
        companies = generate_companies(small_cfg, rng)
        contracts = generate_contracts(small_cfg, companies, rng)
        return generate_insureds(small_cfg, companies, rng)

    pd.testing.assert_frame_equal(build(), build())

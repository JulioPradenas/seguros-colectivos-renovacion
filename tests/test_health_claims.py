from datetime import date

import numpy as np
import pandas as pd
import pytest

from colectivos.generator.health_claims import (
    apply_reimbursement,
    compute_system_coverage,
    draw_claim_lines,
    draw_company_effects,
    draw_severity,
    enrich_exposure,
    expected_frequency,
    generate_health_claims,
)

ONE_PLAN = pd.DataFrame(
    {
        "plan_id": ["p1"],
        "claim_type": ["ambulatoria"],
        "reimbursement_pct": [0.8],
        "deductible_uf": [1.0],
        "annual_cap_uf": [10.0],
    }
)
ONE_CONTRACT = pd.DataFrame(
    {
        "contract_id": ["CTR1", "CTR1"],
        "plan_id": ["p1", "p1"],
        "term_start": pd.to_datetime(["2022-03-01", "2023-03-01"]),
        "term_end": pd.to_datetime(["2023-02-28", "2024-02-29"]),
    }
)


def _claims(billed: list[float], dates: list[str]) -> pd.DataFrame:
    billed_arr = np.array(billed)
    return pd.DataFrame(
        {
            "claim_id": [f"S{i}" for i in range(len(billed))],
            "insured_id": "A1",
            "contract_id": "CTR1",
            "claim_type": "ambulatoria",
            "occurrence_date": pd.to_datetime(dates),
            "billed_uf": billed_arr,
            "system_covered_uf": billed_arr * 0.5,
        }
    )


def test_reimbursement_respects_deductible_pct_and_cap():
    claims = _claims([4.0, 6.0, 30.0], ["2022-04-01", "2022-05-01", "2022-06-01"])
    out = apply_reimbursement(claims, ONE_PLAN, ONE_CONTRACT)
    assert out.reimbursed_uf.round(6).tolist() == [0.8, 2.4, 6.8]


def test_deductible_and_cap_reset_each_term():
    claims = _claims([4.0, 4.0], ["2023-02-15", "2023-03-15"])
    out = apply_reimbursement(claims, ONE_PLAN, ONE_CONTRACT)
    assert out.reimbursed_uf.round(6).tolist() == [0.8, 0.8]


def test_fonasa_higher_copay_than_isapre_same_billed(small_cfg):
    billed = pd.Series([10.0, 10.0])
    covered = compute_system_coverage(
        small_cfg, billed, pd.Series(["isapre", "fonasa"]), pd.Series(["ambulatoria", "ambulatoria"])
    )
    copay = billed - covered
    assert copay.iloc[1] > copay.iloc[0]


def test_expected_frequency_relativities_and_seasonality(small_cfg):
    base = {
        "age_band": "30-44", "sex": "M", "health_system": "isapre", "role": "titular",
        "industry": "manufactura", "region": "metropolitana", "company_id": "EMP0001",
        "exposure": 1.0,
    }
    rows = pd.DataFrame(
        [
            {**base, "month": pd.Timestamp("2021-03-01")},
            {**base, "month": pd.Timestamp("2021-03-01"), "sex": "F"},
            {**base, "month": pd.Timestamp("2021-06-01")},
            {**base, "month": pd.Timestamp("2022-03-01")},
        ]
    )
    effect = pd.Series({"EMP0001": 1.0})
    lam = expected_frequency(small_cfg, rows, "ambulatoria", effect)
    assert lam.iloc[0] == pytest.approx(6.0 / 12)
    assert lam.iloc[1] / lam.iloc[0] == pytest.approx(1.25)
    assert lam.iloc[2] / lam.iloc[0] == pytest.approx(1.25)
    assert lam.iloc[3] / lam.iloc[0] == pytest.approx(1.01)
    hosp = expected_frequency(small_cfg, rows, "hospitalaria", effect)
    assert hosp.iloc[2] == pytest.approx(hosp.iloc[0])


def test_pattern_multiplier_scales_lambda(small_cfg):
    rows = pd.DataFrame(
        [{"age_band": "30-44", "sex": "M", "health_system": "isapre", "role": "titular",
          "industry": "manufactura", "region": "metropolitana", "company_id": "EMP0001",
          "exposure": 1.0, "month": pd.Timestamp("2021-03-01")}]
    )
    effect = pd.Series({"EMP0001": 1.0})
    plain = expected_frequency(small_cfg, rows, "dental", effect)
    boosted = expected_frequency(small_cfg, rows, "dental", effect, pd.Series([1.6]))
    assert boosted.iloc[0] == pytest.approx(plain.iloc[0] * 1.6)


def test_reimbursed_never_exceeds_copay(claims):
    assert (claims.reimbursed_uf <= claims.billed_uf - claims.system_covered_uf + 1e-9).all()
    assert (claims.reimbursed_uf > 0).all()


def test_payment_after_occurrence(claims):
    assert (claims.payment_date >= claims.occurrence_date).all()


def test_claims_only_while_exposed(claims, insureds):
    merged = claims.merge(insureds[["insured_id", "enrollment_date", "termination_date"]], on="insured_id")
    assert (merged.occurrence_date >= merged.enrollment_date).all()
    assert (merged.termination_date.isna() | (merged.occurrence_date <= merged.termination_date)).all()


def test_claims_have_expected_columns(claims):
    assert list(claims.columns) == [
        "claim_id", "insured_id", "company_id", "contract_id", "claim_type", "occurrence_date",
        "payment_date", "billed_uf", "system_covered_uf", "reimbursed_uf",
    ]
    assert claims.claim_id.is_unique


@pytest.mark.slow
def test_empirical_frequency_matches_lambda(small_cfg, portfolio):
    enriched = enrich_exposure(portfolio["exposure"], portfolio["insureds"], portfolio["companies"],
                               portfolio["contracts"])
    rng = np.random.default_rng(11)
    effects = draw_company_effects(small_cfg, portfolio["companies"], rng)
    lines = draw_claim_lines(small_cfg, enriched, effects, rng)
    for claim_type in ["ambulatoria", "farmacia"]:
        expected = expected_frequency(small_cfg, enriched, claim_type, effects).sum()
        observed = (lines.claim_type == claim_type).sum()
        assert observed == pytest.approx(expected, rel=0.03)


@pytest.mark.slow
def test_severity_mean_matches_config(small_cfg):
    rng = np.random.default_rng(5)
    years = np.full(200_000, 2021)
    assert draw_severity(small_cfg, "ambulatoria", years, rng).mean() == pytest.approx(1.2, rel=0.02)
    assert draw_severity(small_cfg, "hospitalaria", years, rng).mean() == pytest.approx(60.0, rel=0.03)
    later = draw_severity(small_cfg, "ambulatoria", np.full(200_000, 2023), rng).mean()
    assert later == pytest.approx(1.2 * (1 + small_cfg.annual_trend["ambulatoria"]) ** 2, rel=0.02)
    assert draw_severity(small_cfg, "alto_costo", years, rng).min() >= 300.0


def test_deductible_consumed_in_warmup_before_simulation_start(small_cfg):
    """Una vigencia que empezó antes de cfg.start no reinicia el deducible el 1 de enero del primer año."""
    from dataclasses import replace

    from colectivos.config import CLAIM_TYPES
    from colectivos.generator.exposure import build_exposure

    cfg = replace(
        small_cfg,
        base_frequency={t: (200.0 if t == "ambulatoria" else 20.0) for t in CLAIM_TYPES},
        frequency_trend={t: 0.0 for t in CLAIM_TYPES},
    )
    insureds = pd.DataFrame(
        {
            "insured_id": ["A1"], "company_id": ["EMP1"], "holder_id": ["A1"], "role": ["titular"],
            "sex": ["F"], "birth_date": pd.to_datetime(["1985-05-10"]), "health_system": ["isapre"],
            "enrollment_date": pd.to_datetime(["2019-01-01"]), "termination_date": pd.to_datetime([pd.NaT]),
        }
    )
    companies = pd.DataFrame({"company_id": ["EMP1"], "industry": ["manufactura"], "region": ["metropolitana"]})
    contracts = pd.DataFrame(
        {
            "contract_id": ["CTR1", "CTR1"], "company_id": ["EMP1", "EMP1"], "plan_id": ["p1", "p1"],
            "term_start": pd.to_datetime(["2020-07-01", "2021-07-01"]),
            "term_end": pd.to_datetime(["2021-06-30", "2022-06-30"]),
        }
    )
    plans = pd.DataFrame(
        {
            "plan_id": "p1", "claim_type": list(CLAIM_TYPES), "reimbursement_pct": 0.8,
            "deductible_uf": 1.0, "annual_cap_uf": 1e9,
        }
    )
    exposure = build_exposure(insureds, cfg.start, date(2021, 6, 30))
    claims = generate_health_claims(
        cfg, exposure, insureds, companies, contracts, plans, pd.Series({"EMP1": 1.0}), np.random.default_rng(7)
    )

    assert claims.occurrence_date.min() >= pd.Timestamp(cfg.start)
    first_semester = claims[(claims.occurrence_date < pd.Timestamp("2021-07-01")) & (claims.claim_type == "ambulatoria")]
    assert len(first_semester) > 50
    copay = first_semester.billed_uf - first_semester.system_covered_uf
    assert first_semester.reimbursed_uf.sum() == pytest.approx((0.8 * copay).sum())

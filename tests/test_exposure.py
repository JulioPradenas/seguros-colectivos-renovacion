from datetime import date

import pandas as pd

from colectivos.generator.exposure import assign_age_band, build_exposure


def _single_insured(enrollment: str, termination: str | None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "insured_id": ["A1"],
            "company_id": ["EMP001"],
            "holder_id": pd.Series([pd.NA], dtype="string"),
            "role": ["titular"],
            "sex": ["F"],
            "birth_date": [pd.Timestamp("1985-06-15")],
            "health_system": ["isapre"],
            "enrollment_date": [pd.Timestamp(enrollment)],
            "termination_date": [pd.Timestamp(termination) if termination else pd.NaT],
        }
    )


def test_exposure_years_full_month():
    exposure = build_exposure(_single_insured("2021-01-01", None), date(2021, 1, 1), date(2025, 12, 31))
    assert len(exposure) == 60
    assert (exposure.exposure == 1.0).all()


def test_partial_months_prorated_by_days():
    exposure = build_exposure(_single_insured("2021-01-16", "2021-03-10"), date(2021, 1, 1), date(2025, 12, 31))
    assert exposure.exposure.round(6).tolist() == [round(16 / 31, 6), 1.0, round(10 / 31, 6)]


def test_age_at_month_start():
    exposure = build_exposure(_single_insured("2021-01-01", "2021-07-31"), date(2021, 1, 1), date(2025, 12, 31))
    assert exposure.set_index("month").loc[pd.Timestamp("2021-06-01"), "age"] == 35
    assert exposure.set_index("month").loc[pd.Timestamp("2021-07-01"), "age"] == 36


def test_assign_age_band_edges():
    bands = assign_age_band(pd.Series([0, 17, 18, 29, 30, 44, 45, 59, 60, 69, 70, 95]))
    assert bands.tolist() == ["0-17", "0-17", "18-29", "18-29", "30-44", "30-44",
                              "45-59", "45-59", "60-69", "60-69", "70+", "70+"]


def test_exposure_between_0_and_1_and_zero_outside_enrollment(exposure, insureds):
    assert exposure.exposure.gt(0).all() and exposure.exposure.le(1).all()
    merged = exposure.merge(insureds[["insured_id", "enrollment_date", "termination_date"]], on="insured_id")
    month_end = merged.month + pd.offsets.MonthEnd(0)
    assert (month_end >= merged.enrollment_date).all()
    assert (merged.termination_date.isna() | (merged.month <= merged.termination_date)).all()


def test_dependent_exposure_zero_after_holder_termination(exposure, insureds):
    deps = insureds[insureds.role == "carga"][["insured_id", "holder_id"]]
    holder_term = insureds[insureds.role == "titular"][["insured_id", "termination_date"]].rename(
        columns={"insured_id": "holder_id", "termination_date": "holder_termination"}
    )
    merged = exposure.merge(deps, on="insured_id").merge(holder_term, on="holder_id")
    after = merged[merged.holder_termination.notna() & (merged.month > merged.holder_termination)]
    assert after.empty


def test_exposure_inside_observation_window(exposure):
    assert exposure.month.min() >= pd.Timestamp("2021-01-01")
    assert exposure.month.max() <= pd.Timestamp("2025-12-01")

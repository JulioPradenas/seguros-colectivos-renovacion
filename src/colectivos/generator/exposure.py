"""Exposición mensual por asegurado (fracción de días cubiertos en el mes)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from colectivos.config import AGE_BAND_EDGES, AGE_BANDS


def assign_age_band(age: pd.Series) -> pd.Series:
    bands = pd.cut(age, bins=list(AGE_BAND_EDGES), right=False, labels=list(AGE_BANDS))
    return bands.astype("string")


def _age_at(birth: pd.Series, when: pd.Series) -> np.ndarray:
    had_birthday = (when.dt.month > birth.dt.month) | (
        (when.dt.month == birth.dt.month) & (when.dt.day >= birth.dt.day)
    )
    return (when.dt.year - birth.dt.year - (~had_birthday).astype(int)).to_numpy()


def build_exposure(insureds: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    window_start = pd.Timestamp(start)
    window_end = pd.Timestamp(end)
    first_day = insureds.enrollment_date.clip(lower=window_start)
    last_day = insureds.termination_date.fillna(window_end).clip(upper=window_end)
    covered = insureds[first_day <= last_day].copy()
    first_day = first_day[covered.index]
    last_day = last_day[covered.index]

    first_month = first_day.dt.to_period("M")
    last_month = last_day.dt.to_period("M")
    n_months = (last_month - first_month).apply(lambda offset: offset.n).to_numpy() + 1

    rows = np.repeat(np.arange(len(covered)), n_months)
    month_offset = np.arange(len(rows)) - np.repeat(np.cumsum(n_months) - n_months, n_months)
    month_start = (first_month.iloc[rows].reset_index(drop=True) + month_offset).dt.to_timestamp()
    month_end = month_start + pd.offsets.MonthEnd(0)

    row_first = first_day.iloc[rows].reset_index(drop=True)
    row_last = last_day.iloc[rows].reset_index(drop=True)
    days_covered = (np.minimum(month_end, row_last) - np.maximum(month_start, row_first)).dt.days + 1
    days_in_month = month_start.dt.days_in_month

    picked = covered.iloc[rows].reset_index(drop=True)
    return pd.DataFrame(
        {
            "insured_id": picked.insured_id,
            "company_id": picked.company_id,
            "month": month_start,
            "exposure": days_covered / days_in_month,
            "age": _age_at(picked.birth_date, month_start),
        }
    )

import duckdb
import numpy as np
import pandas as pd
import pytest
import yaml

from colectivos.config import load_pricing_config
from colectivos.models.ibnr import estimate_ibnr
from colectivos.models.trend import TrendModel, fit_trend, fit_trends, trend_log_offset
from colectivos.models.ultimates import cells_to_ultimate, to_yearly

PRICING_CONFIG = "config/pricing.yaml"
INDUSTRIES = ("construccion", "retail", "mineria", "servicios")
AGE_RELATIVITY = {"18-29": 0.8, "30-44": 1.0, "45-59": 1.4}
SEX_RELATIVITY = {"F": 1.2, "M": 1.0}
SYSTEM_RELATIVITY = {"isapre": 1.0, "fonasa": 0.7}


def _synthetic_cells(
    company_effects: dict[str, float],
    years: dict[str, tuple[int, ...]] | None = None,
    within_trend: float = 0.0,
    industry_trend: dict[str, float] | None = None,
    exposure_per_cell: float = 20.0,
    base_frequency: float = 2.0,
    seed: int = 0,
) -> pd.DataFrame:
    """Base anual sintética con efecto multiplicativo por empresa, sin efecto de rubro en el nivel."""
    rng = np.random.default_rng(seed)
    industry_trend = industry_trend or {}
    rows = []
    for index, (company_id, effect) in enumerate(company_effects.items()):
        industry = INDUSTRIES[index % len(INDUSTRIES)]
        company_years = (years or {}).get(company_id, (2021, 2022, 2023, 2024))
        for year in company_years:
            year_c = year - 2023
            trend = (1 + within_trend) ** year_c * (1 + industry_trend.get(industry, 0.0)) ** year_c
            for age_band, age_rel in AGE_RELATIVITY.items():
                for sex, sex_rel in SEX_RELATIVITY.items():
                    for system, system_rel in SYSTEM_RELATIVITY.items():
                        mean = exposure_per_cell * base_frequency * effect * trend * age_rel * sex_rel * system_rel
                        n_claims = rng.poisson(mean)
                        amount = rng.gamma(2.0 * n_claims, 0.5) if n_claims > 0 else 0.0
                        rows.append(
                            {
                                "year": year, "claim_type": "ambulatoria", "company_id": company_id,
                                "contract_id": f"K{company_id}", "age_band": age_band, "sex": sex,
                                "health_system": system, "role": "titular", "industry": industry,
                                "region": "RM", "exposure_years": exposure_per_cell,
                                "n_claims_ult": float(n_claims), "reimbursed_capped_ult_uf": amount,
                            }
                        )
    return pd.DataFrame(rows)


def _mix_shift_portfolio(within_trend: float, seed: int = 0) -> pd.DataFrame:
    effects = {f"E{i:02d}": 1.0 for i in range(32)} | {f"N{i:02d}": 1.5 for i in range(8)}
    years = {f"N{i:02d}": (2024,) for i in range(8)}
    return _synthetic_cells(effects, years=years, within_trend=within_trend, seed=seed)


def test_trend_ignores_company_mix_shift():
    cells = _mix_shift_portfolio(within_trend=0.0)
    by_year = cells.groupby("year")[["n_claims_ult", "exposure_years"]].sum()
    aggregate = by_year.n_claims_ult / by_year.exposure_years
    assert aggregate.loc[2024] / aggregate.loc[2023] > 1.07
    trend = fit_trend(cells, "ambulatoria", (2021, 2024), test_interaction=False, alpha=0.05)
    assert isinstance(trend, TrendModel)
    assert abs(trend.freq_trend) < 0.01
    assert abs(trend.sev_trend) < 0.02


def test_trend_recovers_within_company_trend():
    cells = _mix_shift_portfolio(within_trend=0.03, seed=1)
    trend = fit_trend(cells, "ambulatoria", (2021, 2024), test_interaction=False, alpha=0.05)
    assert trend.freq_trend == pytest.approx(0.03, abs=0.005)


def test_company_without_claims_does_not_break_trend():
    base = _mix_shift_portfolio(within_trend=0.02, seed=2)
    silent = _synthetic_cells({"Z99": 1.0}, exposure_per_cell=0.05, seed=3).assign(
        n_claims_ult=0.0, reimbursed_capped_ult_uf=0.0
    )
    with_silent = fit_trend(pd.concat([base, silent]), "ambulatoria", (2021, 2024), False, 0.05)
    without = fit_trend(base, "ambulatoria", (2021, 2024), False, 0.05)
    assert np.isfinite(with_silent.freq_trend)
    assert abs(with_silent.freq_trend - without.freq_trend) <= 0.002


def test_industry_interaction_retained_when_planted():
    effects = {f"E{i:02d}": 1.0 for i in range(40)}
    cells = _synthetic_cells(effects, industry_trend={"construccion": 0.08}, seed=4)
    trend = fit_trend(cells, "ambulatoria", (2021, 2024), test_interaction=True, alpha=0.05)
    assert trend.lr_pvalue is not None and trend.lr_pvalue < 0.05
    assert "construccion" in trend.industry_freq_trend
    extra = trend.industry_freq_trend["construccion"]
    total = (1 + trend.freq_trend) * (1 + extra) - 1
    assert total == pytest.approx(0.08, abs=0.02)


def test_trend_log_offset_adds_industry_term():
    trends = {
        "hospitalaria": TrendModel("hospitalaria", 0.02, 0.03, {"construccion": 0.08}, 0.001),
    }
    profile = pd.DataFrame({"industry": ["construccion", "retail"]})
    freq = trend_log_offset(trends, profile, "hospitalaria", 2.0, "freq")
    sev = trend_log_offset(trends, profile, "hospitalaria", 2.0, "sev")
    assert freq == pytest.approx([2 * (np.log(1.02) + np.log(1.08)), 2 * np.log(1.02)])
    assert sev == pytest.approx([2 * np.log(1.03)] * 2)


def _yearly_base(db_path) -> pd.DataFrame:
    with duckdb.connect(str(db_path), read_only=True) as con:
        cells = con.execute("SELECT * FROM marts.mart_model_cells_company").df()
        development = con.execute("SELECT * FROM marts.mart_development_quarterly").df()
    exposure = cells.groupby(["claim_type", "origin_quarter"], as_index=False).exposure_years.sum()
    ibnr = estimate_ibnr(development, exposure, load_pricing_config(PRICING_CONFIG))
    return to_yearly(cells_to_ultimate(cells, ibnr))


@pytest.mark.slow
def test_recovers_generator_trends(medium_db_path):
    cfg = load_pricing_config(PRICING_CONFIG)
    generator = yaml.safe_load(open("config/generator_small.yaml"))
    trends = fit_trends(_yearly_base(medium_db_path), cfg.train_years_oot, cfg)
    for claim_type in ("ambulatoria", "farmacia"):
        fitted = (1 + trends[claim_type].freq_trend) * (1 + trends[claim_type].sev_trend) - 1
        expected = (1 + generator["frequency_trend"][claim_type]) * (1 + generator["annual_trend"][claim_type]) - 1
        assert fitted == pytest.approx(expected, abs=0.02), (claim_type, fitted, expected)

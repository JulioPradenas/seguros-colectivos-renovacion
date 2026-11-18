import itertools
import json

import duckdb
import numpy as np
import pandas as pd
import pytest

from colectivos.models.glm import (
    FactorLevels,
    fit_all,
    fit_frequency,
    fit_severity,
    predict_cost_per_year,
    relativities,
)

BASE_LEVELS = {
    "age_band": ["30-44", "45-59"],
    "sex": ["F", "M"],
    "health_system": ["isapre", "fonasa"],
    "role": ["titular"],
    "industry": ["retail", "mineria"],
    "region": ["metropolitana", "aysen"],
}


def _synthetic_cells(claim_type: str, rate_fn, sev_mean: float = 2.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for combo in itertools.product(*BASE_LEVELS.values(), [2021, 2022, 2023, 2024]):
        row = dict(zip([*BASE_LEVELS, "year"], combo))
        row["claim_type"] = claim_type
        row["exposure_years"] = 400.0
        n = rng.poisson(row["exposure_years"] * rate_fn(row))
        row["n_claims"] = int(n)
        row["reimbursed_uf"] = float(rng.gamma(2.0, sev_mean / 2.0, n).sum()) if n else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def test_frequency_glm_recovers_planted_relativity():
    cells = _synthetic_cells("ambulatoria", lambda r: 0.5 * (1.8 if r["sex"] == "F" else 1.0))
    rel = relativities(fit_frequency(cells, "ambulatoria"))
    assert rel.loc[rel.term == "C(sex)[T.M]", "relativity"].item() == pytest.approx(1 / 1.8, rel=0.05)
    assert {"term", "relativity", "ci_low", "ci_high"} <= set(rel.columns)


def test_severity_glm_recovers_mean():
    cells = _synthetic_cells("hospitalaria", lambda r: 0.3, sev_mean=50.0)
    result = fit_severity(cells, "hospitalaria")
    intercept = relativities(result).set_index("term").loc["Intercept", "relativity"]
    assert intercept == pytest.approx(50.0, rel=0.10)


def test_prediction_finite_for_level_with_zero_claims():
    cells = _synthetic_cells("dental", lambda r: 0.0 if r["region"] == "aysen" else 0.8)
    model = fit_all(cells, train_years=(2021, 2024))["dental"]
    profile = pd.DataFrame([{"age_band": "30-44", "sex": "F", "health_system": "isapre", "role": "titular",
                             "industry": "retail", "region": "aysen"}])
    cost = predict_cost_per_year({"dental": model}, profile, year_c=2.5)
    assert np.isfinite(cost.expected_cost_dental_uf).all()
    assert (cost.expected_cost_dental_uf > 0).all()
    base = predict_cost_per_year({"dental": model}, profile.assign(region="metropolitana"), year_c=2.5)
    # un nivel sin siniestros no puede quedar con precio ~0: se fusiona con el nivel de mayor exposición
    assert cost.expected_cost_dental_uf.item() >= 0.1 * base.expected_cost_dental_uf.item()


def test_predict_cost_is_frequency_times_severity():
    cells = _synthetic_cells("farmacia", lambda r: 2.0, sev_mean=1.0)
    models = fit_all(cells, train_years=(2021, 2024))
    profile = pd.DataFrame([{"age_band": "30-44", "sex": "M", "health_system": "isapre", "role": "titular",
                             "industry": "retail", "region": "metropolitana"}])
    cost = predict_cost_per_year(models, profile, year_c=0.0)
    assert cost.expected_cost_farmacia_uf.item() == pytest.approx(2.0 * 1.0, rel=0.10)
    assert cost.expected_health_cost_uf.item() == pytest.approx(cost.expected_cost_farmacia_uf.item())


def test_train_years_respected():
    cells = pd.concat([
        _synthetic_cells("ambulatoria", lambda r: 1.0),
        _synthetic_cells("ambulatoria", lambda r: 1.0).assign(year=2025, n_claims=0, reimbursed_uf=0.0),
    ])
    model = fit_all(cells, train_years=(2021, 2024))["ambulatoria"]
    assert model.train_years == (2021, 2024)
    assert model.freq.model.data.frame.year.max() == 2024


def test_fit_all_on_generated_portfolio_covers_all_types(models):
    assert set(models) == {"ambulatoria", "hospitalaria", "dental", "farmacia", "alto_costo"}
    assert all(isinstance(m.levels, FactorLevels) for m in models.values())


@pytest.mark.slow
def test_recovers_generator_relativities(medium_db_path):
    with duckdb.connect(str(medium_db_path), read_only=True) as con:
        cells = con.execute("SELECT * FROM marts.mart_model_cells").df()
    truth = json.loads((medium_db_path.parent / "truth" / "parameters.json").read_text())["relativities"]
    rel = relativities(fit_frequency(cells[cells.year <= 2024], "hospitalaria")).set_index("term").relativity
    # referencias por defecto de patsy: sex=F, age_band=0-17
    assert rel["C(sex)[T.M]"] == pytest.approx(truth["sex"]["M"] / truth["sex"]["F"], rel=0.10)
    age_ratio = rel["C(age_band)[T.60-69]"] / rel["C(age_band)[T.30-44]"]
    assert age_ratio == pytest.approx(truth["age_band"]["60-69"] / truth["age_band"]["30-44"], rel=0.15)


def test_alto_costo_severity_is_not_segmented(models):
    terms = set(models["alto_costo"].sev.params.index)
    assert terms == {"Intercept", "year_c"}
    assert "C(sex)[T.M]" in set(models["ambulatoria"].sev.params.index)


def test_actual_vs_expected_out_of_time():
    from colectivos.models.glm import actual_vs_expected

    train = _synthetic_cells("ambulatoria", lambda r: 1.0)
    test = _synthetic_cells("ambulatoria", lambda r: 1.0, seed=3).assign(year=2025)
    models = fit_all(train, train_years=(2021, 2024))
    report = actual_vs_expected(models, test, year=2025)
    row = report.set_index("claim_type").loc["ambulatoria"]
    assert row.actual_claims == test.n_claims.sum()
    assert row.ae_frequency == row.actual_claims / row.expected_claims
    assert 0.9 < row.ae_frequency < 1.1
    assert {"claim_type", "actual_claims", "expected_claims", "ae_frequency", "poisson_deviance"} <= set(report.columns)

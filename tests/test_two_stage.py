import dataclasses

import numpy as np
import pandas as pd
import pytest

from colectivos.config import CLAIM_TYPES, load_pricing_config
from colectivos.models.glm import FACTORS
from colectivos.models.two_stage import TwoStageModel, fit_two_stage

PRICING_CONFIG = "config/pricing.yaml"


def _profile(cells_yearly: pd.DataFrame, n: int = 25) -> pd.DataFrame:
    return cells_yearly[list(FACTORS)].drop_duplicates().head(n).reset_index(drop=True)


def test_two_stage_predicts_frequency_times_severity(two_stage_model, cells_yearly):
    profile = _profile(cells_yearly)
    prediction = two_stage_model.predict_cost(profile, 0.0)
    cost_columns = [f"expected_cost_{claim_type}_uf" for claim_type in CLAIM_TYPES]
    assert set(cost_columns) <= set(prediction.columns)
    assert prediction.expected_health_cost_uf.to_numpy() == pytest.approx(prediction[cost_columns].sum(axis=1))
    model = two_stage_model.relativities["dental"]
    rate = np.asarray(model.freq.predict(profile, offset=np.zeros(len(profile))))
    severity = np.asarray(model.sev.predict(profile, offset=np.zeros(len(profile))))
    seen = ~prediction.unseen_level_flag.to_numpy()
    assert prediction.expected_cost_dental_uf.to_numpy()[seen] == pytest.approx((rate * severity)[seen])


def test_offset_applies_trend_exactly(two_stage_model, cells_yearly):
    profile = _profile(cells_yearly)
    trend = two_stage_model.trends["ambulatoria"]
    now = two_stage_model.predict_cost(profile, 0.5).expected_cost_ambulatoria_uf
    later = two_stage_model.predict_cost(profile, 1.5).expected_cost_ambulatoria_uf
    expected = (1 + trend.freq_trend) * (1 + trend.sev_trend)
    assert (later / now).to_numpy() == pytest.approx(np.full(len(profile), expected))


def test_industry_interaction_applies_only_to_that_industry(two_stage_model, cells_yearly):
    trends = dict(two_stage_model.trends)
    hospital = trends["hospitalaria"]
    trends["hospitalaria"] = dataclasses.replace(hospital, industry_freq_trend={"construccion": 0.08})
    model = dataclasses.replace(two_stage_model, trends=trends)
    base = _profile(cells_yearly, 1)
    profile = pd.concat([base.assign(industry="construccion"), base.assign(industry="retail")], ignore_index=True)
    ratio = (
        model.predict_cost(profile, 1.0).expected_cost_hospitalaria_uf
        / model.predict_cost(profile, 0.0).expected_cost_hospitalaria_uf
    ).to_numpy()
    plain = (1 + hospital.freq_trend) * (1 + hospital.sev_trend)
    assert ratio == pytest.approx([plain * 1.08, plain])


def test_unseen_level_flagged(cells_yearly):
    cfg = load_pricing_config(PRICING_CONFIG)
    model = fit_two_stage(cells_yearly[cells_yearly.age_band != "70+"], cfg.train_years_oot, cfg)
    profile = _profile(cells_yearly, 2).assign(age_band=["70+", "30-44"])
    prediction = model.predict_cost(profile, 0.0)
    assert prediction.unseen_level_flag.tolist() == [True, False]
    assert np.isfinite(prediction.expected_health_cost_uf).all()
    assert (prediction.expected_health_cost_uf > 0).all()


def test_fit_two_stage_on_generated_portfolio_covers_all_types(two_stage_model, cells_yearly):
    assert isinstance(two_stage_model, TwoStageModel)
    assert set(two_stage_model.relativities) == set(CLAIM_TYPES)
    assert set(two_stage_model.trends) == set(CLAIM_TYPES)
    assert "year_c" not in two_stage_model.relativities["ambulatoria"].freq.params.index
    prediction = two_stage_model.predict_cost(_profile(cells_yearly, 200), 2.5)
    assert np.isfinite(prediction.expected_health_cost_uf).all()
    assert (prediction.expected_health_cost_uf > 0).all()


def test_type_without_claims_in_training_is_skipped_not_crashing(cells_yearly):
    from colectivos.models.tweedie import fit_tweedie

    cfg = load_pricing_config(PRICING_CONFIG)
    no_high_cost = cells_yearly.copy()
    is_high_cost = no_high_cost.claim_type == "alto_costo"
    for column in ["n_claims", "n_claims_ult", "reimbursed_uf", "reimbursed_ult_uf", "reimbursed_capped_ult_uf"]:
        no_high_cost.loc[is_high_cost, column] = 0.0
    model = fit_two_stage(no_high_cost, cfg.train_years_oot, cfg)
    challenger = fit_tweedie(no_high_cost, cfg.train_years_oot, model.trends, cfg.tweedie_powers)
    assert "alto_costo" not in model.relativities
    profile = _profile(cells_yearly)
    for prediction in (model.predict_cost(profile, 2.0), challenger.predict_cost(profile, 2.0)):
        assert (prediction.expected_cost_alto_costo_uf == 0).all()
        assert np.isfinite(prediction.expected_health_cost_uf).all()
        assert (prediction.expected_health_cost_uf > 0).all()

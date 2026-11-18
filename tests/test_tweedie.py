import numpy as np
import pytest

from colectivos.config import CLAIM_TYPES, load_pricing_config
from colectivos.models.glm import FACTORS
from colectivos.models.tweedie import TweedieModel, fit_tweedie
from colectivos.models.two_stage import _training_cells

PRICING_CONFIG = "config/pricing.yaml"


@pytest.fixture(scope="module")
def tweedie_model(cells_yearly, two_stage_model) -> TweedieModel:
    cfg = load_pricing_config(PRICING_CONFIG)
    return fit_tweedie(cells_yearly, cfg.train_years_oot, two_stage_model.trends, cfg.tweedie_powers)


def test_tweedie_power_selected_from_grid(tweedie_model):
    cfg = load_pricing_config(PRICING_CONFIG)
    assert set(tweedie_model.powers) == set(CLAIM_TYPES)
    assert all(power in cfg.tweedie_powers for power in tweedie_model.powers.values())


# Con link log y p > 1 el intercepto no balancea el total exacto. A escala full todos los tipos quedan a 0,1%;
# en la cartera de test (20 empresas, ~20 siniestros de alto costo en 4 años) alto costo queda a ~7%.
SPARSE_TOLERANCE = {"alto_costo": 0.10}


def test_tweedie_total_matches_training_cost(tweedie_model, cells_yearly):
    for claim_type in CLAIM_TYPES:
        train = _training_cells(cells_yearly, claim_type, tweedie_model.train_years)
        prediction = tweedie_model.predict_cost(train, train.year_c)
        predicted = (prediction[f"expected_cost_{claim_type}_uf"] * train.exposure_years).sum()
        observed = train.reimbursed_capped_ult_uf.sum()
        assert predicted == pytest.approx(observed, rel=SPARSE_TOLERANCE.get(claim_type, 0.02)), claim_type


def test_tweedie_predict_cost_has_same_columns_as_two_stage(tweedie_model, two_stage_model, cells_yearly):
    profile = cells_yearly[list(FACTORS)].drop_duplicates().head(50).reset_index(drop=True)
    challenger = tweedie_model.predict_cost(profile, 2.5)
    champion = two_stage_model.predict_cost(profile, 2.5)
    assert list(challenger.columns) == list(champion.columns)
    assert challenger.unseen_level_flag.dtype == bool
    assert np.isfinite(challenger.expected_health_cost_uf).all()
    assert (challenger.expected_health_cost_uf > 0).all()

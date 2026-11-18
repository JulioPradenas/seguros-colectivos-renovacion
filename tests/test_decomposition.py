import shutil

import numpy as np
import pytest

from colectivos.config import load_pricing_config
from colectivos.generator.life_claims import load_mortality
from colectivos.pricing.credibility import buhlmann_straub, contract_experience, large_loss_load
from colectivos.pricing.technical_premium import renewal_table, save_renewal_mart
from colectivos.report.decomposition import FACTOR_ORDER, rate_change_decomposition
from colectivos.report.draft import build_draft
from tests.conftest import CONFIG_DIR

PRICING = load_pricing_config(CONFIG_DIR / "pricing.yaml")
MORTALITY = load_mortality(CONFIG_DIR / "mortality" / "makeham_supuesto.csv")


@pytest.fixture(scope="module")
def priced(db_path, two_stage_model, cells_yearly, tmp_path_factory):
    db_copy = tmp_path_factory.mktemp("decomposition") / "warehouse.duckdb"
    shutil.copy(db_path, db_copy)
    years = two_stage_model.train_years
    credibility = buhlmann_straub(contract_experience(cells_yearly, two_stage_model, years))
    load = large_loss_load(cells_yearly, two_stage_model, years)
    renewal = renewal_table(db_copy, two_stage_model, credibility, load, MORTALITY, PRICING)
    save_renewal_mart(db_copy, renewal)
    decomposition = rate_change_decomposition(db_copy, two_stage_model, cells_yearly, renewal, PRICING)
    return db_copy, renewal, decomposition


def test_decomposition_product_equals_aggregate_rate_change(priced):
    _, renewal, decomposition = priced
    aggregate = renewal.technical_premium_annual_uf.sum() / renewal.current_premium_annual_uf.sum()
    assert np.prod(decomposition.multiplier.to_numpy()) == pytest.approx(aggregate, rel=1e-9)
    assert decomposition.log_share.sum() == pytest.approx(1.0, rel=1e-9)
    assert np.isfinite(decomposition.multiplier).all()
    assert (decomposition.multiplier > 0).all()


def test_decomposition_rows_in_spec_order(priced):
    _, _, decomposition = priced
    assert list(decomposition.columns) == ["factor", "multiplier", "log_share"]
    assert decomposition.factor.tolist() == list(FACTOR_ORDER)
    assert FACTOR_ORDER == (
        "Brecha de siniestralidad", "Ajuste del modelo", "Perfil", "Tendencia",
        "Credibilidad y siniestros grandes", "Vida", "Prima por persona",
    )


def test_draft_contains_decomposition_section(priced, tmp_path):
    db_copy, _, decomposition = priced
    text = build_draft(db_copy, tmp_path / "draft.md", decomposition=decomposition).read_text()
    assert "## Descomposición del reajuste agregado" in text
    assert "Credibilidad y siniestros grandes" in text
    without = build_draft(db_copy, tmp_path / "plain.md").read_text()
    assert "Descomposición del reajuste agregado" not in without


def test_trend_factor_is_one_when_model_has_no_trend(db_path, two_stage_model, cells_yearly, tmp_path):
    import dataclasses
    from datetime import date

    from colectivos.pricing.credibility import neutral_credibility

    flat = {
        claim_type: dataclasses.replace(trend, freq_trend=0.0, sev_trend=0.0, industry_freq_trend={})
        for claim_type, trend in two_stage_model.trends.items()
    }
    model = dataclasses.replace(two_stage_model, trends=flat)
    renewal = renewal_table(db_path, model, neutral_credibility(), 0.0, MORTALITY, PRICING)
    decomposition = rate_change_decomposition(
        db_path, model, cells_yearly, renewal, PRICING, valuation_date=date(2025, 12, 31)
    ).set_index("factor")
    assert decomposition.loc["Tendencia", "multiplier"] == pytest.approx(1.0, rel=1e-9)
    assert decomposition.loc["Credibilidad y siniestros grandes", "multiplier"] == pytest.approx(1.0, rel=1e-9)


def test_decomposition_rejects_valuation_date_inconsistent_with_renewal(priced, two_stage_model, cells_yearly):
    from datetime import date

    db_copy, renewal, _ = priced
    with pytest.raises(ValueError, match="vigentes"):
        rate_change_decomposition(db_copy, two_stage_model, cells_yearly, renewal, PRICING, valuation_date=date(2024, 6, 30))

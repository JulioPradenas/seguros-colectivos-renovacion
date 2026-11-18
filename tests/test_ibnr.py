import numpy as np
import pandas as pd
import pytest

from colectivos.config import load_pricing_config
from colectivos.models.ibnr import (
    cape_cod,
    cdf_to_ultimate,
    chain_ladder,
    development_factors,
    estimate_ibnr,
)

PRICING_CONFIG = "config/pricing.yaml"


def _triangle(rows: dict[str, list[float]]) -> pd.DataFrame:
    origins = pd.date_range("2024-01-01", periods=len(rows), freq="QS")
    records = [
        {"origin_quarter": origin, "dev_quarter": dev, "paid": value}
        for origin, values in zip(origins, rows.values())
        for dev, value in enumerate(values)
    ]
    return pd.DataFrame(records)


def _load_ibnr_inputs(db_path) -> tuple[pd.DataFrame, pd.DataFrame]:
    import duckdb

    with duckdb.connect(str(db_path), read_only=True) as con:
        development = con.execute("SELECT * FROM marts.mart_development_quarterly").df()
        exposure = con.execute(
            "SELECT claim_type, origin_quarter, SUM(exposure_years) AS exposure_years "
            "FROM marts.mart_model_cells_company GROUP BY ALL"
        ).df()
    return development, exposure


def test_development_factors_volume_weighted():
    triangle = _triangle({"A": [100, 150, 165], "B": [200, 290], "C": [150]})
    factors = development_factors(triangle, "paid")
    assert factors.loc[0] == pytest.approx(440 / 300)
    assert factors.loc[1] == pytest.approx(1.1)
    result = chain_ladder(triangle, "paid").set_index("origin_quarter")
    last_origin = result.iloc[-1]
    assert last_origin.latest == 150
    assert last_origin.ultimate == pytest.approx(150 * 440 / 300 * 1.1)
    assert result.iloc[0].ultimate == pytest.approx(165)
    assert (result.ibnr == result.ultimate - result.latest).all()


def test_cdf_to_ultimate_is_cumulative_product_with_unit_tail():
    cdf = cdf_to_ultimate(pd.Series([2.0, 1.5, 1.1], index=[0, 1, 2]))
    assert cdf.loc[0] == pytest.approx(3.3)
    assert cdf.loc[2] == pytest.approx(1.1)
    assert cdf.loc[3] == pytest.approx(1.0)


def test_zero_column_gives_unit_factor():
    triangle = _triangle({"A": [0, 0, 0], "B": [0, 0], "C": [0]})
    factors = development_factors(triangle, "paid")
    assert (factors == 1.0).all()
    result = chain_ladder(triangle, "paid")
    assert not result.isna().any().any()
    assert (result.ultimate == 0).all()


def test_cape_cod_uses_trended_prior():
    mature = {f"M{i}": [10.0] + [20.0] * (5 - i) for i in range(5)}
    triangle = _triangle({**mature, "R": [0.0]})
    exposure = pd.Series(10.0, index=sorted(triangle.origin_quarter.unique()))
    result = cape_cod(triangle, "paid", exposure, recent_quarters=1).set_index("origin_quarter")
    recent = result.iloc[-1]
    assert recent.cdf == pytest.approx(2.0)
    assert recent.ultimate == pytest.approx(2.0 * 10.0 * (1 - 1 / 2.0))
    assert recent.method == "cape_cod"
    assert (result.iloc[:-1].method == "chain_ladder").all()
    assert result.iloc[:-1].ultimate.to_numpy() == pytest.approx(np.full(5, 20.0))


def test_tail_factors_near_one_on_generated_portfolio(db_path):
    development, _ = _load_ibnr_inputs(db_path)
    for claim_type, triangle in development.groupby("claim_type"):
        factors = development_factors(triangle, "paid_uf_cum")
        tail = factors[factors.index >= 8]
        assert ((tail >= 0.995) & (tail <= 1.005)).all(), (claim_type, tail[(tail < 0.995) | (tail > 1.005)])


def test_estimate_ibnr_switches_method_for_cape_cod_types(db_path):
    development, exposure = _load_ibnr_inputs(db_path)
    cfg = load_pricing_config(PRICING_CONFIG)
    ibnr = estimate_ibnr(development, exposure, cfg)
    expected_columns = {
        "claim_type", "origin_quarter", "paid_uf", "ultimate_uf", "paid_capped_uf", "ultimate_capped_uf",
        "n_paid", "n_ultimate", "cdf_amount", "cdf_capped", "cdf_count", "method", "ibnr_uf",
    }
    assert expected_columns <= set(ibnr.columns)
    recent = sorted(ibnr.origin_quarter.unique())[-cfg.cape_cod_recent_quarters:]
    is_cape_cod = ibnr.claim_type.isin(cfg.cape_cod_claim_types) & ibnr.origin_quarter.isin(recent)
    assert (ibnr.loc[is_cape_cod, "method"] == "cape_cod").all()
    assert (ibnr.loc[~is_cape_cod, "method"] == "chain_ladder").all()
    assert is_cape_cod.sum() == len(cfg.cape_cod_claim_types) * cfg.cape_cod_recent_quarters
    assert (ibnr.ibnr_uf >= -1e-9).all()
    assert (ibnr.n_ultimate >= ibnr.n_paid - 1e-9).all()
    assert ibnr.ibnr_uf.to_numpy() == pytest.approx((ibnr.ultimate_uf - ibnr.paid_uf).to_numpy())
    assert not ibnr[list(expected_columns - {"method"})].isna().any().any()

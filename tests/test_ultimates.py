import shutil

import duckdb
import pandas as pd
import pytest

from colectivos.config import load_pricing_config
from colectivos.models.ibnr import estimate_ibnr
from colectivos.models.ultimates import cells_to_ultimate, save_ibnr_mart, to_yearly

PRICING_CONFIG = "config/pricing.yaml"


@pytest.fixture(scope="module")
def cells_and_ibnr(db_path) -> tuple[pd.DataFrame, pd.DataFrame]:
    with duckdb.connect(str(db_path), read_only=True) as con:
        cells = con.execute("SELECT * FROM marts.mart_model_cells_company").df()
        development = con.execute("SELECT * FROM marts.mart_development_quarterly").df()
    exposure = cells.groupby(["claim_type", "origin_quarter"], as_index=False).exposure_years.sum()
    ibnr = estimate_ibnr(development, exposure, load_pricing_config(PRICING_CONFIG))
    return cells, ibnr


def test_cell_ultimates_sum_to_ibnr_ultimates(cells_and_ibnr):
    cells, ibnr = cells_and_ibnr
    cells_ult = cells_to_ultimate(cells, ibnr)
    keys = ["claim_type", "origin_quarter"]
    sums = cells_ult.assign(origin_quarter=pd.to_datetime(cells_ult.origin_quarter)).groupby(keys)[
        ["n_claims_ult", "reimbursed_ult_uf", "reimbursed_capped_ult_uf"]
    ].sum()
    expected = ibnr.set_index(keys)[["n_ultimate", "ultimate_uf", "ultimate_capped_uf"]].loc[sums.index]
    assert sums.n_claims_ult.to_numpy() == pytest.approx(expected.n_ultimate.to_numpy(), rel=1e-9)
    assert sums.reimbursed_ult_uf.to_numpy() == pytest.approx(expected.ultimate_uf.to_numpy(), rel=1e-9)
    assert sums.reimbursed_capped_ult_uf.to_numpy() == pytest.approx(
        expected.ultimate_capped_uf.to_numpy(), rel=1e-9
    )


def test_cape_cod_allocation_gives_ultimate_to_contracts_without_paid(cells_and_ibnr):
    cells, ibnr = cells_and_ibnr
    cells_ult = cells_to_ultimate(cells, ibnr)
    unpaid = cells_ult[
        (cells_ult.claim_type == "alto_costo")
        & (pd.to_datetime(cells_ult.origin_quarter).dt.year == 2025)
        & (cells_ult.reimbursed_uf == 0)
        & (cells_ult.exposure_years > 0)
    ]
    assert len(unpaid) > 0
    assert (unpaid.reimbursed_ult_uf > 0).all()
    assert (unpaid.reimbursed_capped_ult_uf > 0).all()


def test_cape_cod_cells_with_ultimate_amount_have_ultimate_count(cells_and_ibnr):
    """La severidad (monto/conteo) se ajusta solo en celdas con conteo > 0: el IBNR de conteo de los trimestres
    Cape Cod se reparte por exposición igual que el monto, para que ningún monto último quede sin conteo."""
    cells, ibnr = cells_and_ibnr
    cells_ult = cells_to_ultimate(cells, ibnr)
    cape_cod_quarters = ibnr.loc[ibnr.method == "cape_cod", ["claim_type", "origin_quarter"]]
    cape_cod_cells = cells_ult.merge(
        cape_cod_quarters.assign(origin_quarter=pd.to_datetime(cape_cod_quarters.origin_quarter)),
        on=["claim_type", "origin_quarter"],
    )
    with_amount = cape_cod_cells[cape_cod_cells.reimbursed_capped_ult_uf > 0]
    assert len(with_amount) > 0
    assert (with_amount.n_claims_ult > 0).all()


def test_to_yearly_preserves_totals(cells_and_ibnr):
    cells, ibnr = cells_and_ibnr
    cells_ult = cells_to_ultimate(cells, ibnr)
    yearly = to_yearly(cells_ult)
    assert "origin_quarter" not in yearly.columns
    assert not yearly.duplicated(
        ["year", "claim_type", "company_id", "contract_id", "age_band", "sex", "health_system", "role",
         "industry", "region"]
    ).any()
    for column in ["exposure_years", "n_claims", "reimbursed_uf", "n_claims_ult", "reimbursed_ult_uf",
                   "reimbursed_capped_ult_uf"]:
        assert yearly[column].sum() == pytest.approx(cells_ult[column].sum(), rel=1e-9), column


def test_ibnr_mart_is_exported(db_path, cells_and_ibnr, tmp_path):
    from colectivos.warehouse.export import export_marts

    _, ibnr = cells_and_ibnr
    db_copy = tmp_path / "warehouse.duckdb"
    shutil.copy(db_path, db_copy)
    save_ibnr_mart(db_copy, ibnr)
    paths = export_marts(db_copy, tmp_path / "exports")
    assert "mart_ibnr.csv" in {path.name for path in paths}
    exported = pd.read_csv(tmp_path / "exports" / "mart_ibnr.csv")
    assert len(exported) == len(ibnr)
    assert {"claim_type", "origin_quarter", "paid_uf", "ultimate_uf", "ibnr_uf", "method", "cdf_amount"} <= set(
        exported.columns
    )

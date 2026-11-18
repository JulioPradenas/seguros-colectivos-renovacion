"""Siniestros últimos por celda (empresa x factores x trimestre) a partir del IBNR de la cartera, y mart_ibnr."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

CELL_KEYS: tuple[str, ...] = (
    "year", "claim_type", "company_id", "contract_id", "age_band", "sex", "health_system", "role", "industry",
    "region",
)
SUM_COLUMNS: tuple[str, ...] = (
    "exposure_years", "n_claims", "reimbursed_uf", "reimbursed_capped_uf", "n_claims_ult", "reimbursed_ult_uf",
    "reimbursed_capped_ult_uf",
)


def cells_to_ultimate(cells: pd.DataFrame, ibnr: pd.DataFrame) -> pd.DataFrame:
    """Chain-ladder: valor de la celda x CDF de su tipo y trimestre. Cape Cod (monto): pagado de la celda + IBNR
    del trimestre repartido por la exposición de la celda; así una celda sin pagos no queda en 0."""
    keys = ["claim_type", "origin_quarter"]
    quarter_ibnr = ibnr.assign(
        origin_quarter=pd.to_datetime(ibnr.origin_quarter),
        ibnr_capped_uf=ibnr.ultimate_capped_uf - ibnr.paid_capped_uf,
    )[keys + ["cdf_amount", "cdf_capped", "cdf_count", "method", "ibnr_uf", "ibnr_capped_uf"]]
    merged = cells.assign(origin_quarter=pd.to_datetime(cells.origin_quarter)).merge(
        quarter_ibnr, on=keys, how="left", validate="many_to_one"
    )
    exposure_share = merged.exposure_years / merged.groupby(keys).exposure_years.transform("sum")
    is_cape_cod = merged.method == "cape_cod"

    merged["n_claims_ult"] = merged.n_claims * merged.cdf_count
    merged["reimbursed_ult_uf"] = merged.reimbursed_uf * merged.cdf_amount
    merged["reimbursed_capped_ult_uf"] = merged.reimbursed_capped_uf * merged.cdf_capped
    merged.loc[is_cape_cod, "reimbursed_ult_uf"] = (
        merged.reimbursed_uf + merged.ibnr_uf * exposure_share
    )[is_cape_cod]
    merged.loc[is_cape_cod, "reimbursed_capped_ult_uf"] = (
        merged.reimbursed_capped_uf + merged.ibnr_capped_uf * exposure_share
    )[is_cape_cod]
    return merged.drop(columns=["cdf_amount", "cdf_capped", "cdf_count", "method", "ibnr_uf", "ibnr_capped_uf"])


def to_yearly(cells_ult: pd.DataFrame) -> pd.DataFrame:
    """Base de modelamiento anual: year x claim_type x empresa x contrato x factores."""
    return cells_ult.groupby(list(CELL_KEYS), as_index=False, observed=True)[list(SUM_COLUMNS)].sum()


def save_ibnr_mart(db_path: Path, ibnr: pd.DataFrame) -> None:
    mart = ibnr.assign(origin_quarter=pd.to_datetime(ibnr.origin_quarter).dt.date)
    with duckdb.connect(str(db_path)) as con:
        con.register("ibnr_frame", mart)
        con.execute("CREATE OR REPLACE TABLE marts.mart_ibnr AS SELECT * FROM ibnr_frame")
        con.unregister("ibnr_frame")

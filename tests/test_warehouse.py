import pandas as pd
import pytest

AGE_BANDS = {"0-17", "18-29", "30-44", "45-59", "60-69", "70+"}


def _scalar(db, sql: str):
    return db.execute(sql).fetchone()[0]


def test_exposure_years_match_raw(db, raw_dir):
    total_sql = _scalar(db, "SELECT SUM(exposure_years) FROM intermediate.int_exposure_contract_year")
    total_raw = pd.read_parquet(raw_dir / "exposure_monthly.parquet").exposure.sum() / 12
    assert total_sql == pytest.approx(total_raw, rel=1e-9)


def test_claims_totals_match_raw(db, raw_dir):
    raw = pd.read_parquet(raw_dir / "health_claims.parquet")
    assert _scalar(db, "SELECT SUM(n_claims) FROM intermediate.int_claims_contract_year") == len(raw)
    total_sql = _scalar(db, "SELECT SUM(reimbursed_uf) FROM intermediate.int_claims_contract_year")
    assert total_sql == pytest.approx(raw.reimbursed_uf.sum(), rel=1e-9)


def test_no_claims_after_valuation_in_warehouse(db):
    assert _scalar(db, "SELECT MAX(payment_date) FROM staging.stg_health_claims") <= pd.Timestamp("2025-12-31").date()


def test_staging_filters_late_payments_even_if_raw_has_them(raw_dir, tmp_path):
    import duckdb

    from colectivos.warehouse.build import build_warehouse

    leaky = tmp_path / "raw"
    leaky.mkdir()
    for path in raw_dir.glob("*.parquet"):
        frame = pd.read_parquet(path)
        if path.stem == "health_claims":
            late = frame.iloc[[0]].copy()
            late["claim_id"] = "S_LATE"
            late["payment_date"] = pd.Timestamp("2026-02-01")
            frame = pd.concat([frame, late], ignore_index=True)
        frame.to_parquet(leaky / path.name, index=False)
    db_file = tmp_path / "w.duckdb"
    build_warehouse(leaky, db_file)
    with duckdb.connect(str(db_file), read_only=True) as con:
        assert con.execute("SELECT COUNT(*) FROM staging.stg_health_claims WHERE claim_id = 'S_LATE'").fetchone()[0] == 0


def test_staging_has_no_null_keys(db):
    checks = {
        "stg_insureds": ["insured_id", "company_id"],
        "stg_contracts": ["contract_id", "company_id", "term_start"],
        "stg_health_claims": ["claim_id", "insured_id", "contract_id", "company_id"],
        "stg_exposure_monthly": ["insured_id", "company_id", "month"],
        "stg_premiums_monthly": ["contract_id", "month"],
    }
    for table, keys in checks.items():
        condition = " OR ".join(f"{k} IS NULL" for k in keys)
        assert _scalar(db, f"SELECT COUNT(*) FROM staging.{table} WHERE {condition}") == 0, table


def test_age_band_domain(db):
    bands = {row[0] for row in db.execute("SELECT DISTINCT age_band FROM intermediate.int_insured_profile_month").fetchall()}
    assert bands == AGE_BANDS


def test_every_claim_falls_inside_a_contract_term(db):
    orphans = _scalar(db, "SELECT COUNT(*) FROM intermediate.int_health_claims_term WHERE term_start IS NULL")
    assert orphans == 0
    outside = _scalar(
        db,
        "SELECT COUNT(*) FROM intermediate.int_health_claims_term "
        "WHERE occurrence_date < term_start OR occurrence_date > term_end",
    )
    assert outside == 0

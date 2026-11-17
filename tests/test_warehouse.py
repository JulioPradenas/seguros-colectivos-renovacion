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


def test_loss_ratio_definition(db):
    frame = db.execute("SELECT * FROM marts.mart_loss_ratio_contract_year WHERE earned_premium_uf > 0").df()
    expected = (frame.health_claims_uf + frame.life_claims_uf) / frame.earned_premium_uf
    assert frame.loss_ratio.to_numpy() == pytest.approx(expected.to_numpy(), rel=1e-9)


def test_loss_ratio_totals_match_sources(db, raw_dir):
    totals = db.execute(
        "SELECT SUM(earned_premium_uf), SUM(health_claims_uf), SUM(life_claims_uf) "
        "FROM marts.mart_loss_ratio_contract_year"
    ).fetchone()
    assert totals[0] == pytest.approx(pd.read_parquet(raw_dir / "premiums_monthly.parquet").earned_premium_uf.sum())
    assert totals[1] == pytest.approx(pd.read_parquet(raw_dir / "health_claims.parquet").reimbursed_uf.sum())
    assert totals[2] == pytest.approx(pd.read_parquet(raw_dir / "life_claims.parquet").capital_paid_uf.sum())


def test_loss_ratio_null_when_no_premium(db):
    bad = _scalar(
        db,
        "SELECT COUNT(*) FROM marts.mart_loss_ratio_contract_year "
        "WHERE COALESCE(earned_premium_uf, 0) = 0 AND loss_ratio IS NOT NULL",
    )
    assert bad == 0


def test_model_cells_include_zero_claim_cells(db):
    assert _scalar(db, "SELECT COUNT(*) FROM marts.mart_model_cells WHERE n_claims = 0") > 0
    assert _scalar(db, "SELECT COUNT(*) FROM marts.mart_model_cells WHERE exposure_years <= 0") == 0


def test_model_cells_totals_match_intermediate(db):
    cells = db.execute("SELECT SUM(n_claims), SUM(reimbursed_uf) FROM marts.mart_model_cells").fetchone()
    source = db.execute("SELECT SUM(n_claims), SUM(reimbursed_uf) FROM intermediate.int_claims_contract_year").fetchone()
    assert cells[0] == source[0]
    assert cells[1] == pytest.approx(source[1], rel=1e-9)
    exposure = _scalar(db, "SELECT SUM(exposure_years) FROM marts.mart_model_cells WHERE claim_type = 'dental'")
    assert exposure == pytest.approx(_scalar(db, "SELECT SUM(exposure_years) FROM intermediate.int_exposure_contract_year"))


def test_kpi_monthly_frequency_definition(db):
    frame = db.execute("SELECT * FROM marts.mart_kpi_monthly WHERE n_claims > 0").df()
    assert frame.frequency.to_numpy() == pytest.approx((frame.n_claims / frame.exposure_years).to_numpy())
    assert frame.severity.to_numpy() == pytest.approx((frame.reimbursed_uf / frame.n_claims).to_numpy())


def test_triangle_is_cumulative_nondecreasing(db):
    tri = db.execute(
        "SELECT * FROM marts.mart_payment_triangle ORDER BY claim_type, occurrence_year, development_month"
    ).df()
    diffs = tri.groupby(["claim_type", "occurrence_year"]).paid_uf_cumulative.diff().dropna()
    assert (diffs >= -1e-9).all()
    last = tri.groupby(["claim_type", "occurrence_year"]).paid_uf_cumulative.last().sum()
    assert last == pytest.approx(_scalar(db, "SELECT SUM(reimbursed_uf) FROM staging.stg_health_claims"))


def test_triangle_stops_at_valuation(db):
    latest = db.execute(
        "SELECT occurrence_year, MAX(development_month) FROM marts.mart_payment_triangle GROUP BY occurrence_year"
    ).df().set_index("occurrence_year").iloc[:, 0]
    assert latest.loc[2025] == 12
    assert latest.loc[2021] == 60


def test_export_writes_one_csv_per_mart(db_path, tmp_path):
    from colectivos.warehouse.export import export_marts

    paths = export_marts(db_path, tmp_path)
    assert {p.name for p in paths} == {
        "mart_loss_ratio_contract_year.csv", "mart_model_cells.csv", "mart_kpi_monthly.csv",
        "mart_payment_triangle.csv",
    }
    sample = pd.read_csv(tmp_path / "mart_kpi_monthly.csv")
    assert {"month", "claim_type", "loss_ratio"} <= set(sample.columns)

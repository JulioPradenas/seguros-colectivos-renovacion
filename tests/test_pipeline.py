import re
from pathlib import Path

from colectivos.pipeline import main, run_pipeline
from tests.conftest import CONFIG_DIR


def test_pipeline_small_end_to_end(tmp_path: Path):
    run_pipeline(CONFIG_DIR / "generator_small.yaml", tmp_path / "data", tmp_path / "exports")
    csvs = {p.name for p in (tmp_path / "exports" / "tableau").glob("*.csv")}
    assert csvs == {
        "mart_loss_ratio_contract_year.csv", "mart_model_cells.csv", "mart_kpi_monthly.csv",
        "mart_payment_triangle.csv", "mart_renewal_2026.csv", "mart_development_quarterly.csv",
        "mart_model_cells_company.csv", "mart_large_losses.csv", "mart_ibnr.csv", "mart_oot_by_type.csv",
        "mart_oot_by_segment.csv", "mart_oot_contract.csv",
    }
    import duckdb

    with duckdb.connect(str(tmp_path / "data" / "warehouse.duckdb"), read_only=True) as con:
        tables = {row[0] for row in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'marts'"
        ).fetchall()}
        renewal_columns = set(con.execute("SELECT * FROM marts.mart_renewal_2026 LIMIT 0").df().columns)
        oot_models = {row[0] for row in con.execute("SELECT DISTINCT model FROM marts.mart_oot_contract").fetchall()}
    assert {"mart_ibnr", "mart_oot_by_type", "mart_oot_by_segment", "mart_oot_contract"} <= tables
    assert {"credibility_factor", "credibility_z", "large_loss_load_uf", "unseen_level_flag"} <= renewal_columns
    assert oot_models == {"baseline", "two_stage", "tweedie"}
    draft = (tmp_path / "data" / "reports" / "informe_borrador.md").read_text()
    assert "Siniestralidad" in draft
    assert not re.search(r"\bnan\b", draft.lower()), "el borrador contiene valores NaN"
    assert "Compañía de Seguros Cordillera (ficticia)" in draft
    for heading in ["## Siniestralidad por año", "## Segmentos con mayor alza de frecuencia",
                    "## Reajuste requerido 2026", "## Suficiencia de prima",
                    "## Descomposición del reajuste agregado"]:
        assert heading in draft


def test_cli_parses_arguments(tmp_path: Path, monkeypatch):
    calls = {}
    monkeypatch.setattr("colectivos.pipeline.run_pipeline", lambda *args: calls.setdefault("args", args))
    main(["--config", "config/generator_small.yaml", "--out", str(tmp_path / "d"), "--exports", str(tmp_path / "e")])
    assert calls["args"] == (Path("config/generator_small.yaml"), tmp_path / "d", tmp_path / "e")

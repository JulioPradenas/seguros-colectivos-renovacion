import re
from pathlib import Path

from colectivos.pipeline import main, run_pipeline
from tests.conftest import CONFIG_DIR


def test_pipeline_small_end_to_end(tmp_path: Path):
    run_pipeline(CONFIG_DIR / "generator_small.yaml", tmp_path / "data", tmp_path / "exports")
    csvs = {p.name for p in (tmp_path / "exports" / "tableau").glob("*.csv")}
    assert csvs == {
        "mart_loss_ratio_contract_year.csv", "mart_model_cells.csv", "mart_kpi_monthly.csv",
        "mart_payment_triangle.csv", "mart_renewal_2026.csv",
    }
    draft = (tmp_path / "data" / "reports" / "informe_borrador.md").read_text()
    assert "Siniestralidad" in draft
    assert not re.search(r"\bnan\b", draft.lower()), "el borrador contiene valores NaN"
    assert "Compañía de Seguros Cordillera (ficticia)" in draft
    for heading in ["## Siniestralidad por año", "## Segmentos con mayor alza de frecuencia",
                    "## Reajuste requerido 2026", "## Suficiencia de prima"]:
        assert heading in draft


def test_cli_parses_arguments(tmp_path: Path, monkeypatch):
    calls = {}
    monkeypatch.setattr("colectivos.pipeline.run_pipeline", lambda *args: calls.setdefault("args", args))
    main(["--config", "config/generator_small.yaml", "--out", str(tmp_path / "d"), "--exports", str(tmp_path / "e")])
    assert calls["args"] == (Path("config/generator_small.yaml"), tmp_path / "d", tmp_path / "e")

"""Pipeline de un comando: genera la cartera, construye el warehouse, modela, tarifica y exporta."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from colectivos.calibration import calibration_report
from colectivos.config import load_generator_config, load_pricing_config
from colectivos.generator.life_claims import load_mortality
from colectivos.generator.run import run_generator
from colectivos.models.glm import actual_vs_expected, fit_all
from colectivos.pricing.technical_premium import renewal_table, save_renewal_mart
from colectivos.report.draft import build_draft
from colectivos.warehouse.build import build_warehouse
from colectivos.warehouse.export import export_marts

TRAIN_YEARS = (2021, 2024)
OUT_OF_TIME_YEAR = 2025


def run_pipeline(config_path: Path, out_dir: Path, exports_dir: Path) -> None:
    config_path, out_dir, exports_dir = Path(config_path), Path(out_dir), Path(exports_dir)
    config_dir = config_path.parent
    cfg = load_generator_config(config_path)
    db_path = out_dir / "warehouse.duckdb"

    print(f"[1/6] Generando cartera sintética ({cfg.n_companies} empresas)")
    run_generator(config_path, out_dir / "raw", out_dir / "truth")

    print("[2/6] Construyendo warehouse DuckDB")
    build_warehouse(out_dir / "raw", db_path, valuation_date=cfg.valuation_date)

    print("[3/6] Calibración contra objetivos de mercado")
    report = calibration_report(db_path, config_dir / "calibration_targets.yaml")
    print(report[["metric", "generated", "target_low", "target_high", "within_range"]].to_string(index=False))

    print(f"[4/6] GLM frecuencia/severidad (entrenamiento {TRAIN_YEARS[0]}-{TRAIN_YEARS[1]})")
    with duckdb.connect(str(db_path), read_only=True) as con:
        cells = con.execute("SELECT * FROM marts.mart_model_cells").df()
    models = fit_all(cells, train_years=TRAIN_YEARS)
    ae = actual_vs_expected(models, cells, year=OUT_OF_TIME_YEAR)
    print(f"Validación fuera de tiempo {OUT_OF_TIME_YEAR} (A/E < 1 esperado por IBNR al corte):")
    with pd.option_context("display.float_format", "{:,.3f}".format):
        print(ae.to_string(index=False))

    print("[5/6] Tarificando renovaciones 2026")
    pricing = load_pricing_config(config_dir / "pricing.yaml")
    mortality = load_mortality(config_dir / cfg.mortality_table)
    renewal = renewal_table(db_path, models, mortality, pricing, valuation_date=cfg.valuation_date)
    save_renewal_mart(db_path, renewal)

    print("[6/6] Exportando CSV para Tableau y borrador de informe")
    export_marts(db_path, exports_dir / "tableau")
    draft = build_draft(db_path, out_dir / "reports" / "informe_borrador.md")
    print(f"Listo. Borrador: {draft}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/generator.yaml"))
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--exports", type=Path, default=Path("exports"))
    args = parser.parse_args(argv)
    run_pipeline(args.config, args.out, args.exports)


if __name__ == "__main__":
    main()

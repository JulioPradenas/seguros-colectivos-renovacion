"""Pipeline de un comando: genera la cartera, construye el warehouse, estima el IBNR, valida fuera de tiempo,
reentrena, aplica credibilidad, tarifica 2026, descompone el reajuste y exporta."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb
import pandas as pd

from colectivos.calibration import calibration_report
from colectivos.config import load_generator_config, load_pricing_config
from colectivos.generator.life_claims import load_mortality
from colectivos.generator.run import run_generator
from colectivos.models.glm import fit_all
from colectivos.models.ibnr import estimate_ibnr
from colectivos.models.oot import BaselineModel, out_of_time_report
from colectivos.models.tweedie import fit_tweedie
from colectivos.models.two_stage import fit_two_stage
from colectivos.models.ultimates import cells_to_ultimate, save_ibnr_mart, to_yearly
from colectivos.pricing.credibility import buhlmann_straub, contract_experience, large_loss_load
from colectivos.pricing.technical_premium import renewal_table, save_renewal_mart
from colectivos.report.decomposition import rate_change_decomposition
from colectivos.report.draft import build_draft
from colectivos.warehouse.build import build_warehouse
from colectivos.warehouse.export import export_marts

N_STEPS = 8


def _step(number: int, text: str) -> None:
    print(f"[{number}/{N_STEPS}] {text}", flush=True)


def _save_mart(db_path: Path, name: str, frame: pd.DataFrame) -> None:
    with duckdb.connect(str(db_path)) as con:
        con.register("mart_frame", frame)
        con.execute(f"CREATE OR REPLACE TABLE marts.{name} AS SELECT * FROM mart_frame")
        con.unregister("mart_frame")


def _print_table(frame: pd.DataFrame) -> None:
    with pd.option_context("display.float_format", "{:,.3f}".format, "display.width", 160):
        print(frame.to_string(index=False))


def run_pipeline(config_path: Path, out_dir: Path, exports_dir: Path) -> None:
    started = time.perf_counter()
    config_path, out_dir, exports_dir = Path(config_path), Path(out_dir), Path(exports_dir)
    config_dir = config_path.parent
    cfg = load_generator_config(config_path)
    pricing = load_pricing_config(config_dir / "pricing.yaml")
    db_path = out_dir / "warehouse.duckdb"
    test_year = pricing.train_years_oot[1] + 1

    _step(1, f"Generando cartera sintética ({cfg.n_companies} empresas)")
    run_generator(config_path, out_dir / "raw", out_dir / "truth")

    _step(2, f"Construyendo warehouse DuckDB (umbral de siniestro grande {pricing.large_loss_threshold_uf:,.0f} UF)")
    build_warehouse(
        out_dir / "raw", db_path, valuation_date=cfg.valuation_date,
        large_loss_threshold_uf=pricing.large_loss_threshold_uf,
    )

    _step(3, "Calibración contra objetivos de mercado")
    report = calibration_report(db_path, config_dir / "calibration_targets.yaml")
    print(report[["metric", "generated", "target_low", "target_high", "within_range"]].to_string(index=False))

    _step(4, "IBNR (chain-ladder y Cape Cod) y siniestros últimos por celda")
    with duckdb.connect(str(db_path), read_only=True) as con:
        company_cells = con.execute("SELECT * FROM marts.mart_model_cells_company").df()
        development = con.execute("SELECT * FROM marts.mart_development_quarterly").df()
        paid_cells = con.execute("SELECT * FROM marts.mart_model_cells").df()
    exposure_quarter = company_cells.groupby(["claim_type", "origin_quarter"], as_index=False).exposure_years.sum()
    ibnr = estimate_ibnr(development, exposure_quarter, pricing)
    save_ibnr_mart(db_path, ibnr)
    cells_yearly = to_yearly(cells_to_ultimate(company_cells, ibnr))
    ibnr_by_year = ibnr.assign(year=pd.to_datetime(ibnr.origin_quarter).dt.year).groupby("year")[
        ["paid_uf", "ultimate_uf", "ibnr_uf"]
    ].sum().reset_index()
    _print_table(ibnr_by_year)

    first, last = pricing.train_years_oot
    _step(5, f"Validación fuera de tiempo: línea base, dos etapas y Tweedie ({first}-{last} → {test_year})")
    baseline = BaselineModel(fit_all(paid_cells, train_years=pricing.train_years_oot))
    champion = fit_two_stage(cells_yearly, pricing.train_years_oot, pricing)
    challenger = fit_tweedie(cells_yearly, pricing.train_years_oot, champion.trends, pricing.tweedie_powers)
    oot = out_of_time_report(
        {"baseline": baseline, "two_stage": champion, "tweedie": challenger},
        cells_yearly[cells_yearly.year == test_year],
        test_year,
    )
    for name, frame in oot.items():
        _save_mart(db_path, f"mart_oot_{name}", frame)
    _print_table(oot["by_type"])
    _print_table(oot["contract"])

    first, last = pricing.train_years_final
    _step(6, f"Reentrenamiento {first}-{last} en siniestros últimos, credibilidad y recargo por siniestros grandes")
    model = fit_two_stage(cells_yearly, pricing.train_years_final, pricing)
    credibility = buhlmann_straub(contract_experience(cells_yearly, model, pricing.train_years_final))
    load = large_loss_load(cells_yearly, model, pricing.train_years_final)
    print(f"Credibilidad: k = {credibility.k:,.1f}, center = {credibility.center:.4f}, "
          f"Z mediana = {credibility.by_contract.credibility_z.median():.3f}; recargo = {load:.4f}")

    _step(7, f"Tarificando renovaciones {pricing.pricing_year} y descomponiendo el reajuste agregado")
    mortality = load_mortality(config_dir / cfg.mortality_table)
    renewal = renewal_table(
        db_path, model, credibility, load, mortality, pricing, valuation_date=cfg.valuation_date
    )
    save_renewal_mart(db_path, renewal)
    decomposition = rate_change_decomposition(db_path, model, cells_yearly, renewal, pricing)
    _print_table(decomposition)

    _step(8, "Exportando CSV para Tableau y borrador de informe")
    export_marts(db_path, exports_dir / "tableau")
    draft = build_draft(db_path, out_dir / "reports" / "informe_borrador.md", decomposition=decomposition)
    print(f"Listo en {time.perf_counter() - started:,.0f} s. Borrador: {draft}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/generator.yaml"))
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--exports", type=Path, default=Path("exports"))
    args = parser.parse_args(argv)
    run_pipeline(args.config, args.out, args.exports)


if __name__ == "__main__":
    main()

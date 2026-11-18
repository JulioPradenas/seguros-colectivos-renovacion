"""python -m colectivos.validation --data data: valida los modelos contra la verdad del generador e imprime y guarda
las tablas en <data>/reports/validacion/. Corre aparte del pipeline de tarificación (que nunca lee la verdad)."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from colectivos.config import load_pricing_config
from colectivos.models.glm import fit_all
from colectivos.models.oot import BaselineModel
from colectivos.models.tweedie import fit_tweedie
from colectivos.models.two_stage import fit_two_stage
from colectivos.models.ultimates import cells_to_ultimate, to_yearly
from colectivos.validation.truth_checks import (
    credibility_gain,
    ibnr_error,
    oot_against_truth,
    pattern_detection,
    rate_change_effect_correlation,
    relativity_recovery,
    trend_recovery,
)


def _show(name: str, frame: pd.DataFrame, out_dir: Path) -> None:
    frame.to_csv(out_dir / f"{name}.csv", index=False)
    print(f"\n== {name} ==")
    with pd.option_context("display.float_format", "{:,.4f}".format, "display.width", 200, "display.max_colwidth", 120):
        print(frame.to_string(index=False))


def run_validation(data_dir: Path, config_dir: Path) -> None:
    data_dir = Path(data_dir)
    db_path, truth_dir = data_dir / "warehouse.duckdb", data_dir / "truth"
    out_dir = data_dir / "reports" / "validacion"
    out_dir.mkdir(parents=True, exist_ok=True)
    pricing = load_pricing_config(Path(config_dir) / "pricing.yaml")

    with duckdb.connect(str(db_path), read_only=True) as con:
        company_cells = con.execute("SELECT * FROM marts.mart_model_cells_company").df()
        ibnr = con.execute("SELECT * FROM marts.mart_ibnr").df()
        paid_cells = con.execute("SELECT * FROM marts.mart_model_cells").df()
        renewal = con.execute("SELECT * FROM marts.mart_renewal_2026").df()
    cells_yearly = to_yearly(cells_to_ultimate(company_cells, ibnr))

    errors = ibnr_error(db_path, truth_dir)
    _show("ibnr_error", errors, out_dir)
    by_year = errors.assign(year=pd.to_datetime(errors.origin_quarter).dt.year).groupby(["claim_type", "year"])[
        ["ibnr_est_uf", "ibnr_true_uf", "error_uf"]
    ].sum().reset_index()
    _show("ibnr_error_by_year", by_year[by_year.year >= 2024], out_dir)

    oot_model = fit_two_stage(cells_yearly, pricing.train_years_oot, pricing)
    final_model = fit_two_stage(cells_yearly, pricing.train_years_final, pricing)
    trends = pd.concat(
        [
            trend_recovery(oot_model.trends, truth_dir).assign(train_years=str(pricing.train_years_oot)),
            trend_recovery(final_model.trends, truth_dir).assign(train_years=str(pricing.train_years_final)),
        ]
    )
    _show("trend_recovery", trends, out_dir)
    _show("relativity_recovery", relativity_recovery(final_model, truth_dir), out_dir)
    _show("pattern_detection", pattern_detection(db_path, final_model, renewal, truth_dir), out_dir)
    _show("credibility_gain", credibility_gain(cells_yearly, pricing, truth_dir), out_dir)
    _show("rate_change_vs_effect", rate_change_effect_correlation(renewal, truth_dir), out_dir)

    test_year = pricing.train_years_oot[1] + 1
    predictors = {
        "baseline": BaselineModel(fit_all(paid_cells, train_years=pricing.train_years_oot)),
        "two_stage": oot_model,
        "tweedie": fit_tweedie(cells_yearly, pricing.train_years_oot, oot_model.trends, pricing.tweedie_powers),
    }
    annex = oot_against_truth(
        predictors, cells_yearly[cells_yearly.year == test_year], db_path, truth_dir, pricing.large_loss_threshold_uf
    )
    for name, frame in annex.items():
        _show(f"oot_truth_{name}", frame, out_dir)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--config", type=Path, default=Path("config"))
    args = parser.parse_args(argv)
    run_validation(args.data, args.config)


if __name__ == "__main__":
    main()

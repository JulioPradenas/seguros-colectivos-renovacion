"""Orquesta el generador: cartera, patrones, precios, siniestros, primas, verdad y corte de valoración."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from colectivos.config import load_generator_config
from colectivos.generator.exposure import build_exposure
from colectivos.generator.health_claims import draw_company_effects, enrich_exposure, generate_health_claims
from colectivos.generator.life_claims import draw_life_group_loadings, generate_life_claims, load_mortality
from colectivos.generator.patterns import inject_catastrophic_claim, pattern_multipliers, select_pattern_targets
from colectivos.generator.portfolio import generate_companies, generate_contracts, generate_insureds, generate_plans
from colectivos.generator.premiums import expected_annual_cost, generate_premiums, price_contracts


def _write(frame: pd.DataFrame, path: Path) -> None:
    frame.to_parquet(path, index=False)


def run_generator(cfg_path: Path, raw_dir: Path, truth_dir: Path) -> None:
    cfg_path = Path(cfg_path)
    cfg = load_generator_config(cfg_path)
    raw_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(cfg.seed)

    companies = generate_companies(cfg, rng)
    contracts = generate_contracts(cfg, companies, rng)
    insureds = generate_insureds(cfg, companies, rng)
    plans = generate_plans(cfg)
    exposure = build_exposure(insureds, cfg.start, cfg.end)
    enriched = enrich_exposure(exposure, insureds, companies, contracts)

    targets = select_pattern_targets(cfg, companies, contracts, rng)
    multipliers = pattern_multipliers(cfg, enriched, targets)
    company_effects = draw_company_effects(cfg, companies, rng)
    mortality = load_mortality(cfg_path.parent / cfg.mortality_table)
    life_loadings = draw_life_group_loadings(cfg, companies, rng)

    expected = expected_annual_cost(cfg, enriched, company_effects, multipliers, plans, contracts, mortality,
                                    life_loadings)
    contracts = price_contracts(cfg, contracts, expected, targets, rng)

    health_full = generate_health_claims(cfg, exposure, insureds, companies, contracts, plans, company_effects,
                                         rng, multipliers)
    health_full = inject_catastrophic_claim(cfg, health_full, enriched, targets, rng)
    life_full = generate_life_claims(cfg, enriched, contracts, mortality, life_loadings, rng)
    premiums = generate_premiums(contracts, enriched)

    _write(health_full, truth_dir / "health_claims_full.parquet")
    _write(life_full, truth_dir / "life_claims_full.parquet")
    _write(
        pd.DataFrame({"company_id": company_effects.index, "company_effect": company_effects.to_numpy(),
                      "life_group_loading": life_loadings.reindex(company_effects.index).to_numpy()}),
        truth_dir / "company_effects.parquet",
    )
    _write(expected, truth_dir / "expected_cost.parquet")
    (truth_dir / "parameters.json").write_text(json.dumps(asdict(cfg), default=str, indent=2, ensure_ascii=False))
    (truth_dir / "patterns.json").write_text(json.dumps(targets, default=str, indent=2, ensure_ascii=False))

    valuation = pd.Timestamp(cfg.valuation_date)
    health_raw = health_full[health_full.payment_date <= valuation]
    life_raw = life_full[life_full.death_date <= valuation]
    for name, frame in {
        "companies": companies.drop(columns=["n_holders_target"]),
        "plans": plans,
        "contracts": contracts,
        "insureds": insureds,
        "exposure_monthly": exposure,
        "health_claims": health_raw,
        "life_claims": life_raw,
        "premiums_monthly": premiums,
    }.items():
        _write(frame, raw_dir / f"{name}.parquet")

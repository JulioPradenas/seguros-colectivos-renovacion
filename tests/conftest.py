from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from colectivos.config import GeneratorConfig, load_generator_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"


@pytest.fixture(scope="session")
def small_cfg() -> GeneratorConfig:
    return load_generator_config(CONFIG_DIR / "generator_small.yaml")


@pytest.fixture(scope="session")
def portfolio(small_cfg: GeneratorConfig) -> dict[str, pd.DataFrame]:
    from colectivos.generator.exposure import build_exposure
    from colectivos.generator.portfolio import (
        generate_companies,
        generate_contracts,
        generate_insureds,
        generate_plans,
    )

    rng = np.random.default_rng(small_cfg.seed)
    companies = generate_companies(small_cfg, rng)
    contracts = generate_contracts(small_cfg, companies, rng)
    insureds = generate_insureds(small_cfg, companies, rng)
    exposure = build_exposure(insureds, small_cfg.start, small_cfg.end)
    return {
        "companies": companies,
        "plans": generate_plans(small_cfg),
        "contracts": contracts,
        "insureds": insureds,
        "exposure": exposure,
    }


@pytest.fixture(scope="session")
def companies(portfolio) -> pd.DataFrame:
    return portfolio["companies"]


@pytest.fixture(scope="session")
def plans(portfolio) -> pd.DataFrame:
    return portfolio["plans"]


@pytest.fixture(scope="session")
def contracts(portfolio) -> pd.DataFrame:
    return portfolio["contracts"]


@pytest.fixture(scope="session")
def insureds(portfolio) -> pd.DataFrame:
    return portfolio["insureds"]


@pytest.fixture(scope="session")
def exposure(portfolio) -> pd.DataFrame:
    return portfolio["exposure"]


@pytest.fixture(scope="session")
def claims(small_cfg: GeneratorConfig, portfolio) -> pd.DataFrame:
    from colectivos.generator.health_claims import draw_company_effects, generate_health_claims

    rng = np.random.default_rng(small_cfg.seed + 1)
    effects = draw_company_effects(small_cfg, portfolio["companies"], rng)
    return generate_health_claims(
        small_cfg,
        portfolio["exposure"],
        portfolio["insureds"],
        portfolio["companies"],
        portfolio["contracts"],
        portfolio["plans"],
        effects,
        rng,
    )

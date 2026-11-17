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


@pytest.fixture(scope="session")
def generated_dirs(tmp_path_factory) -> tuple[Path, Path]:
    from colectivos.generator.run import run_generator

    root = tmp_path_factory.mktemp("small_run")
    raw, truth = root / "raw", root / "truth"
    run_generator(CONFIG_DIR / "generator_small.yaml", raw, truth)
    return raw, truth


@pytest.fixture(scope="session")
def raw_dir(generated_dirs) -> Path:
    return generated_dirs[0]


@pytest.fixture(scope="session")
def truth_dir(generated_dirs) -> Path:
    return generated_dirs[1]


@pytest.fixture(scope="session")
def db_path(raw_dir, tmp_path_factory) -> Path:
    from colectivos.warehouse.build import build_warehouse

    path = tmp_path_factory.mktemp("warehouse") / "warehouse.duckdb"
    build_warehouse(raw_dir, path)
    return path


@pytest.fixture()
def db(db_path):
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    yield con
    con.close()


@pytest.fixture(scope="session")
def models(db_path):
    import duckdb

    from colectivos.models.glm import fit_all

    with duckdb.connect(str(db_path), read_only=True) as con:
        cells = con.execute("SELECT * FROM marts.mart_model_cells").df()
    return fit_all(cells, train_years=(2021, 2024))


@pytest.fixture(scope="session")
def medium_db_path(tmp_path_factory) -> Path:
    import yaml

    from colectivos.generator.run import run_generator
    from colectivos.warehouse.build import build_warehouse

    root = tmp_path_factory.mktemp("medium")
    raw_cfg = yaml.safe_load((CONFIG_DIR / "generator_small.yaml").read_text())
    raw_cfg["n_companies"] = 100
    raw_cfg["mortality_table"] = str(CONFIG_DIR / raw_cfg["mortality_table"])
    cfg_path = root / "generator_medium.yaml"
    cfg_path.write_text(yaml.safe_dump(raw_cfg))
    run_generator(cfg_path, root / "raw", root / "truth")
    build_warehouse(root / "raw", root / "warehouse.duckdb")
    return root / "warehouse.duckdb"

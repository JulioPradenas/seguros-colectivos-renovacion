from pathlib import Path

import pytest

from colectivos.config import GeneratorConfig, load_generator_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"


@pytest.fixture(scope="session")
def small_cfg() -> GeneratorConfig:
    return load_generator_config(CONFIG_DIR / "generator_small.yaml")

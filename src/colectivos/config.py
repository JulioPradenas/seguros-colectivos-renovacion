"""Carga y validación de la configuración YAML del generador y de la tarificación."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path
from typing import Any

import yaml

CLAIM_TYPES: tuple[str, ...] = ("ambulatoria", "hospitalaria", "dental", "farmacia", "alto_costo")
HEALTH_SYSTEMS: tuple[str, ...] = ("isapre", "fonasa")
ROLES: tuple[str, ...] = ("titular", "carga")
AGE_BANDS: tuple[str, ...] = ("0-17", "18-29", "30-44", "45-59", "60-69", "70+")
AGE_BAND_EDGES: tuple[int, ...] = (0, 18, 30, 45, 60, 70, 200)


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int
    start: date
    end: date
    valuation_date: date
    n_companies: int
    industries: dict[str, float]
    regions: dict[str, float]
    company_size_lognormal: dict[str, float]
    dependents_per_holder: float
    fonasa_share: float
    annual_turnover: float
    company_lapse_rate: float
    new_client_share: float
    holder_age: dict[str, float]
    dependent_age: dict[str, Any]
    claim_types: list[str]
    base_frequency: dict[str, float]
    relativities: dict[str, dict[str, float]]
    frequency_trend: dict[str, float]
    annual_trend: dict[str, float]
    seasonality: dict[str, Any]
    company_effect_shape: float
    severity: dict[str, dict[str, Any]]
    catastrophic: dict[str, float]
    system_coverage: dict[str, dict[str, float]]
    plans: list[dict[str, Any]]
    payment_lag_days: dict[str, dict[str, float]]
    life_capital_uf: list[float]
    mortality_table: str
    life_group_loading: dict[str, float]
    initial_loading: float
    initial_premium_noise_sigma: float
    expense_ratio: float
    commission_ratio: float
    historic_rate_change: dict[str, float]
    patterns: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class PricingConfig:
    expense_ratio: float
    commission_ratio: float
    target_margin: float
    low_exposure_threshold_years: float
    pricing_year: int


def _require_keys(raw: dict[str, Any], cls: type, path: Path) -> None:
    missing = [f.name for f in fields(cls) if f.name not in raw]
    if missing:
        raise ValueError(f"{path}: faltan claves {missing}")


def _check_weights(name: str, weights: dict[str, float]) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"{name}: los pesos suman {total}, deben sumar 1")


def _check_claim_type_keys(name: str, mapping: dict[str, Any]) -> None:
    unknown = set(mapping) - set(CLAIM_TYPES)
    missing = set(CLAIM_TYPES) - set(mapping)
    if unknown or missing:
        raise ValueError(f"{name}: tipos desconocidos {sorted(unknown)}, faltantes {sorted(missing)}")


def _validate(cfg: GeneratorConfig) -> None:
    unknown = [t for t in cfg.claim_types if t not in CLAIM_TYPES]
    if unknown or set(cfg.claim_types) != set(CLAIM_TYPES):
        raise ValueError(f"claim_types inválidos: {unknown or cfg.claim_types}")
    _check_weights("industries", cfg.industries)
    _check_weights("regions", cfg.regions)
    _check_weights("plans", {p["plan_id"]: p["weight"] for p in cfg.plans})
    if cfg.valuation_date > cfg.end:
        raise ValueError("valuation_date no puede ser posterior a end")
    if set(cfg.system_coverage) != set(HEALTH_SYSTEMS):
        raise ValueError(f"system_coverage debe tener {HEALTH_SYSTEMS}")
    for name in ("base_frequency", "frequency_trend", "annual_trend", "severity", "payment_lag_days"):
        _check_claim_type_keys(name, getattr(cfg, name))
    for system, coverage in cfg.system_coverage.items():
        _check_claim_type_keys(f"system_coverage.{system}", coverage)
    if set(cfg.relativities["industry"]) != set(cfg.industries):
        raise ValueError("relativities.industry debe cubrir las mismas industrias que industries")
    if set(cfg.relativities["region"]) != set(cfg.regions):
        raise ValueError("relativities.region debe cubrir las mismas regiones que regions")
    if set(cfg.relativities["age_band"]) != set(AGE_BANDS):
        raise ValueError(f"relativities.age_band debe tener {AGE_BANDS}")


def load_generator_config(path: Path) -> GeneratorConfig:
    raw = yaml.safe_load(Path(path).read_text())
    _require_keys(raw, GeneratorConfig, path)
    cfg = GeneratorConfig(**{f.name: raw[f.name] for f in fields(GeneratorConfig)})
    _validate(cfg)
    return cfg


def load_pricing_config(path: Path) -> PricingConfig:
    raw = yaml.safe_load(Path(path).read_text())
    _require_keys(raw, PricingConfig, path)
    cfg = PricingConfig(**{f.name: raw[f.name] for f in fields(PricingConfig)})
    loading = cfg.expense_ratio + cfg.commission_ratio + cfg.target_margin
    if not 0 < loading < 1:
        raise ValueError(f"gastos + comisión + margen = {loading}, debe estar en (0, 1)")
    return cfg

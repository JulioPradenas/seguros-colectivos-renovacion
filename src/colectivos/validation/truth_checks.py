"""Chequeos contra la verdad del generador (data/truth/). Solo se usan desde `python -m colectivos.validation` y el
notebook de validación; el pipeline de tarificación nunca lee la verdad."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from colectivos.config import PricingConfig
from colectivos.models.glm import FACTORS, REFERENCE_YEAR
from colectivos.models.oot import CostPredictor, _expected_by_row, out_of_time_report
from colectivos.models.trend import TrendModel
from colectivos.models.two_stage import TwoStageModel, fit_two_stage
from colectivos.pricing.credibility import buhlmann_straub, contract_experience
from colectivos.warehouse.build import DEFAULT_LARGE_LOSS_THRESHOLD_UF

SMALL_COMPANY_MAX_HOLDERS = 50
COHORT_START = pd.Timestamp("2023-01-01")
FONASA_SHIFT_START_YEAR = 2024
CELL_KEYS = ["year", "claim_type", "company_id", "contract_id", *FACTORS]


def _parameters(truth_dir: Path) -> dict:
    return json.loads((Path(truth_dir) / "parameters.json").read_text())


def _patterns(truth_dir: Path) -> dict:
    return json.loads((Path(truth_dir) / "patterns.json").read_text())


def _truth_claims(truth_dir: Path, columns: list[str] | None = None) -> pd.DataFrame:
    claims = pd.read_parquet(Path(truth_dir) / "health_claims_full.parquet", columns=columns)
    claims["occurrence_date"] = pd.to_datetime(claims.occurrence_date)
    return claims


def ibnr_error(db_path: Path, truth_dir: Path) -> pd.DataFrame:
    """IBNR estimado contra el verdadero (todo lo ocurrido en el trimestre según la verdad − lo pagado al corte)."""
    with duckdb.connect(str(db_path), read_only=True) as con:
        ibnr = con.execute("SELECT claim_type, origin_quarter, paid_uf, ibnr_uf FROM marts.mart_ibnr").df()
    ibnr["origin_quarter"] = pd.to_datetime(ibnr.origin_quarter)
    claims = _truth_claims(truth_dir, ["claim_type", "occurrence_date", "reimbursed_uf"])
    claims["origin_quarter"] = claims.occurrence_date.dt.to_period("Q").dt.start_time
    total = claims.groupby(["claim_type", "origin_quarter"]).reimbursed_uf.sum().rename("true_total_uf")
    errors = ibnr.join(total, on=["claim_type", "origin_quarter"]).fillna({"true_total_uf": 0.0})
    errors = errors.rename(columns={"ibnr_uf": "ibnr_est_uf"})
    errors["ibnr_true_uf"] = errors.true_total_uf - errors.paid_uf
    errors["error_uf"] = errors.ibnr_est_uf - errors.ibnr_true_uf
    errors["error_rel"] = np.where(errors.ibnr_true_uf > 0, errors.error_uf / errors.ibnr_true_uf.where(errors.ibnr_true_uf > 0), np.nan)
    return errors[["claim_type", "origin_quarter", "paid_uf", "ibnr_est_uf", "ibnr_true_uf", "error_uf", "error_rel"]]


def trend_recovery(trends: dict[str, TrendModel], truth_dir: Path) -> pd.DataFrame:
    params = _parameters(truth_dir)
    rows = []
    for claim_type, trend in trends.items():
        freq_true = params["frequency_trend"][claim_type]
        sev_true = params["annual_trend"][claim_type]
        rows.append(
            {
                "claim_type": claim_type,
                "freq_est": trend.freq_trend, "freq_true": freq_true,
                "sev_est": trend.sev_trend, "sev_true": sev_true,
                "total_est": (1 + trend.freq_trend) * (1 + trend.sev_trend) - 1,
                "total_true": (1 + freq_true) * (1 + sev_true) - 1,
                "industry_freq_trend": json.dumps(trend.industry_freq_trend),
            }
        )
    return pd.DataFrame(rows)


def relativity_recovery(model: TwoStageModel, truth_dir: Path) -> pd.DataFrame:
    """Relatividades de frecuencia de la etapa 2 contra las del generador, ambas relativas al nivel base del GLM
    (el primero en orden alfabético entre los niveles con siniestros)."""
    truth = _parameters(truth_dir)["relativities"]
    rows = []
    for claim_type, relativity_model in model.relativities.items():
        params = relativity_model.freq.params
        for factor in FACTORS:
            if factor not in truth:
                continue
            levels = sorted(relativity_model.levels.freq[factor])
            base = levels[0]
            for level in levels:
                term = f"C({factor})[T.{level}]"
                rows.append(
                    {
                        "claim_type": claim_type, "factor": factor, "level": level, "base_level": base,
                        "estimated": float(np.exp(params[term])) if term in params.index else 1.0,
                        "true": truth[factor][level] / truth[factor][base],
                    }
                )
    return pd.DataFrame(rows)


def _cohort_ae(db_path: Path, model: TwoStageModel, first_year: int, last_year: int) -> pd.DataFrame:
    """A/E de frecuencia (todos los tipos, pagados) por empresa chica y cohorte de ingreso (antes/desde 2023)."""
    with duckdb.connect(str(db_path), read_only=True) as con:
        exposure = con.execute(
            f"""
            WITH holders AS (
                SELECT company_id, COUNT(*) AS n_holders
                FROM staging.stg_insureds
                WHERE role = 'titular'
                GROUP BY company_id
            )
            SELECT profile.*, insureds.enrollment_date
            FROM intermediate.int_insured_profile_month AS profile
            INNER JOIN staging.stg_insureds AS insureds
                ON profile.insured_id = insureds.insured_id
            INNER JOIN holders
                ON profile.company_id = holders.company_id
            WHERE profile.year BETWEEN {first_year} AND {last_year}
                AND holders.n_holders <= {SMALL_COMPANY_MAX_HOLDERS}
            """
        ).df()
        claims = con.execute(
            f"""
            SELECT insured_id, COUNT(*) AS n_claims
            FROM intermediate.int_health_claims_term
            WHERE year BETWEEN {first_year} AND {last_year}
            GROUP BY insured_id
            """
        ).df()
    exposure["new_cohort"] = pd.to_datetime(exposure.enrollment_date) >= COHORT_START
    frequency = model.predict_frequency(exposure, exposure.year - REFERENCE_YEAR)
    exposure["expected"] = frequency.sum(axis=1) * exposure.exposure / 12
    by_insured = exposure.groupby(["company_id", "new_cohort", "insured_id"], as_index=False).expected.sum()
    by_insured["actual"] = by_insured.insured_id.map(claims.set_index("insured_id").n_claims).fillna(0.0)
    return by_insured.groupby(["company_id", "new_cohort"], as_index=False)[["actual", "expected"]].sum()


def pattern_detection(db_path: Path, model: TwoStageModel, renewal: pd.DataFrame, truth_dir: Path) -> pd.DataFrame:
    """Detección de los 5 patrones con criterios que no miran la verdad; la verdad solo dice dónde estaban
    (spec Fase 2, 5.9). detected es un hallazgo, no una compuerta."""
    planted = _patterns(truth_dir)
    rows = []

    hospital = model.trends["hospitalaria"]
    target = planted["industry_hospital_trend"]["industry"]
    extra = hospital.industry_freq_trend
    detected = bool(extra) and max(extra, key=extra.get) == target and extra[target] > 0
    rows.append(("industry_hospital_trend", detected,
                 f"tendencias adicionales retenidas {json.dumps({k: round(v, 4) for k, v in extra.items()})}, "
                 f"p LR = {hospital.lr_pvalue}"))

    cohort = _cohort_ae(db_path, model, COHORT_START.year, model.train_years[1])
    cohort["planted"] = cohort.company_id.isin(planted["adverse_selection"]["companies"])
    totals = cohort.groupby(["planted", "new_cohort"])[["actual", "expected"]].sum()
    ae = (totals.actual / totals.expected).unstack("new_cohort")
    ratio = (ae[True] / ae[False]).reindex([True, False])
    detected = bool(ratio.loc[True] > 1.2 and ratio.loc[True] > ratio.loc[False])
    rows.append(("adverse_selection", detected,
                 f"A/E cohorte ≥2023 / cohorte anterior en empresas chicas: plantadas {ratio.loc[True]:.3f}, "
                 f"resto {ratio.loc[False]:.3f}"))

    catastrophic = planted["catastrophic_event"]
    with duckdb.connect(str(db_path), read_only=True) as con:
        large = con.execute("SELECT * FROM marts.mart_large_losses").df()
    match = large[
        (large.company_id == catastrophic["company_id"])
        & (pd.to_datetime(large.occurrence_date).dt.year == catastrophic["year"])
        & (large.reimbursed_uf >= 0.99 * catastrophic["amount_uf"])
    ]
    detected = not match.empty
    evidence = (f"{len(large)} siniestros sobre el umbral; el catastrófico aparece con {match.reimbursed_uf.iloc[0]:,.0f} UF "
                f"y exceso {match.excess_uf.iloc[0]:,.0f} UF fuera de la experiencia") if detected else f"{len(large)} siniestros sobre el umbral; el catastrófico no aparece"
    rows.append(("catastrophic_event", detected, evidence))

    is_planted = renewal.contract_id.isin(planted["inadequate_rate_changes"]["contracts"])
    top_quartile = renewal.required_rate_change >= renewal.required_rate_change.quantile(0.75)
    share_top = float(top_quartile[is_planted].mean()) if is_planted.any() else float("nan")
    median_planted = renewal.required_rate_change[is_planted].median()
    median_rest = renewal.required_rate_change[~is_planted].median()
    detected = bool(is_planted.any() and median_planted > median_rest and share_top > 0.25)
    rows.append(("inadequate_rate_changes", detected,
                 f"reajuste requerido mediano: sin reajuste {median_planted:+.1%} vs resto {median_rest:+.1%}; "
                 f"{share_top:.0%} de los contratos sin reajuste en el cuartil superior ({int(is_planted.sum())} contratos)"))

    with duckdb.connect(str(db_path), read_only=True) as con:
        shares = con.execute(
            """
            SELECT
                YEAR(enrollment_date) AS enrollment_year,
                AVG(CASE WHEN health_system = 'fonasa' THEN 1.0 ELSE 0.0 END) AS fonasa_share,
                COUNT(*) AS n
            FROM staging.stg_insureds
            WHERE YEAR(enrollment_date) >= 2021
            GROUP BY ALL
            ORDER BY enrollment_year
            """
        ).df().set_index("enrollment_year")
    before = shares[shares.index < FONASA_SHIFT_START_YEAR]
    after = shares[shares.index >= FONASA_SHIFT_START_YEAR]
    share_before = float(np.average(before.fonasa_share, weights=before.n))
    share_after = float(np.average(after.fonasa_share, weights=after.n))
    detected = share_after / share_before >= 1.3
    rows.append(("fonasa_shift", bool(detected),
                 "proporción Fonasa por año de ingreso: "
                 + ", ".join(f"{year} {share:.1%}" for year, share in shares.fonasa_share.items())))
    return pd.DataFrame(rows, columns=["pattern", "detected", "evidence"]).astype({"detected": bool})


def _realized_capped_by_contract(truth_dir: Path, year: int, threshold: float) -> pd.Series:
    claims = _truth_claims(truth_dir, ["contract_id", "occurrence_date", "reimbursed_uf"])
    claims = claims[claims.occurrence_date.dt.year == year]
    return claims.reimbursed_uf.clip(upper=threshold).groupby(claims.contract_id).sum()


def credibility_gain(cells_yearly: pd.DataFrame, cfg: PricingConfig, truth_dir: Path) -> pd.DataFrame:
    """Modelo y credibilidad estimados con los años de entrenamiento fuera de tiempo, contra el costo realizado
    completo (verdad) y limitado del año siguiente, por contrato."""
    test_year = cfg.train_years_oot[1] + 1
    model = fit_two_stage(cells_yearly, cfg.train_years_oot, cfg)
    credibility = buhlmann_straub(contract_experience(cells_yearly, model, cfg.train_years_oot))
    test = cells_yearly[(cells_yearly.year == test_year) & (cells_yearly.exposure_years > 0)].reset_index(drop=True)
    rows = _expected_by_row(model, test, float(test_year - REFERENCE_YEAR))
    by_contract = rows.groupby("contract_id").expected_uf.sum().to_frame("expected_uf")
    by_contract["exposure"] = test[test.claim_type == test.claim_type.iloc[0]].groupby("contract_id").exposure_years.sum()
    by_contract["actual_uf"] = _realized_capped_by_contract(truth_dir, test_year, cfg.large_loss_threshold_uf)
    by_contract = by_contract.fillna({"actual_uf": 0.0})
    by_contract = by_contract[by_contract.exposure > 0]
    factor = credibility.by_contract.set_index("contract_id").credibility_factor
    by_contract["factor"] = by_contract.index.map(factor).fillna(credibility.center)
    by_contract["credible_uf"] = by_contract.expected_uf * by_contract.factor

    company = cells_yearly.drop_duplicates("contract_id").set_index("contract_id").company_id
    effects = pd.read_parquet(Path(truth_dir) / "company_effects.parquet").set_index("company_id").company_effect
    effect = by_contract.index.map(company).map(effects).to_numpy(dtype=float)

    def metrics(expected: pd.Series) -> list[float]:
        error = (by_contract.actual_uf - expected) / by_contract.exposure
        return [
            float(np.sqrt(np.average(error**2, weights=by_contract.exposure))),
            float(by_contract.actual_uf.sum() / expected.sum()),
        ]

    return pd.DataFrame(
        {
            "metric": ["rmse_per_py", "ae", "corr_log_factor_log_effect"],
            "model_only": [*metrics(by_contract.expected_uf), np.nan],
            "with_credibility": [
                *metrics(by_contract.credible_uf),
                float(np.corrcoef(np.log(by_contract.factor), np.log(effect))[0, 1]),
            ],
        }
    )


def _truth_cells(db_path: Path, truth_dir: Path, year: int, threshold: float) -> pd.DataFrame:
    """Costo completo (verdad) y limitado por celda, con el perfil del asegurado en su mes de ocurrencia."""
    claims = _truth_claims(truth_dir, ["insured_id", "claim_type", "occurrence_date", "reimbursed_uf"])
    claims = claims[claims.occurrence_date.dt.year == year]
    claims = claims.assign(
        month=claims.occurrence_date.dt.to_period("M").dt.start_time,
        capped_uf=claims.reimbursed_uf.clip(upper=threshold),
    )[["insured_id", "claim_type", "month", "capped_uf"]]
    with duckdb.connect(str(db_path), read_only=True) as con:
        con.register("truth_claims", claims)
        cells = con.execute(
            f"""
            SELECT
                profile.year, truth_claims.claim_type, profile.company_id, profile.contract_id,
                {", ".join(f"profile.{factor}" for factor in FACTORS)},
                COUNT(*) AS n_true, SUM(truth_claims.capped_uf) AS capped_true_uf
            FROM truth_claims
            INNER JOIN intermediate.int_insured_profile_month AS profile
                ON truth_claims.insured_id = profile.insured_id
                AND truth_claims.month = profile.month
            GROUP BY ALL
            """
        ).df()
        con.unregister("truth_claims")
    return cells


def oot_against_truth(
    predictors: dict[str, CostPredictor],
    test_cells: pd.DataFrame,
    db_path: Path,
    truth_dir: Path,
    large_loss_threshold_uf: float = DEFAULT_LARGE_LOSS_THRESHOLD_UF,
) -> dict[str, pd.DataFrame]:
    """Anexo de 5.5: el mismo reporte fuera de tiempo con el costo real completo de la verdad; ae_shift = A/E
    contra la verdad − A/E contra los últimos estimados (el error que aporta el IBNR)."""
    test_year = int(test_cells.year.max())
    estimated = out_of_time_report(predictors, test_cells, test_year)
    truth = _truth_cells(db_path, truth_dir, test_year, large_loss_threshold_uf)
    for factor in FACTORS:
        truth[factor] = truth[factor].astype(str)
    merged = test_cells.assign(**{factor: test_cells[factor].astype(str) for factor in FACTORS}).merge(
        truth, on=CELL_KEYS, how="left"
    )
    true_cells = merged.assign(
        n_claims_ult=merged.n_true.fillna(0.0).astype(float),
        reimbursed_capped_ult_uf=merged.capped_true_uf.fillna(0.0).astype(float),
    ).drop(columns=["n_true", "capped_true_uf"])
    against_truth = out_of_time_report(predictors, true_cells, test_year)
    keys = {"by_type": ["model", "claim_type"], "by_segment": ["model", "factor", "level"], "contract": ["model"]}
    for name, key in keys.items():
        shift = against_truth[name].merge(estimated[name][[*key, "ae"]], on=key, suffixes=("", "_estimated"))
        against_truth[name] = shift.assign(ae_shift=shift.ae - shift.ae_estimated).drop(columns="ae_estimated")
    return against_truth

"""Borrador del informe ejecutivo con las cifras clave del warehouse (la narrativa se completa en la fase 4)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

COMPANY_NAME = "Compañía de Seguros Cordillera (ficticia)"


def _num(value: float, decimals: int = 2) -> str:
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _pct(value: float, decimals: int = 1) -> str:
    return f"{_num(100 * value, decimals)}%"


def _markdown_table(frame: pd.DataFrame) -> str:
    header = "| " + " | ".join(frame.columns) + " |"
    divider = "|" + "|".join("---" for _ in frame.columns) + "|"
    body = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, divider, *body])


def _decomposition_section(decomposition: pd.DataFrame | None) -> str:
    if decomposition is None:
        return ""
    total = float(decomposition.multiplier.prod())
    table = pd.DataFrame(
        {
            "Factor": decomposition.factor,
            "Multiplicador": decomposition.multiplier.map(lambda v: f"×{_num(v, 3)}"),
            "Participación (log)": decomposition.log_share.map(lambda v: _pct(v) if pd.notna(v) else "—"),
        }
    )
    return f"""
## Descomposición del reajuste agregado

Prima técnica total / prima vigente total de los contratos que renuevan = ×{_num(total, 4)}
(reajuste agregado {_pct(total - 1)}). El producto de los factores es exactamente ese cociente.

{_markdown_table(table)}
"""


def build_draft(db_path: Path, out_path: Path, decomposition: pd.DataFrame | None = None) -> Path:
    with duckdb.connect(str(db_path), read_only=True) as con:
        loss_ratio = con.execute(
            """
            SELECT
                year,
                SUM(earned_premium_uf) AS premium,
                SUM(health_claims_uf + life_claims_uf) AS claims,
                SUM(health_claims_uf + life_claims_uf) / SUM(earned_premium_uf) AS loss_ratio
            FROM marts.mart_loss_ratio_contract_year
            GROUP BY year
            ORDER BY year
            """
        ).df()
        segments = con.execute(
            """
            WITH frequency AS (
                SELECT
                    industry,
                    claim_type,
                    SUM(CASE WHEN year = 2021 THEN n_claims END)
                        / SUM(CASE WHEN year = 2021 THEN exposure_years END) AS freq_2021,
                    SUM(CASE WHEN year = 2024 THEN n_claims END)
                        / SUM(CASE WHEN year = 2024 THEN exposure_years END) AS freq_2024
                FROM marts.mart_model_cells
                WHERE claim_type <> 'alto_costo'
                GROUP BY industry, claim_type
            )
            SELECT industry, claim_type, freq_2021, freq_2024, freq_2024 / freq_2021 - 1 AS change
            FROM frequency
            WHERE freq_2021 > 0
            ORDER BY change DESC
            LIMIT 3
            """
        ).df()
        renewal = con.execute("SELECT * FROM marts.mart_renewal_2026").df()

    quantiles = renewal.required_rate_change.quantile([0.1, 0.5, 0.9])
    insufficient = (renewal.sufficiency_index < 1).mean()
    additional = (renewal.technical_premium_annual_uf - renewal.current_premium_annual_uf).sum()
    current_total = renewal.current_premium_annual_uf.sum()

    lr_table = pd.DataFrame(
        {
            "Año": loss_ratio.year.astype(int),
            "Prima devengada (UF)": loss_ratio.premium.map(lambda v: _num(v, 0)),
            "Siniestros (UF)": loss_ratio.claims.map(lambda v: _num(v, 0)),
            "Siniestralidad": loss_ratio.loss_ratio.map(_pct),
        }
    )
    segment_table = pd.DataFrame(
        {
            "Rubro": segments.industry,
            "Prestación": segments.claim_type,
            "Frecuencia 2021": segments.freq_2021.map(lambda v: _num(v, 3)),
            "Frecuencia 2024": segments.freq_2024.map(lambda v: _num(v, 3)),
            "Variación": segments.change.map(_pct),
        }
    )

    text = f"""# Renovación 2026 de seguros colectivos de salud y vida — borrador

{COMPANY_NAME}. Cifras al corte de valoración 31-12-2025. Datos sintéticos calibrados con rangos de mercado.

> Borrador generado automáticamente por el pipeline (fase 1). Las secciones marcadas TODO se completan en la fase 4.

## Siniestralidad por año

{_markdown_table(lr_table)}

La siniestralidad de 2025 está subestimada: incluye solo siniestros pagados al corte (falta el IBNR).

## Segmentos con mayor alza de frecuencia

Variación de la frecuencia (siniestros por año-persona) entre 2021 y 2024, por rubro y tipo de prestación.

{_markdown_table(segment_table)}

## Reajuste requerido 2026

Contratos tarificados: {len(renewal)}. Reajuste requerido (prima técnica / prima vigente − 1):

| Percentil | Reajuste |
|---|---|
| p10 | {_pct(quantiles.loc[0.1])} |
| p50 | {_pct(quantiles.loc[0.5])} |
| p90 | {_pct(quantiles.loc[0.9])} |

{_decomposition_section(decomposition)}
## Suficiencia de prima

- Contratos con prima insuficiente (índice de suficiencia < 1): {_pct(insufficient)}.
- Prima adicional anual si se aplican todos los reajustes requeridos: {_num(additional, 0)} UF
  ({_pct(additional / current_total)} sobre la prima vigente de {_num(current_total, 0)} UF).

## Causas del deterioro

TODO (fase 4): narrativa sobre tendencia de costos, apalancamiento de deducibles, reajustes históricos
insuficientes y segmentos críticos.

## Recomendación

TODO (fase 4): política de reajuste recomendada (uniforme, diferenciada o con tope) con impacto en resultado y retención.

## Riesgos

TODO (fase 4): IBNR, migración Isapre → Fonasa, competencia de la MCC, siniestros catastróficos.
"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text)
    return out_path

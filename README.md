# Renovación y suficiencia de primas en seguros colectivos de salud y vida

Proyecto de portafolio de análisis técnico y financiero de una cartera de seguros colectivos en Chile.
La compañía es ficticia (**Compañía de Seguros Cordillera**) y los datos son sintéticos, calibrados con rangos de mercado.

## Pregunta de negocio

**Para cada contrato colectivo que renueva en 2026, ¿qué reajuste de prima necesita para que la prima sea suficiente,
y cómo queda la cartera si se aplican?**

Contexto: el segmento de seguros colectivos de salud acumula pérdidas operacionales, los costos de siniestros de salud
subieron con fuerza en 2023, y la Ley 21.674 (Ley Corta de Isapres) abre la Modalidad de Cobertura Complementaria de
Fonasa como competidor. Detalle y fuentes en
[docs/superpowers/specs/2026-11-17-renovacion-colectivos-salud-vida-design.md](docs/superpowers/specs/2026-11-17-renovacion-colectivos-salud-vida-design.md).

## Estado

Fase 1 (núcleo end-to-end) completa:

- generador de cartera calibrado;
- warehouse DuckDB con capas staging, intermediate y marts;
- GLM de frecuencia y severidad;
- prima técnica 2026, reajuste requerido y suficiencia por contrato;
- CSV para Tableau;
- borrador de informe.

Pendiente para las fases siguientes: IBNR, credibilidad, escenarios Monte Carlo, Streamlit, dashboard Tableau,
cotizador Excel e informe ejecutivo final.

## Cómo correrlo

```bash
uv sync
```

```bash
uv run python -m colectivos.pipeline --config config/generator.yaml --out data --exports exports
```

El comando:

1. genera unas 300 empresas y 90 mil asegurados con 3 millones de prestaciones (cerca de 1 minuto);
2. construye `data/warehouse.duckdb`;
3. imprime la calibración y la validación fuera de tiempo;
4. escribe los CSV en `exports/tableau/` y el borrador en `data/reports/informe_borrador.md`.

Tests (incluye los estadísticos `slow`):

```bash
uv run pytest
```

## Estructura

```
config/                     parámetros del generador, objetivos de calibración, supuestos de tarificación, mortalidad
src/colectivos/
    generator/              cartera, exposición, siniestros de salud y vida, primas, patrones plantados
    warehouse/              DuckDB: sql/01_staging, 02_intermediate, 03_marts; exportación CSV
    calibration.py          métricas generadas vs rangos objetivo
    models/glm.py           GLM Poisson (frecuencia) y Gamma (severidad), validación A/E
    pricing/                prima técnica, reajuste requerido, suficiencia
    report/draft.py         borrador del informe
    pipeline.py             CLI de un comando
notebooks/01_calidad_datos.ipynb
data/truth/                 verdad del generador (solo para validar, nunca la leen los modelos)
```

## Supuestos importantes

- **Calibración:** los rangos objetivo son supuestos razonados, porque no hay cifra oficial publicada para colectivos de salud. Ver `config/calibration_targets.yaml`.
- **Mortalidad:** tabla Gompertz-Makeham marcada como supuesto, a reemplazar por la TM-2020 oficial. Ver `config/mortality/README.md`.
- **Tarificación:** gastos 12%, comisión 8% y margen 5%, todos supuestos (`config/pricing.yaml`).

## Glosario

| Término | Definición |
|---|---|
| Siniestralidad | Siniestros / prima devengada. Sobre 1 significa que se paga más de lo que se cobra. |
| Frecuencia | Número de siniestros por año-persona expuesto. |
| Severidad | Monto medio reembolsado por siniestro (UF). |
| Exposición (año-persona) | Tiempo asegurado; 12 meses de una persona = 1 año-persona. |
| Prima técnica | Prima que cubre el costo esperado más gastos, comisión y margen: costo / (1 − gastos − comisión − margen). |
| Suficiencia | Prima vigente / prima técnica. Menor a 1 indica prima insuficiente. |
| Reajuste requerido | Prima técnica / prima vigente − 1. |
| IBNR | Siniestros ocurridos y no reportados o no pagados al corte; hacen que el último período se vea mejor de lo que es. |
| A/E | Actual / Expected: siniestros observados sobre esperados por el modelo. |
| Credibilidad | Peso que se le da a la experiencia propia de un grupo frente a la del modelo, según su tamaño (fase 2). |
| GLM | Modelo lineal generalizado; aquí Poisson para frecuencia y Gamma para severidad, con link log. |

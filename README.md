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

Fase 1 (núcleo end-to-end) y Fase 2 (modelo validado) completas:

- generador de cartera calibrado;
- warehouse DuckDB con capas staging, intermediate y marts;
- IBNR por chain-ladder y Cape Cod, con siniestros últimos por contrato y celda;
- tendencia en dos etapas (dentro de cada empresa) y relatividades por segmento con la tendencia como offset;
- validación fuera de tiempo 2025 contra la línea base de la Fase 1 y un retador Tweedie;
- credibilidad Bühlmann-Straub por contrato y recargo por siniestros grandes;
- prima técnica 2026, reajuste requerido, suficiencia y descomposición del reajuste agregado;
- validación contra la verdad del generador (`python -m colectivos.validation`);
- CSV para Tableau y borrador de informe.

Pendiente para las fases siguientes: escenarios Monte Carlo, Streamlit, dashboard Tableau, cotizador Excel e informe
ejecutivo final.

## Cómo correrlo

```bash
uv sync
```

```bash
uv run python -m colectivos.pipeline --config config/generator.yaml --out data --exports exports
```

El comando:

1. genera unas 300 empresas y 90 mil asegurados con 3 millones de prestaciones;
2. construye `data/warehouse.duckdb`;
3. imprime la calibración, el IBNR y la validación fuera de tiempo;
4. reentrena con 2021–2025, aplica credibilidad, tarifica 2026 y descompone el reajuste;
5. escribe los CSV en `exports/tableau/` y el borrador en `data/reports/informe_borrador.md`.

Tarda ~5 minutos a escala full. La validación contra la verdad del generador corre aparte (varios minutos) y escribe
sus tablas en `data/reports/validacion/`:

```bash
uv run python -m colectivos.validation --data data
```

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
    models/                 GLM Fase 1, IBNR, últimos, tendencia (etapa 1), relatividades (etapa 2), Tweedie, validación fuera de tiempo
    pricing/                prima técnica, credibilidad, reajuste requerido, suficiencia
    report/                 borrador del informe y descomposición del reajuste
    validation/             chequeos contra la verdad del generador (CLI aparte)
    pipeline.py             CLI de un comando
notebooks/01_calidad_datos.ipynb
notebooks/02_validacion_modelo.ipynb
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
| Siniestro último | Pagado al corte + IBNR: lo que costará el período cuando se termine de pagar. |
| Chain-ladder | Método de IBNR que proyecta lo pagado con factores de desarrollo observados en orígenes anteriores (aquí trimestrales, ponderados por volumen). |
| Cape Cod | Variante de Bornhuetter-Ferguson: el IBNR de un origen poco desarrollado sale de un a priori (costo por año-persona de los orígenes maduros, con tendencia) y no del pagado. Se usa en el monto de alto costo de 2025. |
| A/E | Actual / Expected: siniestros observados sobre esperados por el modelo. |
| Credibilidad | Peso Z que se le da a la experiencia propia de un contrato frente al modelo, según su tamaño. Bühlmann-Straub: Z = w / (w + k), con k = varianza dentro / varianza entre contratos. |
| Efecto fijo (de empresa) | Un nivel propio por empresa en el GLM de tendencia, para medir la tendencia dentro de cada empresa y no confundirla con la entrada o salida de clientes más o menos riesgosos. |
| Tweedie | Distribución para el costo puro (muchos ceros y montos positivos) en un solo GLM; aquí es el retador del modelo frecuencia × severidad. |
| Gini (de lift) | Qué tan bien ordena un modelo a los contratos por costo: 0 = no ordena, mayor = ordena mejor. |
| GLM | Modelo lineal generalizado; aquí Poisson para frecuencia y Gamma para severidad, con link log. |

# Handoff — Renovación y suficiencia de primas en seguros colectivos de salud y vida

Fecha: 2026-11-17. Para continuar en Claude Code (VS Code) desde este repositorio.

- **Repo:** https://github.com/JulioPradenas/seguros-colectivos-renovacion (público, rama `main`, al día con `origin/main`)
- **Diseño (fuente de verdad):** [docs/superpowers/specs/2026-11-17-renovacion-colectivos-salud-vida-design.md](superpowers/specs/2026-11-17-renovacion-colectivos-salud-vida-design.md)
- **Plan ejecutado (Fase 1):** [docs/superpowers/plans/2026-11-17-fase1-nucleo-end-to-end.md](superpowers/plans/2026-11-17-fase1-nucleo-end-to-end.md)

## 1. Qué es el proyecto

Es un proyecto de portafolio de un data scientist que quiere entrar al dominio de seguros colectivos de salud y vida en Chile.
El encargo se toma de un aviso real de "Analista de Riesgos Técnicos". Este no apunta a un cargo puntual: el aviso sirve como lista de lo que el proyecto tiene que cubrir.

La compañía es ficticia ("Compañía de Seguros Cordillera") y la cartera es sintética, calibrada con rangos de mercado.

**Pregunta central:** para cada contrato colectivo que renueva en 2026, ¿qué reajuste de prima necesita para que la prima sea suficiente, y cómo queda la cartera si se aplican esos reajustes?

**Módulo de escenarios:** el resultado técnico de la cartera bajo cuatro presiones:
- inflación médica alta;
- migración Isapre → Fonasa;
- competencia de la MCC de Fonasa (Ley 21.674), que provoca antiselección;
- siniestros catastróficos.

## 2. Preferencias de trabajo del usuario

- **Idioma y estilo:** español, directo y conciso, sin emojis y sin resumen redundante al final.
- **Ritmo:** al terminar cada task, avisar qué quedó hecho y esperar confirmación antes de la siguiente.
- **Flujo superpowers:**
  - brainstorming → diseño aprobado → `writing-plans` → ejecución.
  - Ejecución "nativa": una sola sesión y TDD estricto (el test se ve fallar antes de implementar).
  - Revisión final de la rama con un revisor independiente.
- **Decisiones sin preguntar:** cuando el implementador decide algo por su cuenta, se anota en el registro de avance (ledger) con el formato `Ruling: decisión — por qué — costo si está mal`. Todas se informan al cerrar.
- **Código:** f-strings, `pathlib`, type hints en `src/`, nombres en inglés.
- **SQL:** keywords en MAYÚSCULAS, 4 espacios de indentación, CTEs en lugar de subqueries anidadas y alias descriptivos.
- **Pedir confirmación antes de:** push, crear PR o cualquier acción externa.
- **Fase 2:** no se ha iniciado. El usuario pidió explícitamente esperar su indicación.

## 3. Cómo correrlo

```bash
uv sync
```

```bash
uv run python -m colectivos.pipeline --config config/generator.yaml --out data --exports exports
```

```bash
uv run pytest
```

- El pipeline tarda ~70 s a escala full. Genera la cartera, construye el warehouse, calibra, ajusta los GLM con validación 2025, tarifica las renovaciones 2026, exporta los CSV a Tableau y escribe el borrador.
- La suite tiene 91 tests y tarda ~30 s. Incluye tests `slow` estadísticos sobre una cartera media de 100 empresas.
- `data/` y `exports/` están en `.gitignore` y se regeneran con el pipeline. Solo se versiona `data/truth/README.md`.

## 4. Qué está hecho (Fase 1 — núcleo end-to-end)

| Componente | Archivos | Qué hace |
|---|---|---|
| Configuración | `config/generator.yaml`, `generator_small.yaml`, `pricing.yaml`, `calibration_targets.yaml`, `mortality/` | Parámetros del generador (todos los supuestos marcados), escala de test de 20 empresas, gastos 12% / comisión 8% / margen 5%, rangos de calibración, tabla de mortalidad |
| Cartera | `src/colectivos/generator/portfolio.py`, `exposure.py` | Empresas (rubro, región, tamaño, alta y fuga), contratos anuales por aniversario (incluida la vigencia 2026), titulares y cargas con rotación, exposición mensual prorrateada por días |
| Siniestros salud | `generator/health_claims.py` | Frecuencia Poisson con relatividades, tendencia, efecto por empresa y estacionalidad; severidad Gamma, lognormal o Pareto; cobertura Isapre/Fonasa; deducible y tope anual por asegurado × tipo × vigencia; desfase de pago |
| Vida, primas, patrones | `generator/life_claims.py`, `premiums.py`, `patterns.py`, `run.py` | Muertes de titulares (cortan la cobertura del titular y sus cargas); prima inicial = costo esperado × 1,18; reajustes históricos; 5 patrones plantados; corte de valoración al 31-12-2025; verdad en `data/truth/` |
| Warehouse | `src/colectivos/warehouse/` (`build.py`, `export.py`, `sql/01_staging`, `02_intermediate`, `03_marts`) | DuckDB con vistas `raw` sobre parquet, segunda barrera del corte, marts y exportación CSV |
| Calibración | `src/colectivos/calibration.py`, `notebooks/01_calidad_datos.ipynb` | 4 métricas contra rangos; notebook de shape, dtypes, nulos, composición, frecuencia, severidad y siniestralidad |
| Modelos | `src/colectivos/models/glm.py` | GLM Poisson (frecuencia, offset log-exposición) y Gamma (severidad) por tipo; los niveles sin siniestros se fusionan con el nivel base; alto costo sin segmentar; A/E fuera de tiempo 2025 |
| Tarificación | `src/colectivos/pricing/technical_premium.py` | Prima técnica 2026, reajuste requerido, suficiencia y bandera de baja exposición; escribe `marts.mart_renewal_2026` |
| Reporte y CLI | `src/colectivos/report/draft.py`, `pipeline.py`, `README.md` | Borrador con cifras en `data/reports/informe_borrador.md`; README con glosario |

**Marts exportados** a `exports/tableau/`:
- `mart_loss_ratio_contract_year`
- `mart_model_cells`
- `mart_kpi_monthly`
- `mart_payment_triangle`
- `mart_renewal_2026`

**Patrones plantados** (detalle en `data/truth/patterns.json`):

| Patrón | Qué hace |
|---|---|
| `industry_hospital_trend` | Construcción, hospitalaria: frecuencia ×1,08 por año |
| `adverse_selection` | Asegurados que entran desde 2023 en empresas chicas: frecuencia ×1,6 |
| `catastrophic_event` | Un siniestro de 8.000 UF en 2023 |
| `inadequate_rate_changes` | 15% de los contratos sin reajuste |
| `fonasa_shift` | Proporción Fonasa ×1,6 en las altas desde 2024 |

### Cifras actuales (escala full, tras la recalibración)

**Calibración** (todas dentro de rango):

| Métrica | Valor |
|---|---|
| Siniestralidad de salud 2021–2024 | 0,755 (rango 0,75–0,95) |
| Costo por año-persona | 9,23 UF |
| Tendencia de severidad | 6,0% |
| Proporción Fonasa en 2021 | 20% |

**Siniestralidad total por año:**

| 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| 0,74 | 0,785 | 0,807 | 0,829 | 0,716 |

2025 está subestimado por IBNR.

**Validación y tarificación:**
- **A/E 2025:** bajo 1 en todos los tipos, por IBNR. Va de ~0,62 en alto costo a ~0,95 en farmacia.
- **Reajuste requerido 2026:** p10 −5,8%, mediana +45%, p90 +150%.
- **Contratos con prima insuficiente:** 84%.
- **Hallazgo:** construcción / hospitalaria aparece como el segmento con mayor alza de frecuencia. Es el patrón plantado, detectado sin pistas.

## 5. Decisiones y supuestos relevantes

- **Mortalidad:**
  - Se usa una tabla Gompertz-Makeham **supuesta** (`config/mortality/makeham_supuesto.csv`).
  - La oficial es la TM-2020 (CB-H-2020 / B-M-2020, NCG CMF 495), pero sus qx solo están publicados como imágenes.
  - Para reemplazarla, guardar un CSV `age,sex,qx` y apuntar `mortality_table` del YAML a ese archivo.
- **Calibración:** los 4 objetivos son **rangos supuestos** razonados, porque no se encontró cifra oficial publicada para colectivos de salud. Las fuentes cualitativas están en el YAML.
- **Recalibración 2026-11-17:**
  - `historic_rate_change` subió de 4% a 7%.
  - `initial_loading` está en 0,18.
  - Con estos supuestos el reajuste mediano tiene un piso cercano a +37%: la brecha de siniestralidad aporta +11%, y la tendencia de ~9% anual durante ~2,5 años aporta el resto.
  - La tendencia ajustada (~9%) es mayor que la del generador por el apalancamiento de deducibles y topes fijos en UF.
- **Rubro en el GLM:** las relatividades por rubro salen infladas (sector público/retail 1,52 contra 1,21 verdadero) porque el efecto aleatorio de empresa se confunde con el rubro. Esto motiva la credibilidad de la Fase 2.
- **Corrección de la revisión final:** `year_c` de tarificación = punto medio de la vigencia − 2023,5, porque el entrenamiento centra cada año calendario a mitad de año.
- **Simplificaciones del generador:**
  - La antiselección no modela un cambio de plan.
  - El catastrófico se paga sin tope.
  - La prima inicial no descuenta deducibles ni topes.
  - Cuando muere el titular, sus cargas también pierden la cobertura.

## 6. Pendientes menores (de la revisión final, sin corregir)

1. Un tramo de edad no visto al entrenar (por ejemplo 70+ en una cartera chica) se tarifica como el más poblado (30-44). Agregar al menos un aviso.
2. El catastrófico de 8.000 UF entra al entrenamiento de alto costo sin tope de siniestro grande. Impacto <0,3%; tratarlo en la Fase 2.
3. Los pagos de 2024 posteriores al corte sesgan levemente a la baja la tendencia de severidad. Declararlo hasta tener IBNR.
4. `10_int_insured_profile_month.sql` y el CTE de `technical_premium.py` suponen un solo `contract_id`/`plan_id` por empresa. Agregar un test de unicidad.
5. `build.py` crea las vistas `raw` con rutas absolutas y toma cualquier parquet viejo de la carpeta.
6. `mart_kpi_monthly.loss_ratio` es una contribución por tipo de prestación. Renombrarla a `loss_ratio_contribution` antes de armar Tableau.

## 7. Qué falta por hacer (según el diseño, sección 6.9)

Cada fase necesita su propio plan con `superpowers:writing-plans` antes de implementarse.

### Fase 2 — modelo validado (semana 3)

- **IBNR:**
  - Chain-ladder sobre `marts.mart_payment_triangle` por tipo de prestación.
  - La siniestralidad que alimenta la tarificación debe usar siniestros últimos, no solo los pagados.
  - Validar contra `data/truth/health_claims_full.parquet`.
- **Credibilidad Bühlmann-Straub:** combinar la experiencia propia del grupo con la predicción del GLM según su exposición. Usarla en `price_renewals` en vez del GLM puro.
- **Retador:** LightGBM o un GLM Tweedie contra el GLM base, con validación fuera de tiempo (entrenar 2021–2024, probar 2025), devianza, lift/Gini y A/E por segmento.
- **Validación contra la verdad (`data/truth/`):** recuperación de relatividades, detección de los 5 patrones y error del IBNR.
- **Decisiones del spec ya tomadas:**
  - El A/E se calcula contra el modelo; la comparación contra la tarifa va aparte, como suficiencia.
  - El test 2025 usa siniestros últimos estimados, con un anexo contra la verdad completa.
- **Decisión abierta:** si se bajan los supuestos de tendencia para que el reajuste mediano quede cerca de +25–35%.

### Fase 3 — escenarios y simulador (semana 4)

- **Palancas de escenario:**
  - inflación médica base, alta o estrés;
  - proporción Fonasa;
  - competencia MCC (no renovación según reajuste y riesgo, con antiselección);
  - frecuencia catastrófica.
- **Monte Carlo** de un año de la cartera renovada: distribución del resultado técnico y de la siniestralidad, P(siniestralidad > umbral) y VaR 95/99.
- **Comparación de políticas:** reajuste uniforme, diferenciado y diferenciado con tope, midiendo resultado, riesgo y retención.
- **App Streamlit** (Community Cloud) con dos vistas: escenarios de cartera y ficha de renovación por empresa. Usa solo parquet resumidos, nunca siniestros línea a línea.

### Fase 4 — portafolio completo (semana 5)

- **Dashboard Tableau Public:** se edita en el navegador desde los CSV de `exports/tableau/`. Debe mostrar KPIs, tendencias, siniestralidad por segmento, alertas A/E y suficiencia.
- **Cotizador Excel:** hoja de supuestos, experiencia del grupo, credibilidad y prima técnica con fórmulas vivas, y sensibilidad.
- **Informe ejecutivo PDF** de 2–3 páginas: completar los TODO del borrador (causas, recomendación de política de reajuste y riesgos).
- **Documento de metodología** y README final con los links a lo publicado.
- **Opcional:** reemplazar la mortalidad supuesta por la TM-2020 oficial y conseguir la estadística por ramo de la CMF para afinar la calibración.

## 8. Cómo retomar en Claude Code

1. Abrir la carpeta del repo en VS Code, ejecutar `uv sync` y luego `uv run pytest` para confirmar el verde.
2. Correr el pipeline para regenerar `data/` y `exports/`, que no están versionados.
3. Pedirle a Claude que lea este archivo, el spec y el plan de la Fase 1.
4. Para la Fase 2: invocar brainstorming si hay que decidir el alcance (por ejemplo la decisión abierta de tendencia), o ir directo a `writing-plans` con la sección 7 de este documento.

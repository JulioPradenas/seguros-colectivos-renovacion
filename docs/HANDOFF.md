# Handoff — Renovación y suficiencia de primas en seguros colectivos de salud y vida

Fecha: 2026-11-17. Para continuar en Claude Code (VS Code) desde este repositorio.

- **Repo:** https://github.com/JulioPradenas/seguros-colectivos-renovacion (público, rama `main`, al día con `origin/main`)
- **Diseño (fuente de verdad):** [docs/superpowers/specs/2026-11-17-renovacion-colectivos-salud-vida-design.md](superpowers/specs/2026-11-17-renovacion-colectivos-salud-vida-design.md)
- **Plan ejecutado (Fase 1):** [docs/superpowers/plans/2026-11-17-fase1-nucleo-end-to-end.md](superpowers/plans/2026-11-17-fase1-nucleo-end-to-end.md)
- **Diseño Fase 2 (aprobado):** [docs/superpowers/specs/2026-11-17-fase2-modelo-validado-design.md](superpowers/specs/2026-11-17-fase2-modelo-validado-design.md)
- **Plan Fase 2 (aprobado, en ejecución):** [docs/superpowers/plans/2026-11-17-fase2-modelo-validado.md](superpowers/plans/2026-11-17-fase2-modelo-validado.md)

## 0. Dónde estamos (retomar aquí)

Actualizado el 2026-11-17.

- **Rama:** `fase-2`, creada desde `main` (797e341). **Sin push**: pedir confirmación antes de hacerlo.
- **Commits de la rama:**

| Commit | Qué es |
|---|---|
| `eccb7a7` | Recalibración (tendencias reales en UF, reajuste histórico de 4% real) y arreglo del bug del deducible (año de calentamiento) |
| `8a8822f` | Diseño de la Fase 2 |
| `b5dc478` | Plan de la Fase 2 (14 tasks) |
| `1cd0650` | **Task 1 completa:** configuración de la Fase 2 en `pricing.yaml` y `PricingConfig` |

- **Siguiente paso:** la **Task 2** del plan, marts `mart_development_quarterly`, `mart_model_cells_company` y `mart_large_losses`. Quedan las Tasks 2 a 14.
- **Modo de ejecución:** "nativo" con `superpowers:executing-plans`: una sola sesión y TDD estricto (el test se ve fallar antes de implementar). Al cerrar cada task se avisa y **se espera confirmación** antes de la siguiente. Al final, una revisión independiente de la rama completa.
- **Ledger de ejecución:** `.superpowers/sdd/2026-11-17-fase2-modelo-validado/progress.md`.
  - Está en `.gitignore`: existe solo en este equipo.
  - Si se pierde, las tasks completas se deducen de `git log` (un commit `feat:` por task, con el mensaje del plan).
  - Contiene el pre-flight y esta decisión, que hay que respetar al llegar a la Task 10: `Ruling: en T10 se adapta pipeline.py mínimamente (BaselineModel de Fase 1 + CredibilityResult neutro + load 0), para que la suite siga verde; T12 lo reemplaza por el flujo completo`.
- **Cómo retomar en una sesión nueva:**
  1. `git checkout fase-2 && uv sync && uv run pytest`. Expected: 95 passed.
  2. Si no existe `data/`, correr el pipeline (sección 3).
  3. Pedir a Claude que lea este archivo, el spec y el plan de la Fase 2.
  4. Seguir con `superpowers:executing-plans` desde la Task 2. El script `task-start` del skill recrea el brief de cada task en el workspace.
- **Puntos de parada definidos en el plan:**
  - Si el retador Tweedie gana con claridad, o si un hallazgo de validación no tiene explicación técnica, se para y se muestra al autor.
  - Los criterios de éxito son hallazgos, no compuertas.

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
- **Fase 2:** en ejecución (ver sección 0).
- **Hallazgos sin explicar:** si aparece algo que no se explica, parar y mostrárselo antes de seguir. No ajustar supuestos para que un número "se vea bien": todo cambio necesita una razón técnica.

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
- La suite tiene 95 tests (en la rama `fase-2`) y tarda ~30 s. Incluye tests `slow` estadísticos sobre una cartera media de 100 empresas.
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

### Cifras actuales (escala full, rama `fase-2` tras el commit `eccb7a7`; el modelo es todavía el de la Fase 1)

**Calibración** (todas dentro de rango):

| Métrica | Valor |
|---|---|
| Siniestralidad de salud 2021–2024 | 0,765 (rango 0,75–0,95) |
| Costo por año-persona | 8,90 UF (rango 6–12) |
| Tendencia de severidad (real, en UF) | 3,0% (rango 1–5%) |
| Proporción Fonasa en 2021 | 20% (rango 15–30%) |

**Siniestralidad de salud por año:**

| 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| 0,737 | 0,763 | 0,786 | 0,772 | 0,681 |

2025 está subestimado por IBNR.

**Validación y tarificación:**
- **A/E de frecuencia 2025:** bajo 1 en todos los tipos, por IBNR. Va de ~0,60 en alto costo a ~0,985 en farmacia.
- **Reajuste requerido 2026:**
  - agregado de la cartera +19,7%;
  - por contrato: p10 −13%, mediana +28%, p90 +123%;
  - contratos con prima insuficiente: 78%.
- **Descomposición multiplicativa del agregado** (año de referencia 2024; cierra exacto con TP/CP = 1,1967):

| Factor | Multiplicador |
|---|---|
| Brecha de siniestralidad (0,771 contra 0,75) | ×1,028 |
| Ajuste del GLM | ×0,991 |
| Perfil de los vigentes (edad, Fonasa) | ×1,032 |
| **Tendencia a la vigencia 2026 (~6,1% anual)** | **×1,157** |
| Vida | ×1,043 |
| Prima por persona | ×0,943 |

- **Mediana mayor que el agregado:** el reajuste por contrato está dominado por el efecto empresa, que el GLM ignora (correlación −0,90). La credibilidad de la Fase 2 lo corrige.
- **Hallazgo:** construcción / hospitalaria aparece como el segmento con mayor alza de frecuencia. Es el patrón plantado, detectado sin pistas.

## 5. Decisiones y supuestos relevantes

- **Mortalidad:**
  - Se usa una tabla Gompertz-Makeham **supuesta** (`config/mortality/makeham_supuesto.csv`).
  - La oficial es la TM-2020 (CB-H-2020 / B-M-2020, NCG CMF 495), pero sus qx solo están publicados como imágenes.
  - Para reemplazarla, guardar un CSV `age,sex,qx` y apuntar `mortality_table` del YAML a ese archivo.
- **Calibración:** los 4 objetivos son **rangos supuestos** razonados, porque no se encontró cifra oficial publicada para colectivos de salud. Las fuentes cualitativas están en el YAML.
- **Recalibración técnica 2026-11-17 (commit `eccb7a7`):**
  - **`annual_trend`** pasó a tendencia **real en UF**: ambulatoria 2,5%, hospitalaria 3,5%, dental 2%, farmacia 2,5% y alto costo 4%. Las severidades ya están en UF, indexadas a IPC; el 4–8% anterior implicaba IPC+4–8%.
  - **Objetivo `health_severity_trend`:** pasó a 1–5% real (antes 4–9%, que contaba el IPC dos veces).
  - **`historic_rate_change`** volvió a 4% real. El 7% compensaba la tendencia inflada.
  - **`initial_loading`** sigue en 0,18.
- **Bug corregido (mismo commit):** las vigencias en curso al 1-1-2021 reiniciaban el deducible y el tope ese día, porque no se simulaba 2020. Eso deprimía ~6% la frecuencia y el costo de 2021, e inflaba la tendencia 2021–2024 en ~2 puntos al año. Ahora `generate_health_claims` simula un año de calentamiento (2020) que solo consume deducibles y topes, y lo descarta. En el calentamiento no se aplican los patrones plantados (multiplicador 1).
- **Tendencia que queda (~6,1% contra ~4% del generador):**
  - ~1,8% anual viene del **mix de efecto empresa**: en 2024 entran clientes más riesgosos (efecto promedio 1,00 → 1,05) y el GLM, sin efecto empresa, lo extrapola como tendencia.
  - El resto es apalancamiento real de deducibles y topes fijos en UF.
  - La Fase 2 lo corrige con la tendencia estimada dentro de cada empresa (etapa 1).
- **Decisión abierta de tendencia de la Fase 1:** cerrada con lo anterior.
- **Rubro en el GLM:** las relatividades por rubro salen infladas (sector público/retail 1,52 contra 1,21 verdadero) porque el efecto aleatorio de empresa se confunde con el rubro. Esto motiva la credibilidad de la Fase 2.
- **Corrección de la revisión final:** `year_c` de tarificación = punto medio de la vigencia − 2023,5, porque el entrenamiento centra cada año calendario a mitad de año.
- **Simplificaciones del generador:**
  - La antiselección no modela un cambio de plan.
  - El catastrófico se paga sin tope.
  - La prima inicial no descuenta deducibles ni topes.
  - Cuando muere el titular, sus cargas también pierden la cobertura.

## 6. Pendientes menores (de la revisión final de la Fase 1)

El plan de la Fase 2 incluye el #1 (Task 10), el #2 (umbral de siniestro grande, Tasks 2, 5, 6 y 9), el #3 (IBNR, Tasks 3 y 4) y el #4 (Task 2). El #5 y el #6 quedan para la Fase 4.

1. Un tramo de edad no visto al entrenar (por ejemplo 70+ en una cartera chica) se tarifica como el más poblado (30-44). Agregar al menos un aviso.
2. El catastrófico de 8.000 UF entra al entrenamiento de alto costo sin tope de siniestro grande. Impacto <0,3%; tratarlo en la Fase 2.
3. Los pagos de 2024 posteriores al corte sesgan levemente a la baja la tendencia de severidad. Declararlo hasta tener IBNR.
4. `10_int_insured_profile_month.sql` y el CTE de `technical_premium.py` suponen un solo `contract_id`/`plan_id` por empresa. Agregar un test de unicidad.
5. `build.py` crea las vistas `raw` con rutas absolutas y toma cualquier parquet viejo de la carpeta.
6. `mart_kpi_monthly.loss_ratio` es una contribución por tipo de prestación. Renombrarla a `loss_ratio_contribution` antes de armar Tableau.

## 7. Qué falta por hacer (según el diseño, sección 6.9)

Cada fase necesita su propio plan con `superpowers:writing-plans` antes de implementarse.

### Fase 2 — modelo validado (semana 3) — en ejecución

El diseño y el plan aprobados están enlazados al inicio y reemplazan el resumen de abajo, que queda como referencia. Enfoque elegido: tendencia en dos etapas (efecto fijo por empresa), relatividades con la tendencia como offset, reentrenamiento 2021–2025 en siniestros últimos, Bühlmann-Straub encima y un GLM Tweedie como retador.

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
- **Decisión de tendencia:** resuelta. Ver sección 5, recalibración técnica.

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

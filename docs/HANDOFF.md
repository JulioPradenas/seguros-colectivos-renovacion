# Handoff — Renovación y suficiencia de primas en seguros colectivos de salud y vida

Fecha: 2026-11-18. Para continuar en Claude Code (VS Code) desde este repositorio.

- **Repo:** https://github.com/JulioPradenas/seguros-colectivos-renovacion (público, rama `main`, al día con `origin/main`)
- **Diseño (fuente de verdad):** [docs/superpowers/specs/2026-11-17-renovacion-colectivos-salud-vida-design.md](superpowers/specs/2026-11-17-renovacion-colectivos-salud-vida-design.md)
- **Plan ejecutado (Fase 1):** [docs/superpowers/plans/2026-11-17-fase1-nucleo-end-to-end.md](superpowers/plans/2026-11-17-fase1-nucleo-end-to-end.md)
- **Diseño Fase 2 (aprobado):** [docs/superpowers/specs/2026-11-17-fase2-modelo-validado-design.md](superpowers/specs/2026-11-17-fase2-modelo-validado-design.md)
- **Plan Fase 2 (ejecutado):** [docs/superpowers/plans/2026-11-17-fase2-modelo-validado.md](superpowers/plans/2026-11-17-fase2-modelo-validado.md)

## 0. Dónde estamos (retomar aquí)

Actualizado el 2026-11-18.

- **Rama:** `fase-2`, creada desde `main` (797e341). **Sin push**: pedir confirmación antes de hacerlo.
- **Fase 2 implementada completa** (14 tasks del plan, un commit `feat:` por task más un `fix:` y un `test:`).
- **Revisión final hecha:** revisor independiente, "With fixes"; los 3 Important y 3 Minor re-graduados quedaron
  corregidos con tests RED→GREEN. Los Minor diferidos están en el ledger (`Final: minor (deferred)`).
- **Siguiente paso:** `superpowers:finishing-a-development-branch` (merge a `main` / PR, con confirmación del autor).
- **Ledger de ejecución:** `.superpowers/sdd/2026-11-17-fase2-modelo-validado/progress.md` (en `.gitignore`, solo en
  este equipo). Contiene todas las decisiones `Ruling:` y los hallazgos con cifras; hay que informarlas al cerrar.
- **Cómo retomar en una sesión nueva:**
  1. `git checkout fase-2 && uv sync && uv run pytest`. Expected: 159 passed.
  2. Si no existe `data/`, correr el pipeline y la validación (sección 3).
  3. Pedir a Claude que lea este archivo, el spec y el plan de la Fase 2, y el ledger.

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
- **Ritmo:** desde el 2026-11-18, ejecutar las tasks de corrido; parar solo por los puntos de parada del plan o si el autor lo pide.
- **Flujo superpowers:**
  - brainstorming → diseño aprobado → `writing-plans` → ejecución.
  - Ejecución "nativa": una sola sesión y TDD estricto (el test se ve fallar antes de implementar).
  - Revisión final de la rama con un revisor independiente.
- **Decisiones sin preguntar:** cuando el implementador decide algo por su cuenta, se anota en el registro de avance (ledger) con el formato `Ruling: decisión — por qué — costo si está mal`. Todas se informan al cerrar.
- **Código:** f-strings, `pathlib`, type hints en `src/`, nombres en inglés.
- **SQL:** keywords en MAYÚSCULAS, 4 espacios de indentación, CTEs en lugar de subqueries anidadas y alias descriptivos.
- **Pedir confirmación antes de:** push, crear PR o cualquier acción externa.
- **Fase 2:** implementada; falta la revisión final de la rama (ver sección 0).
- **Hallazgos sin explicar:** si aparece algo que no se explica, parar y mostrárselo antes de seguir. No ajustar supuestos para que un número "se vea bien": todo cambio necesita una razón técnica.

## 3. Cómo correrlo

```bash
uv sync
```

```bash
uv run python -m colectivos.pipeline --config config/generator.yaml --out data --exports exports
```

```bash
uv run python -m colectivos.validation --data data
```

```bash
uv run pytest
```

- El pipeline tarda ~5 min a escala full (~200 s son el reentrenamiento 2021–2025 de dos etapas, con 300 efectos fijos
  de empresa). Genera la cartera, construye el warehouse, calibra, estima el IBNR, valida fuera de tiempo (línea base,
  dos etapas y Tweedie), reentrena, aplica credibilidad, tarifica 2026, descompone el reajuste, exporta los CSV y
  escribe el borrador.
- La validación contra la verdad corre aparte (varios minutos) y escribe `data/reports/validacion/*.csv`. El notebook
  `notebooks/02_validacion_modelo.ipynb` lee esas tablas y los marts.
- La suite tiene 159 tests y tarda ~1 min. Incluye tests `slow` estadísticos sobre una cartera media de 100 empresas.
- `data/` y `exports/` están en `.gitignore` y se regeneran con el pipeline. Solo se versiona `data/truth/README.md`.

## 4. Qué está hecho

### Fase 1 — núcleo end-to-end

| Componente | Archivos | Qué hace |
|---|---|---|
| Configuración | `config/generator.yaml`, `generator_small.yaml`, `pricing.yaml`, `calibration_targets.yaml`, `mortality/` | Parámetros del generador (todos los supuestos marcados), escala de test de 20 empresas, gastos 12% / comisión 8% / margen 5%, rangos de calibración, tabla de mortalidad |
| Cartera | `src/colectivos/generator/` | Empresas, contratos, asegurados, exposición, siniestros de salud y vida, primas, 5 patrones plantados, verdad en `data/truth/` |
| Warehouse | `src/colectivos/warehouse/` | DuckDB con vistas `raw`, segunda barrera del corte, marts y exportación CSV |
| Calibración | `src/colectivos/calibration.py`, `notebooks/01_calidad_datos.ipynb` | 4 métricas contra rangos |
| GLM Fase 1 | `src/colectivos/models/glm.py` | Poisson/Gamma con tendencia como covariable; queda como línea base de la validación fuera de tiempo |
| Reporte y CLI | `src/colectivos/report/draft.py`, `pipeline.py` | Borrador del informe y pipeline de un comando |

### Fase 2 — modelo validado

| Componente | Archivos | Qué hace |
|---|---|---|
| Marts nuevos | `warehouse/sql/03_marts/50_*`, `60_*`, `70_*` | Desarrollo trimestral, celdas por empresa × trimestre (monto total y limitado), siniestros grandes (umbral 1500 UF) |
| IBNR | `models/ibnr.py`, `models/ultimates.py` | Chain-ladder trimestral (monto, monto limitado, número; cola = 1); Cape Cod para el monto limitado de alto costo en los 4 últimos trimestres; últimos por celda; `mart_ibnr` |
| Etapa 1: tendencia | `models/trend.py` | Poisson/Gamma con efecto fijo por empresa (alto costo sin él); prueba LR de tendencia adicional por rubro en hospitalaria |
| Etapa 2: relatividades | `models/two_stage.py` | GLM sin año, con la tendencia de la etapa 1 como offset; aviso de nivel no visto |
| Retador | `models/tweedie.py` | GLM Tweedie de costo puro, potencia por verosimilitud perfilada |
| Validación fuera de tiempo | `models/oot.py` | Línea base, dos etapas y Tweedie, 2021–2024 → 2025: A/E y devianza por tipo, A/E por segmento, Gini y RMSE por contrato; `mart_oot_*` |
| Credibilidad | `pricing/credibility.py` | Bühlmann-Straub sobre el A/E por contrato y año; recargo por siniestros grandes |
| Tarificación | `pricing/technical_premium.py` | Modelo 2021–2025 × F + recargo; columnas nuevas en `mart_renewal_2026` |
| Descomposición | `report/decomposition.py` | 7 factores que telescopean a prima técnica / prima vigente; `mart_rate_change_decomposition` y sección del borrador |
| Validación contra la verdad | `validation/` (`python -m colectivos.validation`), `notebooks/02_validacion_modelo.ipynb` | Error del IBNR, tendencia, relatividades, 5 patrones, ganancia de credibilidad, anexo fuera de tiempo contra la verdad |

**Marts exportados** a `exports/tableau/`: `mart_loss_ratio_contract_year`, `mart_model_cells`, `mart_kpi_monthly`,
`mart_payment_triangle`, `mart_renewal_2026`, `mart_development_quarterly`, `mart_model_cells_company` (662 mil filas),
`mart_large_losses`, `mart_ibnr`, `mart_oot_by_type`, `mart_oot_by_segment`, `mart_oot_contract`,
`mart_oot_contract_predictions`, `mart_oot_gini_bootstrap`, `mart_contract_experience` (siniestros pagados y últimos
por contrato × año × tipo, con el esperado del modelo) y `mart_rate_change_decomposition`.

**Patrones plantados** (detalle en `data/truth/patterns.json`):

| Patrón | Qué hace |
|---|---|
| `industry_hospital_trend` | Construcción, hospitalaria: frecuencia ×1,08 por año |
| `adverse_selection` | Asegurados que entran desde 2023 en empresas chicas: frecuencia ×1,6 |
| `catastrophic_event` | Un siniestro de 8.000 UF en 2023 |
| `inadequate_rate_changes` | 15% de los contratos sin reajuste |
| `fonasa_shift` | Proporción Fonasa ×1,6 en las altas desde 2024 |

### Cifras actuales (escala full, rama `fase-2`)

**Calibración** (todas dentro de rango): siniestralidad de salud 2021–2024 0,765; costo por año-persona 8,90 UF;
tendencia de severidad real 3,0%; proporción Fonasa 2021 20%.

**IBNR:** 80.443 UF en los orígenes 2025 (2.780 en 2024). Contra la verdad: −1,7% en 2025 (alto costo −0,9%,
hospitalaria −4,7%, el resto entre +1,5% y +4,6%).

**Tendencia de costo (frecuencia × severidad), 2021–2024, contra el generador:**

| Tipo | Fase 1 | Dos etapas | Generador |
|---|---|---|---|
| Ambulatoria | 6,5% | 4,2% | 3,5% |
| Hospitalaria | 6,4% | 4,6% | 4,5% |
| Dental | 4,4% | 2,1% | 2,0% |
| Farmacia | 6,2% | 3,8% | 3,5% |
| Alto costo | 6,2% | 4,0% | 6,1% |

Alto costo queda bajo el generador porque el tope anual de 1500 UF amortigua la severidad. Con 2021–2025 (modelo que
tarifica): hospitalaria 3,1% más 5,0% adicional en construcción (detectado, p = 0,0009); alto costo 7,3% (2025 fue un
año alto en la verdad).

**Validación fuera de tiempo 2025** (A/E de costo limitado último, por contrato):

| Modelo | A/E | Gini | RMSE por año-persona |
|---|---|---|---|
| Línea base (Fase 1) | 1,004 | 0,034 | 4,49 |
| Dos etapas | 1,058 | 0,035 | 4,51 |
| Tweedie | 1,055 | 0,044 | 4,49 |

- El ~6% que subestiman dos etapas y Tweedie es mix de empresas: el efecto empresa medio pasa de ~1,00 (2021–2023) a
  1,058 en 2025. La línea base acierta en total solo porque su tendencia inflada (6,1%) lo absorbe.
- El Tweedie **no gana con claridad**: diferencia de Gini +0,0075 con IC bootstrap 90% [−0,0009; 0,0189] y A/E por
  segmento igual o peor. Tarifica el modelo de dos etapas (regla 5.5 del spec).

**Credibilidad:** k = 298 UF de costo esperado; Z mediana 0,94; corr(log F, log efecto empresa verdadero) = 0,92.
La correlación entre el reajuste requerido y el efecto empresa verdadero queda en +0,03 (Fase 1: −0,90).
Con modelo y credibilidad de 2021–2024, el RMSE por año-persona contra la verdad de 2025 baja de 4,66 a 2,01 y el A/E
pasa de 1,061 a 0,995. Recargo por siniestros grandes: 0,42%.

**Relatividades:** sector público / retail = 1,22 (verdadero 1,21; Fase 1 1,52). Edad, sexo, rol, previsión y región
cerca de la verdad.

**Patrones:** 5 de 5 detectados con criterios que no miran la verdad.

**Reajuste requerido 2026** (245 contratos):

| | Fase 1 | Fase 2 |
|---|---|---|
| Agregado | +19,7% | +17,6% |
| p10 | −13% | −5,5% |
| Mediana | +28% | +15,9% |
| p90 | +123% | +44,4% |
| Contratos con prima insuficiente | 78% | 84% |

**Descomposición del agregado** (año de referencia 2025, en últimos):

| Factor | Multiplicador |
|---|---|
| Brecha de siniestralidad | ×1,055 |
| Ajuste del modelo | ×0,955 |
| Perfil | ×1,021 |
| Tendencia | ×1,059 |
| Credibilidad y siniestros grandes | ×1,048 |
| Vida | ×1,044 |
| Prima por persona | ×0,986 |

"Ajuste del modelo" y "Credibilidad" son el mismo fenómeno: los clientes de 2025 son más riesgosos que el promedio de
entrenamiento, el modelo sin efecto empresa no lo ve y la credibilidad lo devuelve contrato a contrato.

## 5. Decisiones y supuestos relevantes

- **Mortalidad:** tabla Gompertz-Makeham **supuesta** (`config/mortality/makeham_supuesto.csv`). La oficial es la
  TM-2020 (NCG CMF 495), publicada solo como imágenes. Para reemplazarla, guardar un CSV `age,sex,qx` y apuntar
  `mortality_table` del YAML a ese archivo.
- **Calibración:** los 4 objetivos son rangos supuestos razonados; las fuentes cualitativas están en el YAML.
- **Recalibración 2026-11-17 (commit `eccb7a7`):** tendencias reales en UF, reajuste histórico de 4% real y año de
  calentamiento (2020) que solo consume deducibles y topes.
- **Supuestos de la Fase 2** (`config/pricing.yaml`): umbral de siniestro grande 1500 UF; año de referencia 2025;
  entrenamiento fuera de tiempo 2021–2024 y final 2021–2025; Cape Cod solo en alto costo, 4 trimestres; interacción por
  rubro probada solo en hospitalaria (α = 0,05); grilla Tweedie 1,3–1,7.
- **Decisiones de implementación de la Fase 2:** están todas en el ledger como `Ruling:`. Las de más peso:
  - En Cape Cod, el IBNR de conteo se reparte por exposición igual que el monto (si no, la severidad 2025 de alto costo
    caía de 205 a 135 UF).
  - La tendencia adicional por rubro se mide contra el resto de la cartera, no contra un rubro de referencia.
  - Los criterios de detección de patrones son umbrales del autor de la implementación; la evidencia queda impresa.
  - `experience_ae` es NaN para un contrato sin experiencia (Z = 0, F = center).
- **Simplificaciones del generador:** la antiselección no modela un cambio de plan; el catastrófico se paga sin tope;
  la prima inicial no descuenta deducibles ni topes; cuando muere el titular, sus cargas pierden la cobertura.

## 6. Pendientes menores

De la revisión final de la Fase 1 quedan el #5 y el #6 para la Fase 4 (los #1 a #4 se cerraron en la Fase 2):

5. `build.py` crea las vistas `raw` con rutas absolutas y toma cualquier parquet viejo de la carpeta.
6. `mart_kpi_monthly.loss_ratio` es una contribución por tipo de prestación. Renombrarla a `loss_ratio_contribution`
   antes de armar Tableau.

Nuevos de la Fase 2:

7. El conteo último de alto costo 2025 queda −10% (casi todo en 2025-T4, ruido de pocos siniestros con un factor de
   7,4). Afecta el reparto frecuencia/severidad de alto costo, no su costo puro.
8. El pipeline pasó de ~70 s a ~5 min. Si molesta, el reentrenamiento con efecto fijo por empresa es el candidato a
   optimizar (por ejemplo, absorbiendo el efecto empresa con un GLM de efectos fijos por demeaning).
9. El borrador del informe aún dice que la siniestralidad 2025 está subestimada por IBNR; ahora hay `mart_ibnr` para
   mostrarla en últimos (Fase 4).

## 7. Qué falta por hacer (según el diseño, sección 6.9)

Cada fase necesita su propio plan con `superpowers:writing-plans` antes de implementarse.

### Fase 3 — escenarios y simulador (semana 4)

- **Palancas de escenario:** inflación médica base, alta o estrés; proporción Fonasa; competencia MCC (no renovación
  según reajuste y riesgo, con antiselección); frecuencia catastrófica.
- **Monte Carlo** de un año de la cartera renovada: distribución del resultado técnico y de la siniestralidad,
  P(siniestralidad > umbral) y VaR 95/99.
- **Comparación de políticas:** reajuste uniforme, diferenciado y diferenciado con tope, midiendo resultado, riesgo y
  retención.
- **App Streamlit** (Community Cloud) con dos vistas: escenarios de cartera y ficha de renovación por empresa. Usa solo
  parquet resumidos, nunca siniestros línea a línea.

### Fase 4 — portafolio completo (semana 5)

- **Dashboard Tableau Public** desde los CSV de `exports/tableau/`: KPIs, tendencias, siniestralidad por segmento,
  alertas A/E y suficiencia.
- **Cotizador Excel:** supuestos, experiencia del grupo, credibilidad y prima técnica con fórmulas vivas, y
  sensibilidad.
- **Informe ejecutivo PDF** de 2–3 páginas: completar los TODO del borrador.
- **Documento de metodología** y README final con los links a lo publicado.
- **Opcional:** TM-2020 oficial y estadística por ramo de la CMF.

## 8. Cómo retomar en Claude Code

1. Abrir la carpeta del repo en VS Code, ejecutar `uv sync` y luego `uv run pytest` para confirmar el verde.
2. Correr el pipeline para regenerar `data/` y `exports/`, que no están versionados.
3. Pedirle a Claude que lea este archivo, el spec y el plan de la Fase 1.
4. Para la Fase 2: invocar brainstorming si hay que decidir el alcance (por ejemplo la decisión abierta de tendencia), o ir directo a `writing-plans` con la sección 7 de este documento.

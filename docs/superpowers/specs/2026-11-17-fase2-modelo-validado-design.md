# Diseño Fase 2: modelo validado (IBNR, tendencia en dos etapas, credibilidad, retador)

Fecha: 2026-11-17. Rama: `fase-2`. Complementa el diseño general
[2026-11-17-renovacion-colectivos-salud-vida-design.md](2026-11-17-renovacion-colectivos-salud-vida-design.md) (secciones 6.6 y 6.9),
que sigue siendo la fuente de verdad del proyecto.

## 1. Intención y por qué

La Fase 1 entrega una prima técnica 2026 por contrato, pero con tres debilidades que un lector de la industria
detectaría de inmediato:

- **Usa siniestros pagados, no últimos.** 2025 (y en parte 2024) está subestimado por IBNR.
- **La tendencia está contaminada por el mix de empresas.** El GLM no tiene efecto empresa. En 2024 entran clientes más
  riesgosos (efecto empresa promedio 1,00 → 1,05), y el GLM lo lee como tendencia y lo extrapola a 2026. Tendencia ajustada
  ~6,1% anual contra ~4% del generador.
- **Ignora la experiencia propia de cada grupo.** El reajuste por contrato está dominado por el efecto empresa que el GLM
  no ve (correlación −0,90 entre el reajuste requerido y el efecto verdadero). Una empresa de bajo riesgo aparece muy
  subtarificada, y una de alto riesgo, sobretarificada.

La Fase 2 corrige las tres y **demuestra** que el modelo funciona: valida contra los datos al corte, como en la práctica,
y contra la verdad del generador (`data/truth/`), que en la práctica no existe.

**Éxito:** un actuario que lea la ficha de un contrato entiende de dónde sale su reajuste (siniestros últimos,
tendencia limpia, segmento y experiencia propia ponderada por credibilidad) y puede comprobar que cada pieza está validada.

## 2. Objetivos, no objetivos y anti-objetivos

**Objetivos**

1. IBNR por chain-ladder (y Bornhuetter-Ferguson donde corresponda), con siniestros últimos por tipo, trimestre de
   ocurrencia y contrato.
2. Tendencia estimada dentro de cada empresa (etapa 1), separada de las relatividades de segmento (etapa 2).
3. Validación fuera de tiempo (entrenamiento 2021–2024, prueba 2025 en siniestros últimos) del modelo campeón contra el
   GLM de la Fase 1 y contra un retador.
4. Reentrenamiento del modelo de tarificación con 2021–2025 en siniestros últimos.
5. Credibilidad Bühlmann-Straub por contrato sobre la experiencia en siniestros últimos.
6. Prima técnica 2026 con todo lo anterior, y descomposición del reajuste agregado como parte del reporte.
7. Validación contra `truth/`: error del IBNR, recuperación de tendencia y relatividades, detección de los 5 patrones
   plantados y mejora de la credibilidad.

**No objetivos (fases posteriores)**

- Escenarios, Monte Carlo y app (Fase 3). Dashboard, cotizador Excel e informe final (Fase 4).
- LightGBM. Queda como retador opcional solo si sobra tiempo; el retador de esta fase es el GLM Tweedie.
- Credibilidad en vida. El costo de vida sigue siendo qx × capital.
- IBNR de vida.

**Anti-objetivos (fracaso aunque el código funcione)**

- Que el pipeline de tarificación lea `data/truth/` en cualquier paso. La verdad se usa **solo** en validación.
- Que el IBNR use información posterior al corte del 31-12-2025.
- Que la tendencia proyectada siga absorbiendo cambios de mix de empresas.
- Ajustar supuestos para que el reajuste "se vea bien". Toda cifra que cambie se explica por una razón técnica.
- Una credibilidad que deje entrar el catastrófico de 8.000 UF completo a la experiencia de su contrato.

## 3. Restricciones

- Mismo stack: DuckDB (SQL en capas `staging` → `intermediate` → `marts`), pandas y statsmodels. Sin dependencias nuevas,
  salvo que el retador las requiera (Tweedie está en statsmodels).
- Estilo SQL del proyecto: keywords en mayúsculas, 4 espacios, CTEs y alias descriptivos.
- Python: f-strings, `pathlib` y type hints en `src/`.
- TDD estricto: cada función nueva tiene su test, que se ve fallar antes de implementar.
- El pipeline completo debería seguir corriendo en pocos minutos a escala full (hoy ~70 s).
- Los tests estadísticos `slow` usan la cartera media de 100 empresas, como en la Fase 1.

## 4. Enfoques considerados

| Enfoque | Qué es | A favor | En contra |
|---|---|---|---|
| A. Mínimo según el spec | GLM 2021–2024 sobre pagados; IBNR solo para la validación 2025 y la experiencia por contrato; credibilidad encima | Rápido | La tendencia sigue inflada (~6%) y la credibilidad no lo corrige, porque es un sesgo de toda la cartera |
| **B. Dos etapas + reentrenamiento (elegido)** | Tendencia con efecto fijo por empresa; GLM de relatividades con la tendencia como offset; reentrenamiento 2021–2025 en siniestros últimos; Bühlmann-Straub encima | Separa tendencia, segmento y empresa; es la práctica actuarial estándar; es defendible ante un lector del rubro | Más trabajo; el reentrenamiento con 2025 depende de la calidad del IBNR |
| C. GLMM con efecto aleatorio por empresa | Un solo modelo mixto | Resuelve tendencia y credibilidad de una vez | statsmodels lo soporta mal para Poisson/Gamma; se aleja del Bühlmann-Straub que pide el aviso |

**Elegido por el autor: B.**

## 5. Diseño

### 5.1 IBNR

**Datos.** Un mart nuevo, `marts.mart_development_quarterly`: por tipo de prestación, **trimestre de ocurrencia** y
trimestre de desarrollo (0 = el mismo trimestre de ocurrencia), con el **monto pagado acumulado y el número de siniestros
pagados acumulado**. La grilla llega hasta el trimestre de valoración. El mart anual actual (`mart_payment_triangle`)
se mantiene para Tableau.

Por qué trimestral: con origen anual, el último trimestre de 2025 (muy poco desarrollado) se diluye en el año. Además,
el trimestre permite pasar el desarrollo a cada contrato con más precisión.

**Método.**

- Chain-ladder con factores de desarrollo ponderados por volumen, por tipo y por separado para monto y número.
- Factor de cola = 1: el triángulo tiene hasta 20 trimestres de desarrollo y los desfases del generador se agotan mucho
  antes. Se verifica en un test que los últimos factores observados sean ≈ 1.
- **Alto costo, orígenes de 2025: Cape Cod** (Bornhuetter-Ferguson con a priori sacado del propio triángulo).
  El a priori es el costo último por año-persona de los orígenes maduros (2021–2024), llevado a cada trimestre de 2025 por
  la tendencia observada en esos mismos orígenes y multiplicado por la exposición del trimestre. Motivos:
  - Alto costo es volátil, y el catastrófico de diciembre de 2023 distorsiona los factores tempranos.
  - El a priori **no depende de ningún modelo**, así que el A/E 2025 de la validación fuera de tiempo no queda acercado a 1
    por construcción, y el IBNR puede correr antes que los modelos.
  - Los siniestros sobre el umbral de siniestro grande (5.7) se limitan antes de estimar el a priori.
- El conteo de alto costo usa chain-ladder; el número de siniestros es mucho más estable que el monto.

**Salidas.**

- `marts.mart_ibnr`: tipo, trimestre de ocurrencia, pagado, último, IBNR, método y factor de desarrollo a último.
  Se exporta a Tableau.
- Siniestros últimos por **contrato × tipo × trimestre de ocurrencia**. Alimentan la base de modelamiento de 2025 y la
  credibilidad.
  - Tipos con chain-ladder: pagado del contrato × factor de desarrollo a último (CDF) de la cartera para ese tipo y
    trimestre, en monto y en número.
  - Monto de alto costo con Cape Cod: pagado del contrato + IBNR de la cartera del trimestre **repartido según la
    exposición del contrato** en ese trimestre. Así, un contrato sin pagos no queda en 0 y un siniestro temprano no se
    multiplica. Se reparte por exposición y no por costo esperado para no depender del modelo.

**Validación (con `truth/`, solo en la etapa de validación).** IBNR estimado contra el verdadero
(`health_claims_full` menos lo pagado al corte), por tipo y trimestre: error absoluto y relativo, y error total de la
cartera.

### 5.2 Base de modelamiento con empresa y siniestros últimos

- Un mart nuevo, `marts.mart_model_cells_company`: igual que `mart_model_cells` pero con `company_id` y con
  `n_claims_ultimate` y `reimbursed_uf_ultimate` además de los pagados.
- Para 2021–2024 el último ≈ pagado (salvo la cola pequeña de hospitalaria y alto costo en 2024). Para 2025, el
  último sale de 5.1.
- El paso a último por celda se hace con los CDF por tipo × trimestre aplicados a lo pagado en cada trimestre de la celda.
  El conteo último puede ser fraccionario; el GLM Poisson lo acepta.
- `mart_model_cells` (sin empresa) se mantiene para Tableau y para el GLM de la Fase 1, que es la línea base.

### 5.3 Etapa 1: tendencia dentro de cada empresa

Por tipo de prestación:

- **Frecuencia:** Poisson, `n_claims ~ C(company_id) + C(age_band) + C(sex) + C(role) + C(health_system) + year_c`,
  con offset log(exposición). Rubro y región quedan fuera porque son constantes dentro de cada empresa (colineales con
  el efecto fijo).
- **Severidad:** Gamma con link log y las mismas variables.
- **Alto costo, en frecuencia y en severidad:** sin efecto fijo de empresa. Con una frecuencia de ~0,004 por persona,
  la mayoría de las empresas no tiene siniestros y sus efectos fijos se irían a −∞. Se usan solo `year_c` y los factores
  de persona sobre la cartera, y la severidad con siniestros limitados al umbral de siniestro grande (5.7).
- La tendencia del tipo = exp(coeficiente de `year_c`) de frecuencia × la de severidad.
- **Tendencia por rubro en hospitalaria:** el spec general dice que la tarificación captura la tendencia plantada solo si el
  análisis la detecta. La etapa 1 de hospitalaria prueba una interacción rubro × `year_c`. Las interacciones
  significativas (prueba de razón de verosimilitud contra el modelo sin interacción, al 5%) **se mantienen y se proyectan
  a 2026** para ese rubro. Las que no lo son se descartan. No se prueban interacciones en los demás tipos, para no salir
  a pescar.
- **Antiselección:** no se agrega una variable de cohorte de ingreso. La antiselección se detecta en la validación (5.9) y
  se captura por contrato vía credibilidad (5.7). Su efecto en la tendencia de la cartera es pequeño (10 empresas
  chicas), y se reporta.

**Validación:** tendencia estimada por tipo contra `frequency_trend` y `annual_trend` del generador. Lo esperado es que la
tendencia de costo de la cartera quede en ~4–5% (la del generador más el apalancamiento de deducibles), no en ~6%.

**Hallazgo esperado, que se documenta:** el ~1,8% anual que la Fase 1 atribuía a tendencia es cambio de mix de empresas.

### 5.4 Etapa 2: relatividades de segmento

- Los mismos GLM de frecuencia y severidad de la Fase 1, **sin `year_c`** y con offset adicional
  `year_c × log(1 + tendencia de la etapa 1)`, por tipo.
- Factores: los 6 de la Fase 1, incluidos rubro y región.
- Se mantienen la fusión de niveles sin siniestros y la severidad sin segmentar en alto costo.

### 5.5 Validación fuera de tiempo y retador

**Modelos comparados**, todos entrenados en 2021–2024 y probados en 2025 en siniestros últimos estimados:

1. **Línea base:** el GLM de la Fase 1 (tendencia en el mismo GLM).
2. **Campeón:** el modelo de dos etapas (5.3 + 5.4).
3. **Retador:** GLM Tweedie sobre costo puro por celda (costo / exposición, con la exposición como peso), con los
   mismos factores y la misma tendencia de etapa 1 como offset. La potencia de la varianza se elige por perfil de
   verosimilitud en una grilla (por ejemplo, 1,3–1,7).

**Métricas:**

- A/E de costo y de frecuencia por tipo, y por segmento (rubro, tramo de edad, previsión, tamaño de empresa).
- Devianza (Poisson para frecuencia, Gamma para severidad y Tweedie para el costo puro, cada una en su modelo).
- Lift y Gini sobre el costo por contrato en 2025.
- **Anexo:** las mismas métricas contra la verdad completa de 2025, para medir cuánto error aporta el IBNR.

**Regla de decisión:** el campeón es el modelo de tarificación, salvo que el retador gane con claridad en A/E por
segmento y en Gini. Si gana, se documenta y se discute antes de cambiar.

### 5.6 Reentrenamiento para tarificar

Validado el campeón, se reentrenan las etapas 1 y 2 con 2021–2025 en siniestros últimos. Ese modelo tarifica.
La proyección a 2026 sigue usando el punto medio de cada vigencia (`projection_year_c`).

### 5.7 Credibilidad Bühlmann-Straub

- **Unidad:** el contrato (una empresa = un contrato).
- **Observaciones:** años 2021–2025 de cada contrato. X_cy = costo último de salud observado / costo esperado por el
  modelo reentrenado (el A/E del contrato en el año). Peso w_cy = costo esperado del modelo en ese año.
- **Siniestros grandes**, con el mismo umbral en todas partes:
  - Cada siniestro se limita al umbral en el **entrenamiento** de la severidad (etapas 1 y 2, y el retador), en la
    **experiencia** de credibilidad y en el a priori Cape Cod.
  - El exceso sobre el umbral, en siniestros últimos de 2021–2025, se convierte en un recargo por siniestros grandes:
    exceso total / costo esperado limitado total. Se aplica a todos los contratos, proporcional a su costo esperado.
  - Así el exceso se cuenta una sola vez y queda resuelto el pendiente #2 (el catastrófico de 8.000 UF).
- **Estimación:** estimadores no paramétricos estándar de Bühlmann-Straub para la varianza dentro de cada contrato (s²) y
  entre contratos (a). k = s² / a, Z_c = W_c / (W_c + k), con W_c = Σ_y w_cy. Si â ≤ 0, Z = 0 para todos y se informa.
- **Factor de experiencia:** F_c = Z_c × X̄_c + (1 − Z_c) × 1, con X̄_c = el promedio ponderado de X_cy.
  1 es el centro del colectivo, porque el modelo está balanceado. Se verifica que el A/E de la cartera sea ≈ 1 y, si no,
  se usa el A/E de la cartera como centro.
- **Experiencia de cada año:** cada X_cy se trae al nivel de costo de 2026 a través del esperado del modelo, que ya
  incluye tendencia y perfil del año. No se aplica un factor de tendencia adicional.
- **Costo esperado de salud 2026** = esperado del modelo reentrenado × F_c + recargo por siniestros grandes.

**Validación con `truth/`:**

- Correlación entre F_c y el efecto empresa verdadero (`truth/company_effects.parquet`).
- Error del costo de salud 2025 por contrato, con y sin credibilidad: modelo y credibilidad estimados con 2021–2024,
  contra el **costo realizado completo** de 2025 en `truth/health_claims_full.parquet` (reembolsado, con los siniestros
  limitados al umbral). Se mide con RMSE ponderado por exposición y con el A/E.
- **No se usa `truth/expected_cost.parquet`**, porque suma vida e ignora deducible y tope. No es comparable con el costo
  de salud reembolsado que predice el modelo, y no se cambia el generador para esto.
- Lo esperado: la credibilidad reduce el error por contrato frente al modelo solo, y la correlación del reajuste requerido
  con el efecto empresa baja claramente de −0,90.

### 5.8 Prima técnica, reajuste y descomposición

- `price_renewals` usa el modelo reentrenado, la tendencia de etapa 1, F_c y el recargo por siniestros grandes.
- `marts.mart_renewal_2026` agrega estas columnas: `expected_health_cost_model_uf`, `experience_ae`, `credibility_z`,
  `credibility_factor` y `large_loss_load_uf`. Se mantienen las columnas actuales.
- **Descomposición del reajuste agregado**, sobre los contratos que renuevan. Es una identidad que telescopea, así que los
  factores multiplicados dan exactamente TP/CP. El orden está fijado en la definición: el perfil se mide en el año de
  referencia y la tendencia sobre el perfil vigente.

  Notación:
  - Año de referencia R = 2025, en siniestros últimos.
  - C_R: costo de salud observado en R.
  - P_R: prima devengada en R.
  - n_R: años-persona de exposición en R.
  - M_R(hist): esperado del modelo sobre la exposición de R.
  - M_R(vig): esperado del modelo sobre los vigentes al corte, con edad al punto medio de la vigencia y al nivel de R.
  - M_26(vig): esperado del modelo sobre los vigentes al corte, proyectado al punto medio de la vigencia 2026.
  - n_vig: número de vigentes.
  - F: factor de credibilidad agregado = Σ(M_26 × F_c) / Σ M_26.
  - LL: recargo por siniestros grandes.
  - L: costo de vida.
  - CP: prima vigente anualizada.
  - 0,75 = 1 − gastos − comisión − margen.

  | Factor | Definición |
  |---|---|
  | Brecha de siniestralidad | (C_R / P_R) / 0,75 |
  | Ajuste del modelo | M_R(hist) / C_R |
  | Perfil | (M_R(vig) / n_vig) / (M_R(hist) / n_R) |
  | Tendencia | M_26(vig) / M_R(vig) |
  | Credibilidad y siniestros grandes | (M_26 × F + LL) / M_26 |
  | Vida | (salud 2026 + L) / salud 2026 |
  | Prima por persona | (P_R / n_R) / (CP / n_vig) |

  El análisis exploratorio que lo originó (año de referencia 2024, sin credibilidad) dio +19,7% agregado, con la tendencia
  como factor dominante (×1,157). Las cifras están en el mensaje del commit `eccb7a7`. Va al borrador del informe, y su
  test verifica que el producto de los factores sea igual a TP/CP.
- **Pendiente #1 incluido:** aviso (warning en el log y columna `unseen_level_flag`) cuando un contrato tiene un nivel de
  factor no visto en el entrenamiento.
- **Pendiente #4 incluido:** test de unicidad, un `contract_id`/`plan_id` por empresa, en los SQL que lo suponen.

### 5.9 Validación contra la verdad

Un módulo `src/colectivos/validation/` con funciones testeadas que **solo se llaman desde el notebook y desde un paso de
validación separado del pipeline de tarificación**:

- Error del IBNR (5.1).
- Tendencia recuperada contra la del generador (5.3).
- Relatividades recuperadas (etapa 2) contra `truth/parameters.json`. El sesgo de rubro de la Fase 1 (sector público
  1,52 contra 1,21 verdadero) viene de que el efecto empresa se confunde con el rubro. La etapa 2 sigue sin efecto
  empresa, así que **no se espera que se corrija**. Se reporta como hallazgo, y como motivo de que la credibilidad sea
  necesaria.
- Detección de los 5 patrones, cada uno con un criterio explícito:

| Patrón | Cómo se detecta sin mirar la verdad | Éxito |
|---|---|---|
| `industry_hospital_trend` | Tendencia de frecuencia hospitalaria por rubro (interacción rubro × año en etapa 1) | Construcción aparece con la mayor tendencia y significativa |
| `adverse_selection` | A/E por cohorte de ingreso (≥ 2023) en empresas chicas | A/E de esa cohorte claramente > 1 en las empresas plantadas |
| `catastrophic_event` | Reporte de siniestros sobre el umbral de siniestro grande | El de 8.000 UF de 2023 aparece y queda fuera de la experiencia |
| `inadequate_rate_changes` | Suficiencia por contrato contra historia de reajustes aplicados | Los contratos sin reajuste se concentran en la cola alta del reajuste requerido |
| `fonasa_shift` | Proporción Fonasa por año de ingreso | Salto desde las altas de 2024 |

- Mejora de la credibilidad (5.7).

**Entregable de lectura:** `notebooks/02_validacion_modelo.ipynb`, con las tablas y gráficos de todo lo anterior.

**Los criterios de éxito son hallazgos, no compuertas.** Ningún resultado se ajusta para que pase su criterio
(anti-objetivo). Cuando un resultado no cumple lo esperado:

- Si tiene una explicación técnica verificada, se documenta y se sigue.
- Si no se explica, el builder **para y se lo muestra al autor** antes de seguir. Esta es la regla que el autor aplicó en
  la recalibración previa.

El plan no incluye tareas de iteración de modelo.

### 5.10 Pipeline

Pasos nuevos o cambiados en `colectivos.pipeline`, en orden:

1. Generar.
2. Warehouse, con los marts nuevos `mart_development_quarterly` y `mart_model_cells_company`.
3. Calibración.
4. IBNR → `mart_ibnr` y siniestros últimos por contrato y por celda.
5. Validación fuera de tiempo: línea base, campeón y retador en 2025 (se imprime la tabla).
6. Reentrenamiento 2021–2025 y credibilidad.
7. Tarificación 2026 y descomposición.
8. Exportar y escribir el borrador.

La validación contra `truth/` **no** corre en el pipeline de tarificación. Va en un comando separado
(`python -m colectivos.validation`) y en el notebook.

## 6. Decisiones del autor

- Enfoque B (sección 4).
- Recalibración previa: tendencias reales en UF, reajuste histórico de 4% real y año de calentamiento del deducible
  (commit `eccb7a7`).
- Del spec general: el A/E se calcula contra el modelo, y la suficiencia contra la tarifa va aparte. El test 2025 usa
  siniestros últimos estimados, con un anexo contra la verdad completa.

## 7. Decisiones de Claude (el autor las puede cambiar)

- IBNR con origen trimestral, chain-ladder en monto y número y cola = 1. Cape Cod solo para el monto de alto costo en
  2025, con un a priori del propio triángulo (sin modelo, sin circularidad) y su IBNR repartido por exposición.
- Etapa 1: alto costo sin efecto fijo de empresa en frecuencia ni en severidad. Interacción rubro × año probada solo en
  hospitalaria, y proyectada a 2026 si es significativa. Sin variable de cohorte de antiselección.
- Un solo umbral de siniestro grande para el entrenamiento, la experiencia y el a priori, con el exceso como recargo
  aparte.
- Validación de la credibilidad contra el costo realizado completo de 2025 (`health_claims_full`), no contra
  `expected_cost.parquet`.
- Descomposición del reajuste con año de referencia 2025, en siniestros últimos.
- Retador: GLM Tweedie, no LightGBM.
- Credibilidad sobre el A/E del contrato, con peso = costo esperado y centro = 1 (verificado).
- Siniestros grandes limitados en la experiencia y repartidos en toda la cartera.
- Se incluyen los pendientes #1, #2, #3 y #4. Los #5 (rutas absolutas en `build.py`) y #6 (renombrar `loss_ratio` del KPI)
  quedan para la Fase 4.

## 8. Lo que queda para el builder

- Nombres exactos de módulos y funciones, y si el IBNR va en SQL, en Python o mixto (los triángulos en SQL y el método
  en Python es lo natural).
- El valor del umbral de siniestro grande. Debe documentarse en `pricing.yaml` con su razón; por ejemplo, un percentil
  alto de la severidad de alto costo, por encima del umbral Pareto de 300 UF.
- La grilla de potencias Tweedie y la forma de las curvas de lift.
- Cómo se marca y se reporta un trimestre con poco desarrollo, más allá de usar BF en alto costo.
- La estructura del notebook 02.

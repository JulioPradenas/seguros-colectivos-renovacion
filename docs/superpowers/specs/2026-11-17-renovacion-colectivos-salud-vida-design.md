# Diseño: Renovación y suficiencia de primas en seguros colectivos de salud y vida

Proyecto de portafolio. Fecha: 2026-11-17.

## 1. Intención y por qué

El autor es data scientist / analista de datos (Python, SQL, pandas, scikit-learn). Quiere:

- Entrar a un dominio que no ha trabajado: seguros colectivos de salud y vida en Chile.
- Responder preguntas de negocio que el mercado chileno se está haciendo hoy, usando el lenguaje de la industria (siniestralidad, suficiencia de prima, IBNR, credibilidad, renovación).
- Dar el paso del análisis de datos al data science: modelos, validación, simulación y proyección, no solo reportes.

El proyecto no apunta a un cargo puntual. Usa como lista de cobertura un aviso real de "Analista de Riesgos Técnicos – Seguros Colectivos de Salud y Vida" (ver sección 9).

**Contexto de mercado que motiva las preguntas** (verificado el 2026-11-17):

- Según la prensa financiera, el segmento de seguros colectivos de salud arrastra pérdidas operacionales desde hace algunos años.
- La Ley 21.674 ("Ley Corta de Isapres", mayo 2024) creó la Modalidad de Cobertura Complementaria (MCC) de Fonasa. Su puesta en marcha se ha retrasado: la primera licitación quedó desierta y en septiembre de 2025 seguían los retrasos.
- La CMF advirtió que las primas tienen que ajustarse al arancel y a la siniestralidad para cubrir los riesgos.

## 2. Pregunta de negocio

**Central (A):** para cada contrato colectivo que se renueva, ¿qué reajuste de prima necesita para que la prima sea suficiente, y cómo queda la cartera completa si se aplican esos reajustes?

**Módulo de escenarios (B):** ¿cómo cambia el resultado técnico de la cartera bajo:

- inflación médica alta;
- un cambio en la mezcla de asegurados por la migración Isapre → Fonasa;
- la MCC como competidor en precio, que haría que los grupos de menor riesgo no renueven (antiselección);
- siniestros catastróficos?

**Preguntas secundarias** que salen del análisis:

- ¿Qué segmentos (rubro, tamaño, región, tipo de prestación) explican el deterioro?
- ¿Qué contratos se desvían de lo esperado (A/E)?
- ¿Cuánto hay de siniestros ocurridos y no reportados (IBNR) en el último período?

## 3. Metas, no-metas y anti-metas

**Metas**

- Un recorrido reproducible de punta a punta: un comando genera los datos, construye las tablas, entrena los modelos, calcula los reajustes, corre los escenarios y exporta lo que usan Tableau, Streamlit y Excel.
- Los modelos recuperan los parámetros verdaderos del generador. Esto se muestra explícitamente como validación.
- Entregables para tres audiencias:
  - técnica: README y documento de metodología;
  - de gestión: dashboard en Tableau y simulador en Streamlit;
  - de comité: informe ejecutivo y cotizador en Excel.
- Lenguaje y supuestos coherentes con la práctica chilena: UF, prestaciones reembolsadas sobre la cobertura de Isapre o Fonasa, y vida colectiva como capital asegurado.

**No-metas**

- No es un modelo actuarial regulatorio (no calcula reservas técnicas normativas CMF ni capital basado en riesgo).
- No usa datos reales de ninguna compañía.
- No es un producto en producción: sin autenticación, sin orquestador, sin nube.
- No hay deep learning. scikit-learn y LightGBM alcanzan.

**Anti-metas** (cosas que harían fracasar el proyecto aunque funcione técnicamente)

- Que los datos se vean artificiales: distribuciones sin ceros, sin colas pesadas, sin estacionalidad, todo con forma de campana.
- Que el hallazgo sea circular sin decirlo. Los patrones plantados tienen que declararse como diseño de validación.
- Que haya números de mercado inventados presentados como reales. Toda cifra de calibración cita su fuente CMF, INE o Superintendencia; si no hay fuente, se rotula como supuesto.
- Que haya jerga sin explicación. Cada término técnico se define una vez en el glosario del README.
- Que el informe ejecutivo sea un volcado de gráficos en vez de recomendaciones con números.
- Usar el nombre o la marca de una aseguradora real. La compañía es ficticia: "Compañía de Seguros Cordillera (ficticia)".

## 4. Restricciones

- Hardware: un solo laptop (macOS). Todo local, salvo lo que se publica.
- Herramientas decididas por el autor:
  - DuckDB como base;
  - Python para generar datos, modelar y simular;
  - SQL en DuckDB para transformar;
  - Tableau Public, editado desde el navegador (no está instalado Tableau Desktop);
  - Streamlit para el simulador;
  - Excel para el cotizador.
- Tableau Public solo lee archivos (CSV o Excel). El pipeline exporta tablas resumidas a CSV.
- Todo es público (Tableau Public, Streamlit Community Cloud, GitHub). Los datos son sintéticos, así que no hay problema.
- Tiempo: unas 8 horas diarias. El total estimado es de 4 a 5 semanas.
- Preferencias de código del autor:
  - f-strings, `pathlib`, type hints en el código compartido, nombres en inglés;
  - SQL con keywords en mayúsculas, 4 espacios de indentación, CTEs antes que subqueries y alias descriptivos;
  - revisar nulls, dtypes y shape antes de analizar.

## 5. Enfoques considerados

**Origen de los datos (lo decidió el autor: opción 1)**

1. **Simulación propia calibrada con la CMF (elegida).** Control total del contexto chileno. Se conocen los parámetros verdaderos, así que se puede validar si el modelo los recupera. También se pueden plantar patrones para que el análisis los encuentre. Riesgos: que los datos se vean artificiales y que el proyecto parezca circular. Se mitigan con ruido realista y declarando la validación.
2. Microdatos de salud de EE.UU. (MEPS) reescalados. Las distribuciones son reales, pero el sistema de salud no corresponde al chileno y la estructura de empresas habría que inventarla igual. Se descartó.
3. Solo agregados públicos de la CMF. No permiten tarificar contrato por contrato ni hacer machine learning. Se descartó.

**Herramientas (las decidió el autor)**

- **Base de datos:** DuckDB, en vez de BigQuery o Supabase. Como el dashboard es Tableau y lee archivos, no se necesita base en la nube.
- **Dashboard:** Tableau Public (web), en vez de Looker Studio. El aviso nombra Tableau y no requiere instalación.
- **Simulador:** Streamlit, en vez de Shiny for Python, Dash o marimo. Es más rápido de construir y se publica gratis.

**Alcance de producto (lo decidió el autor)**

Salud complementaria es el foco del modelamiento. Vida colectiva es un componente acotado: su costo esperado sale de mortalidad por tabla y se suma a la prima del paquete.

## 6. Diseño

### 6.1 Escenario ficticio

- **La compañía:** "Compañía de Seguros Cordillera (ficticia)" vende seguros colectivos a empresas.
- **Producto:** paquete de salud complementaria (reembolso de prestaciones sobre la cobertura de Isapre o Fonasa) más vida colectiva (capital fijo en UF por titular).
- **Período observado:** enero 2021 a diciembre 2025, con valoración al 31-12-2025.
- **Tarea:** tarificar las renovaciones de 2026.
- **Moneda:** UF. Se usa la serie histórica real de la UF para convertir a CLP cuando haga falta mostrar pesos.

### 6.2 Escala objetivo

- Del orden de 300 empresas y 50.000 a 80.000 asegurados (titulares más cargas).
- Del orden de 1 a 3 millones de líneas de prestaciones en 5 años.

Basta para justificar "grandes volúmenes" y DuckDB, y cabe en un laptop. El builder ajusta la escala si el tiempo de generación lo exige.

### 6.3 Modelo de datos (tablas crudas que produce el generador)

| Tabla | Grano | Columnas clave |
|---|---|---|
| `companies` | empresa | rubro, tamaño, región, fecha de inicio como cliente |
| `contracts` | contrato × vigencia anual | plan (porcentaje de reembolso, deducible y tope por tipo de prestación), prima mensual UF por titular y por carga, capital de vida UF, gastos, comisión del corredor, reajuste aplicado |
| `insureds` | asegurado | titular o carga, sexo, fecha de nacimiento, previsión (Isapre o Fonasa), fechas de alta y baja |
| `exposure_monthly` | asegurado × mes | meses expuestos y edad al mes |
| `health_claims` | línea de prestación | fecha de ocurrencia, fecha de reporte o pago, tipo de prestación (ambulatoria, hospitalaria, dental, farmacia, alto costo), monto presentado, monto cubierto por la previsión, monto reembolsado por el seguro |
| `life_claims` | fallecimiento | fecha y capital pagado |
| `premiums_monthly` | contrato × mes | prima devengada |

Además, el generador guarda aparte los parámetros verdaderos (`truth/`): relatividades, tendencias y la lista de patrones plantados. Los modelos no los ven; solo se usan en la validación.

### 6.4 Generador

Todos los parámetros van en un archivo de configuración versionado (YAML) con semilla fija.

**Frecuencia**

- Poisson por asegurado × mes × tipo de prestación.
- Relatividades por edad, sexo, previsión, rubro y región, más estacionalidad (por ejemplo, invierno en las respiratorias).
- Un efecto aleatorio por empresa que genera heterogeneidad entre grupos. Es lo que hace que la credibilidad tenga sentido.

**Severidad**

- Gamma o lognormal por tipo de prestación.
- Cola de alto costo con distribución Pareto.

**Reembolso**

- El monto presentado menos lo que cubre la previsión, multiplicado por el porcentaje de reembolso del plan, con deducible y tope.
- La cobertura de la previsión es distinta para Isapre y para Fonasa en la Modalidad de Libre Elección (MLE).

**Desfase**

- Un retardo entre la ocurrencia y el pago, con una distribución por tipo de prestación.
- Con esto los triángulos de desarrollo y el IBNR son reales: en los datos al 31-12-2025, lo ocurrido en el último período está incompleto.

**Inflación médica**

- Una tendencia anual en la severidad, calibrada con el IPC de salud del INE o con estadísticas de la Superintendencia de Salud.

**Mortalidad (vida)**

- Probabilidad de muerte por edad y sexo, tomada de una tabla de mortalidad oficial publicada por la CMF, con un recargo por grupo. El builder verifica qué tabla vigente corresponde.

**Dinámica de cartera**

- Altas y bajas de asegurados, empresas que no renuevan, empresas nuevas y reajustes históricos aplicados en cada renovación.

**Calibración**

- Los niveles agregados se ajustan a los informes y estadísticas de la CMF para el ramo colectivo de salud y vida: siniestralidad (siniestros sobre prima), costo por asegurado y tendencia.
- Si una cifra no se encuentra, se documenta como supuesto y se marca así.
- Un notebook de calibración compara lo generado contra los objetivos.

**Patrones plantados** (documentados en `truth/`, para que el análisis los detecte)

1. Un rubro con frecuencia hospitalaria en alza sostenida.
2. Varios grupos chicos con antiselección: entran asegurados de mayor riesgo después de un cambio de plan.
3. Un año con un siniestro catastrófico en un grupo mediano.
4. Contratos con reajustes históricos insuficientes que dejan primas por debajo de la suficiencia.
5. Un aumento en la proporción de asegurados Fonasa en los últimos dos años.

### 6.5 Capa SQL (DuckDB)

Tres capas:

- **staging:** limpieza y tipos;
- **intermediate:** exposición y siniestros a nivel contrato × año × tipo;
- **marts:**
  - siniestralidad por contrato, año y segmento;
  - frecuencia y severidad;
  - triángulos de pago;
  - KPIs mensuales;
  - alertas A/E.

El pipeline exporta los marts que necesita Tableau a CSV, en `exports/tableau/`.

### 6.6 Análisis y modelos

**Análisis exploratorio y calidad de datos**

- Nulls, dtypes y shape.
- Tendencias y estacionalidad.
- Siniestralidad por segmento.

**IBNR**

- Chain-ladder sobre triángulos de pago por tipo de prestación, para obtener el siniestro último de los períodos recientes.
- La siniestralidad que alimenta la tarificación usa siniestros últimos, no solo los pagados.
- Validación: se compara contra los siniestros verdaderos del generador, que se conocen completos.

**Frecuencia y severidad**

- Un GLM Poisson con offset log(exposición) y un GLM Gamma, por tipo de prestación (statsmodels).
- Un GLM Tweedie o LightGBM como retador.

**Validación**

- Fuera de tiempo: entrenar con 2021–2024 y probar con 2025.
- Métricas: devianza, lift / Gini y A/E por segmento.
- Recuperación de relatividades contra `truth/`.

**Credibilidad**

- Bühlmann-Straub para combinar la experiencia propia de cada grupo con la predicción del modelo, según exposición.

**Prima técnica por contrato para 2026**

- Costo esperado de salud = modelo ponderado por credibilidad, llevado a la vigencia 2026 con la tendencia de inflación médica.
- Costo esperado de vida = Σ qx × capital.
- Prima técnica = (costo salud + costo vida) / (1 − gastos − comisión − margen objetivo).
- Gastos, comisión y margen son supuestos documentados con valores plausibles.

**Reajuste y suficiencia**

- Reajuste requerido = prima técnica / prima vigente − 1.
- Índice de suficiencia por contrato y para la cartera.

### 6.7 Escenarios y Monte Carlo (módulo B)

**Palancas**

- **Inflación médica:** base, alta o estrés.
- **Mezcla de previsión:** la proporción de asegurados Fonasa sube un X%, lo que cambia el monto que cubre la previsión y, con eso, el reembolso.
- **Competencia MCC:** la probabilidad de no renovar depende del reajuste y del riesgo del grupo, con una elasticidad supuesta. Esto genera antiselección, porque se van los grupos buenos.
- **Catastróficos:** frecuencia de la cola.

**Simulación**

- N corridas de un año de siniestros de la cartera renovada.
- Salida: distribución del resultado técnico y de la siniestralidad, P(siniestralidad > umbral) y percentiles (VaR 95/99).

**Comparación de políticas de reajuste**

1. Reajuste uniforme.
2. Reajuste diferenciado según la prima técnica.
3. Diferenciado con tope.

Para cada política se mide el resultado esperado, el riesgo y la retención.

### 6.8 Entregables

1. **Repositorio GitHub:**
   - código en `src/`;
   - notebooks de exploración y validación;
   - un solo comando para reproducir todo;
   - README con la narrativa de negocio, la arquitectura, el glosario y los links a todo lo publicado.
2. **Dashboard Tableau Public, para el monitoreo de cartera:**
   - KPIs: prima, siniestros, siniestralidad, frecuencia y severidad;
   - tendencias;
   - siniestralidad por segmento;
   - alertas A/E por contrato;
   - suficiencia de prima.
3. **App Streamlit**, publicada en Community Cloud, con dos vistas:
   - escenarios de cartera con Monte Carlo y palancas;
   - ficha de renovación por empresa: experiencia, credibilidad, prima técnica y reajuste.
4. **Cotizador de renovación en Excel:**
   - una hoja de supuestos;
   - una hoja de experiencia del grupo;
   - el cálculo de credibilidad y de prima técnica con fórmulas vivas;
   - una sensibilidad del reajuste a la tendencia y al margen.
   El pipeline lo genera con los datos de un contrato de ejemplo.
5. **Informe ejecutivo PDF** de 2 a 3 páginas para un comité técnico-comercial:
   - situación;
   - causas;
   - recomendación de política de reajuste con números;
   - riesgos.
6. **Documento de metodología:** supuestos, fuentes de calibración, validación y limitaciones.

### 6.9 Fases

| Fase | Contenido | Resultado mostrable |
|---|---|---|
| 1 (semanas 1–2) | Generador calibrado, capa SQL, GLM base, prima técnica sin credibilidad y un borrador del informe | Recorrido de punta a punta funcionando |
| 2 (semana 3) | IBNR, credibilidad, retador LightGBM y validación contra `truth/` | Modelo validado |
| 3 (semana 4) | Escenarios, Monte Carlo y app Streamlit | Simulador publicado |
| 4 (semana 5) | Tableau, Excel, informe final, metodología y README | Portafolio completo |

## 7. Lo que queda para el builder

- La estructura exacta de carpetas y módulos. La gestión de entorno (uv, venv) y si se usa make o un script.
- Los valores concretos de relatividades, distribuciones y supuestos (gastos, comisión, margen, elasticidad), siempre que sean plausibles y queden documentados.
- La herramienta para generar el Excel (openpyxl o xlsxwriter) y el PDF.
- El diseño visual del dashboard y de la app.
- La escala final de los datos, dentro del orden de magnitud de 6.2.
- Si los modelos de tipos de prestación con pocos datos se agrupan.

### Decisiones tomadas por Claude tras la revisión (el autor las puede cambiar)

- **Fechas de renovación:** los contratos renuevan en aniversarios repartidos durante el año, no todos en enero. La prima técnica 2026 se proyecta al punto medio de cada vigencia.
- **A/E:** el esperado es el costo que predice el modelo. La comparación contra la tarifa se reporta aparte, como suficiencia.
- **Test fuera de tiempo 2025:** se evalúa contra siniestros últimos estimados (chain-ladder), igual que en la práctica. En un anexo se compara contra los siniestros completos de `truth/`, para medir cuánto error aporta el IBNR.
- **Rubro con tendencia plantada:** la tendencia sigue en 2026 dentro de `truth/` y del Monte Carlo. La tarificación la captura solo si el análisis la detecta (tendencia por rubro).
- **Datos de la app Streamlit:** la app usa archivos parquet resumidos (parámetros de los modelos y experiencia agregada por contrato). Nunca usa siniestros línea a línea.

## 8. Fuentes a usar

- CMF: estadísticas e informes financieros del mercado asegurador (seguros de vida, ramos colectivos de salud y vida) y tablas de mortalidad oficiales.
- INE: IPC de salud.
- Superintendencia de Salud: estadísticas de beneficiarios Isapre/Fonasa y arancel.
- Fonasa: arancel de la MLE.
- Contexto de la MCC y la Ley 21.674: Minsal, La Tercera, BioBioChile y DF (links en el README).

## 9. Cobertura del aviso

| Responsabilidad o requisito del aviso | Dónde se cubre |
|---|---|
| Analizar el desempeño técnico y financiero de carteras | Exploración, marts y dashboard Tableau |
| Proyectar resultados y detectar riesgos y oportunidades | Prima técnica 2026 y Monte Carlo |
| Escenarios, simulaciones y sensibilidad | Módulo B, Streamlit y la sensibilidad del Excel |
| Suficiencia de primas y factores de costo de siniestralidad | Modelos de frecuencia y severidad, credibilidad e índice de suficiencia |
| Detectar tendencias, desviaciones y riesgos | Alertas A/E y patrones plantados detectados |
| Automatizar análisis, reportabilidad y monitoreo | Pipeline de un comando y exportación a Tableau |
| Informes ejecutivos y recomendaciones | Informe PDF |
| Referente técnico | Documento de metodología y glosario |
| SQL, Python, Tableau y Excel avanzado | DuckDB SQL, Python, Tableau Public y cotizador Excel |
| Estadística aplicada y análisis cuantitativo | GLM, credibilidad, chain-ladder y Monte Carlo |
| Análisis de carteras y evaluación de rentabilidad | Resultado técnico por contrato y cartera |
| Presentación a distintos niveles | Tres audiencias: técnica, gestión y comité |

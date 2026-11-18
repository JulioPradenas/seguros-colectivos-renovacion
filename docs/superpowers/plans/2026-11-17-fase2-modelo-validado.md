# Fase 2: Modelo validado — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La prima técnica 2026 por contrato pasa a basarse en lo siguiente, y cada pieza se valida contra los datos al corte y contra `data/truth/`:

- siniestros últimos (IBNR);
- una tendencia estimada dentro de cada empresa;
- relatividades de segmento con esa tendencia como offset;
- credibilidad Bühlmann-Straub por contrato.

**Architecture:** Se extiende el paquete `colectivos` sin reestructurarlo:

- **`warehouse`:** suma marts trimestrales con empresa y siniestros limitados al umbral de siniestro grande.
- **`models`:** suma `ibnr`, `ultimates`, `trend` (etapa 1), `two_stage` (etapa 2), `tweedie` (retador) y `oot` (validación fuera de tiempo).
- **`pricing`:** suma `credibility`.
- **`report`:** suma `decomposition`.
- **`colectivos.validation`:** paquete nuevo y el único que lee `data/truth/`. No lo llama el pipeline de tarificación.

**Tech Stack:** Python 3.12, uv, pandas 3, numpy, duckdb, statsmodels (Poisson, Gamma y Tweedie), pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-11-17-fase2-modelo-validado-design.md`. Complementa el spec general `docs/superpowers/specs/2026-11-17-renovacion-colectivos-salud-vida-design.md`.

## Global Constraints

- Ningún módulo de `models`, `pricing`, `report` ni `pipeline` lee `data/truth/`. Solo `colectivos.validation` y el notebook 02.
- El IBNR usa solo `staging.stg_health_claims` (ya cortado al 31-12-2025), nunca `raw` ni `truth`.
- SQL: keywords en MAYÚSCULAS, 4 espacios, CTEs en vez de subqueries anidadas y alias descriptivos.
- Python: f-strings, `pathlib` y type hints en `src/`. Nombres en inglés y docstrings en español, como el código existente.
- TDD estricto: cada test se ve fallar antes de implementar. Los tests estadísticos de mayor escala llevan `@pytest.mark.slow` y usan `medium_db_path`.
- Los criterios de éxito de la validación son **hallazgos, no compuertas**. Si un resultado no cumple lo esperado y no tiene explicación técnica verificada, se para y se muestra al autor. No hay tareas de iteración de modelo.
- Umbral de siniestro grande: `large_loss_threshold_uf: 1500` en `config/pricing.yaml`. Es igual al tope anual de alto costo del plan básico y deja ~15% del costo esperado de alto costo como exceso, con la Pareto(α = 1,8; umbral 300) del generador.
- Al cerrar cada task, se avisa qué quedó hecho y se espera confirmación antes de la siguiente (preferencia del autor).
- Decisiones tomadas sin preguntar: se anotan en el ledger como `Ruling: decisión — por qué — costo si está mal`.

## Review Focus

1. **Tipo × trimestre sin pagos en el triángulo** (alto costo en un trimestre sin siniestros): el factor de desarrollo no debe dar 0/0. Factor = 1 cuando la suma del denominador es 0, y último = pagado. Test en Task 3.
2. **Empresa sin siniestros de un tipo en la etapa 1** (empresa chica sin dental): su efecto fijo se iría a −∞ y movería la tendencia. Esas empresas se agrupan en un nivel común `__sin_siniestros__`. Test en Task 5.
3. **Contrato con un solo año de experiencia o con costo esperado ~0** (cliente nuevo de 2025): no aporta a s², recibe Z bajo y nunca da NaN. Un contrato sin filas de experiencia queda con F = 1 y Z = 0. Test en Task 9.
4. **â ≤ 0 en Bühlmann-Straub** (cartera homogénea): Z = 0 para todos, con warning en el log y F = centro. Test en Task 9.
5. **Nivel de factor no visto al tarificar** (70+ en una cartera chica): se tarifica con el nivel de respaldo, `unseen_level_flag = True` y warning en el log. Test en Task 10.

---

### Task 1: Configuración de Fase 2

**Files:**
- Modify: `config/pricing.yaml`, `src/colectivos/config.py` (`PricingConfig`, `load_pricing_config`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces, en `PricingConfig`:
  - `large_loss_threshold_uf: float`
  - `reference_year: int` (2025)
  - `train_years_oot: tuple[int, int]` ((2021, 2024))
  - `train_years_final: tuple[int, int]` ((2021, 2025))
  - `cape_cod_claim_types: tuple[str, ...]` (("alto_costo",))
  - `cape_cod_recent_quarters: int` (4)
  - `trend_interaction_claim_types: tuple[str, ...]` (("hospitalaria",))
  - `interaction_alpha: float` (0.05)
  - `tweedie_powers: tuple[float, ...]` ((1.3, 1.4, 1.5, 1.6, 1.7))

- [ ] **Step 1: Write the failing tests** `test_pricing_config_phase2_keys` (carga `config/pricing.yaml` y verifica cada valor de arriba) y `test_pricing_config_rejects_unknown_cape_cod_type` (`ValueError` si `cape_cod_claim_types` o `trend_interaction_claim_types` traen un tipo que no está en `CLAIM_TYPES`).
- [ ] **Step 2:** `uv run pytest tests/test_config.py -v`. Expected: FAIL (faltan los atributos).
- [ ] **Step 3:** Agregar las claves al YAML, cada una con un comentario de supuesto. La del umbral lleva la razón de Global Constraints. Agregar los campos al dataclass: las listas YAML se convierten a tupla y se validan contra `CLAIM_TYPES`.
- [ ] **Step 4:** `uv run pytest tests/test_config.py -v`. Expected: PASS.
- [ ] **Step 5:** `git commit -m "feat: phase 2 pricing config (large loss threshold, IBNR, trend, challenger)"`

### Task 2: Marts de desarrollo trimestral y celdas por empresa

**Files:**
- Modify: `src/colectivos/warehouse/build.py` (nuevo parámetro `large_loss_threshold_uf: float = 1500.0`, expuesto como `SET VARIABLE large_loss_threshold_uf`)
- Create:
  - `src/colectivos/warehouse/sql/03_marts/50_mart_development_quarterly.sql`
  - `src/colectivos/warehouse/sql/03_marts/60_mart_model_cells_company.sql`
  - `src/colectivos/warehouse/sql/03_marts/70_mart_large_losses.sql`
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Produces `marts.mart_development_quarterly`, con columnas:
  - `claim_type`;
  - `origin_quarter` (DATE, primer día del trimestre de ocurrencia);
  - `dev_quarter` (INT, 0 = mismo trimestre);
  - `paid_uf_cum`, `paid_capped_uf_cum`, `n_claims_cum`.

  La grilla es completa hasta el trimestre de la fecha de valoración, con filas en cero incluidas.
- Produces `marts.mart_model_cells_company`, una fila por `(origin_quarter, claim_type, company_id, contract_id, age_band, sex, health_system, role, industry, region)` con `exposure_years > 0`, incluidas las celdas sin siniestros. Columnas extra: `year`, `exposure_years`, `n_claims`, `reimbursed_uf`, `reimbursed_capped_uf`. La exposición del trimestre sale de `intermediate.int_insured_profile_month`, y el siniestro toma el perfil de su mes de ocurrencia, igual que `20_mart_model_cells.sql`.
- Produces `marts.mart_large_losses`: los siniestros con `reimbursed_uf > large_loss_threshold_uf`, con `claim_id`, `company_id`, `contract_id`, `claim_type`, `occurrence_date`, `payment_date`, `reimbursed_uf` y `excess_uf`.
- El monto limitado es `LEAST(reimbursed_uf, getvariable('large_loss_threshold_uf'))`, por siniestro.

- [ ] **Step 1: Write the failing tests** en `tests/test_warehouse.py`:
  - `test_development_quarterly_cumulative_nondecreasing`;
  - `test_development_quarterly_stops_at_valuation`: el máximo de `origin_quarter + dev_quarter` es el trimestre de 2025-12-31;
  - `test_development_quarterly_totals_match_staging`: el último acumulado por tipo es igual a la suma de `stg_health_claims`;
  - `test_model_cells_company_totals_match_model_cells`: exposición, siniestros y monto por `year × claim_type` iguales a `mart_model_cells`;
  - `test_capped_amount_identity`: `reimbursed_uf − reimbursed_capped_uf` sumado es igual a `SUM(excess_uf)` de `mart_large_losses`;
  - `test_one_contract_and_plan_per_company`: `stg_contracts` tiene un solo `contract_id` y un solo `plan_id` por `company_id` (pendiente #4).
- [ ] **Step 2:** `uv run pytest tests/test_warehouse.py -v`. Expected: los tests nuevos fallan con "Table ... does not exist". `test_one_contract_and_plan_per_company` pasa: documenta un supuesto existente.
- [ ] **Step 3:** Escribir los tres SQL y el parámetro de `build_warehouse`. `dev_quarter` = (año pago × 4 + trimestre pago) − (año ocurrencia × 4 + trimestre ocurrencia). La grilla se arma con `GENERATE_SERIES`, como `40_mart_payment_triangle.sql`.
- [ ] **Step 4:** `uv run pytest tests/test_warehouse.py -v`. Expected: PASS.
- [ ] **Step 5:** `git commit -m "feat: quarterly development, company-level model cells and large-loss marts"`

### Task 3: IBNR (chain-ladder y Cape Cod)

**Files:**
- Create: `src/colectivos/models/ibnr.py`
- Test: `tests/test_ibnr.py`

**Interfaces:**
- Produces:
  - `development_factors(triangle: pd.DataFrame, value: str) -> pd.Series`: índice `dev_quarter` (factor de d a d+1), ponderados por volumen. `triangle` tiene columnas `origin_quarter`, `dev_quarter` y `value`, para un solo tipo.
  - `cdf_to_ultimate(factors: pd.Series) -> pd.Series`: índice `dev_quarter`, producto acumulado desde d hasta el final. Cola = 1.
  - `chain_ladder(triangle: pd.DataFrame, value: str) -> pd.DataFrame`: columnas `origin_quarter`, `latest`, `cdf`, `ultimate`, `ibnr`.
  - `cape_cod(triangle: pd.DataFrame, value: str, exposure: pd.Series, recent_quarters: int) -> pd.DataFrame`: mismas columnas más `method`. `exposure` lleva índice `origin_quarter` y está en años-persona.
  - `estimate_ibnr(development: pd.DataFrame, exposure_quarter: pd.DataFrame, cfg: PricingConfig) -> pd.DataFrame`: una fila por `claim_type × origin_quarter`, con `paid_uf`, `ultimate_uf`, `paid_capped_uf`, `ultimate_capped_uf`, `n_paid`, `n_ultimate`, `cdf_amount`, `cdf_capped`, `cdf_count`, `method` (`"chain_ladder"` o `"cape_cod"`) e `ibnr_uf = ultimate_uf − paid_uf`.

Algoritmos que la firma no determina:

```text
LDF_d = Σ_o C(o, d+1) / Σ_o C(o, d), sobre los orígenes con d+1 observado; si Σ_o C(o, d) = 0 → LDF_d = 1.
CDF_d = Π_{k ≥ d} LDF_k; ultimate(o) = latest(o) × CDF_{d_latest(o)}.

Cape Cod (solo para los `recent_quarters` orígenes más recientes del tipo; los anteriores usan chain-ladder):
  pp_o = ultimate_CL(o) / exposure_o para los orígenes maduros (todos menos los recientes);
  ajuste ponderado por exposición de log(pp_o) = α + β·t_o (t_o = índice trimestral);
  a_priori(o) = exp(α + β·t_o) × exposure_o para cada origen reciente;
  ultimate(o) = latest(o) + a_priori(o) × (1 − 1 / CDF_{d_latest(o)}).
```

- [ ] **Step 1: Write the failing tests:**
  - `test_development_factors_volume_weighted`: triángulo 3×3 a mano (orígenes A, B y C, con valores acumulados [100, 150, 165], [200, 290] y [150]). LDF_0 = (150 + 290) / (100 + 200) = 1,4667, LDF_1 = 165/150 = 1,1, último de C = 150 × 1,4667 × 1,1 = 242,0.
  - `test_zero_column_gives_unit_factor`: todas las celdas en 0, LDF = 1 y último = 0, sin NaN (Review Focus 1).
  - `test_tail_factors_near_one_on_generated_portfolio(db_path)`: en el triángulo de monto de cada tipo, los LDF con `dev_quarter ≥ 8` están en [0,995; 1,005].
  - `test_cape_cod_uses_trended_prior`: triángulo sintético en el que el pagado del origen reciente es 0. Último = a_priori × (1 − 1/CDF), con pp maduro constante 2,0 y exposición 10.
  - `test_estimate_ibnr_switches_method_for_cape_cod_types`: `method` es `cape_cod` solo para alto costo en los últimos 4 trimestres, e `ibnr_uf ≥ 0` en todas las filas.
- [ ] **Step 2:** `uv run pytest tests/test_ibnr.py -v`. Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3:** Implementar en `ibnr.py`. Los conteos usan siempre chain-ladder. `exposure_quarter` sale de `mart_model_cells_company`, agregada por `claim_type × origin_quarter`.
- [ ] **Step 4:** `uv run pytest tests/test_ibnr.py -v`. Expected: PASS.
- [ ] **Step 5:** `git commit -m "feat: chain-ladder and Cape Cod IBNR by claim type and quarter"`

### Task 4: Siniestros últimos por celda y contrato, y `mart_ibnr`

**Files:**
- Create: `src/colectivos/models/ultimates.py`
- Test: `tests/test_ultimates.py`

**Interfaces:**
- Consumes: `estimate_ibnr` (Task 3) y `marts.mart_model_cells_company` (Task 2).
- Produces:
  - `cells_to_ultimate(cells: pd.DataFrame, ibnr: pd.DataFrame) -> pd.DataFrame`: agrega a `cells` las columnas `n_claims_ult`, `reimbursed_ult_uf` y `reimbursed_capped_ult_uf`. Para chain-ladder: valor de la celda × CDF de su `claim_type × origin_quarter`. Para Cape Cod: valor de la celda + IBNR del trimestre × `exposure_years` de la celda / exposición total del tipo y trimestre.
  - `to_yearly(cells_ult: pd.DataFrame) -> pd.DataFrame`: agrega a `year × claim_type × company_id × contract_id × factores`. Es la base de modelamiento de las Tasks 5 a 9.
  - `save_ibnr_mart(db_path: Path, ibnr: pd.DataFrame) -> None`: escribe `marts.mart_ibnr`.

- [ ] **Step 1: Write the failing tests** (con `db_path`):
  - `test_cell_ultimates_sum_to_ibnr_ultimates`: por `claim_type × origin_quarter`, la suma sobre celdas de cada último es igual a la columna correspondiente de `estimate_ibnr` (rel = 1e-9).
  - `test_cape_cod_allocation_gives_ultimate_to_contracts_without_paid`: en alto costo de 2025, las celdas con `reimbursed_uf = 0` y exposición > 0 quedan con `reimbursed_ult_uf > 0`.
  - `test_to_yearly_preserves_totals`.
  - `test_ibnr_mart_is_exported(db_path, tmp_path)`: `export_marts` escribe `mart_ibnr.csv`.
- [ ] **Step 2:** `uv run pytest tests/test_ultimates.py -v`. Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3:** Implementar `ultimates.py`.
- [ ] **Step 4:** `uv run pytest tests/test_ultimates.py tests/test_warehouse.py -v`. Expected: PASS.
- [ ] **Step 5:** `git commit -m "feat: ultimate claims by cell and contract, IBNR mart"`

### Task 5: Etapa 1, tendencia dentro de cada empresa

**Files:**
- Create: `src/colectivos/models/trend.py`
- Test: `tests/test_trend.py`

**Interfaces:**
- Consumes: la base anual de `to_yearly` (Task 4).
- Produces:
  - `@dataclass(frozen=True) class TrendModel`, con:
    - `claim_type: str`;
    - `freq_trend: float`;
    - `sev_trend: float` (tasas anuales, por ejemplo 0,02);
    - `industry_freq_trend: dict[str, float]`: tendencia de frecuencia **adicional** por rubro, solo las interacciones retenidas; vacío si no hay;
    - `lr_pvalue: float | None`.
  - `fit_trend(cells_yearly: pd.DataFrame, claim_type: str, train_years: tuple[int, int], test_interaction: bool, alpha: float) -> TrendModel`.
  - `fit_trends(cells_yearly: pd.DataFrame, train_years: tuple[int, int], cfg: PricingConfig) -> dict[str, TrendModel]`.
  - `trend_log_offset(trends: dict[str, TrendModel], profile: pd.DataFrame, claim_type: str, year_c: float | pd.Series, part: Literal["freq", "sev"]) -> np.ndarray`: `year_c × log(1 + tendencia)`, más el término por rubro en frecuencia cuando corresponda.

Detalles:
- Frecuencia: Poisson `n_claims_ult ~ C(company_id) + C(age_band) + C(sex) + C(role) + C(health_system) + year_c`, con offset log(exposición), donde `year_c = year − REFERENCE_YEAR`.
- Severidad: Gamma con link log, sobre `reimbursed_capped_ult_uf / n_claims_ult` y `var_weights = n_claims_ult`, con las mismas variables.
- Alto costo, en frecuencia y en severidad: sin `C(company_id)`.
- Empresas sin siniestros del tipo en el período de entrenamiento: `company_id = "__sin_siniestros__"` (Review Focus 2).
- Interacción: modelo con `C(industry):year_c`, contra el modelo sin interacción, con prueba de razón de verosimilitud (χ², gl = rubros − 1). Si p < `alpha`, se retienen los coeficientes de interacción significativos al 5% individualmente.

- [ ] **Step 1: Write the failing tests:**
  - `test_trend_ignores_company_mix_shift`: datos sintéticos de 40 empresas, 2021–2024, sin tendencia dentro de cada empresa. Las empresas con efecto 1,5 recién entran en 2024, y la frecuencia agregada sube ~10% ese año. Debe dar `abs(freq_trend) < 0.01`. Este es el test central de la causa 2.
  - `test_trend_recovers_within_company_trend`: el mismo generador sintético, con 3% anual dentro de cada empresa. `freq_trend == approx(0.03, abs=0.005)`.
  - `test_company_without_claims_does_not_break_trend`: una empresa con 0 siniestros. El ajuste converge y `freq_trend` es finito y no cambia más de 0,002 respecto del mismo ajuste sin esa empresa.
  - `test_industry_interaction_retained_when_planted`: datos sintéticos con un rubro a +8% anual. Queda en `industry_freq_trend` con un valor ≈ 0,08 (abs = 0,02), y `lr_pvalue < 0.05`.
  - `test_recovers_generator_trends(medium_db_path)` (`slow`): para ambulatoria y farmacia, `(1 + freq_trend) × (1 + sev_trend) − 1` está a 0,02 o menos (abs) de (1 + `frequency_trend`) × (1 + `annual_trend`) − 1 de `config/generator_small.yaml`, no de `truth`. La tolerancia cubre el apalancamiento de deducibles, que es real. Si falla, es un hallazgo: se reporta al autor, sin ajustar el modelo.
- [ ] **Step 2:** `uv run pytest tests/test_trend.py -v`. Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3:** Implementar `trend.py`. El generador sintético de los tests va como helper en `tests/test_trend.py`, no en `src/`.
- [ ] **Step 4:** `uv run pytest tests/test_trend.py -v -m "slow or not slow"`. Expected: PASS.
- [ ] **Step 5:** `git commit -m "feat: stage-1 within-company trend with industry interaction test"`

### Task 6: Etapa 2, relatividades con la tendencia como offset

**Files:**
- Create: `src/colectivos/models/two_stage.py`
- Modify: `src/colectivos/models/glm.py`. Extraer `_prepare`, `_frequency_levels`, `_levels` y `_align_levels` como funciones públicas sin guion bajo (`prepare_cells`, `frequency_levels`, `fitted_levels`, `align_levels`), y actualizar sus usos. No cambia el comportamiento del GLM de la Fase 1.
- Test: `tests/test_two_stage.py`

**Interfaces:**
- Consumes: `TrendModel`, `fit_trends` y `trend_log_offset` (Task 5), y `FactorLevels` y `align_levels` (`glm.py`).
- Produces:
  - `@dataclass(frozen=True) class TwoStageModel`, con `trends: dict[str, TrendModel]`, `relativities: dict[str, FreqSevModel]` y `train_years: tuple[int, int]`.
  - `fit_two_stage(cells_yearly: pd.DataFrame, train_years: tuple[int, int], cfg: PricingConfig) -> TwoStageModel`.
  - Método `TwoStageModel.predict_cost(profile: pd.DataFrame, year_c: float | pd.Series) -> pd.DataFrame`: mismas columnas de salida que `predict_cost_per_year` (`expected_cost_{tipo}_uf` y `expected_health_cost_uf`), más `unseen_level_flag: bool` por fila.

Detalles:
- Fórmulas sin `year_c`: frecuencia `n_claims_ult ~ factores`, con offset log(exposición) + `trend_log_offset(..., "freq")`. Severidad sobre el promedio limitado último, con offset `trend_log_offset(..., "sev")`.
- Alto costo: severidad sin segmentar (solo intercepto + offset).
- Un nivel no visto marca `unseen_level_flag` y se predice con el respaldo de `FactorLevels`.

- [ ] **Step 1: Write the failing tests:**
  - `test_two_stage_predicts_frequency_times_severity`;
  - `test_offset_applies_trend_exactly`: la predicción en `year_c + 1` sobre la predicción en `year_c` es igual a (1 + freq_trend) × (1 + sev_trend), para un tipo sin interacción;
  - `test_industry_interaction_applies_only_to_that_industry`;
  - `test_unseen_level_flagged`: un perfil con `age_band = "70+"` en un modelo entrenado sin 70+ da `unseen_level_flag = True` y un costo finito;
  - `test_fit_two_stage_on_generated_portfolio_covers_all_types(db_path)`;
  - `uv run pytest tests/test_glm.py` debe seguir verde tras el renombre.
- [ ] **Step 2:** `uv run pytest tests/test_two_stage.py -v`. Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3:** Renombrar en `glm.py` e implementar `two_stage.py`.
- [ ] **Step 4:** `uv run pytest tests/test_two_stage.py tests/test_glm.py -v`. Expected: PASS.
- [ ] **Step 5:** `git commit -m "feat: stage-2 segment relativities with trend offset"`

### Task 7: Retador Tweedie

**Files:**
- Create: `src/colectivos/models/tweedie.py`
- Test: `tests/test_tweedie.py`

**Interfaces:**
- Consumes: `TrendModel` y `trend_log_offset` (Task 5), y `align_levels` y `fitted_levels` (Task 6).
- Produces:
  - `@dataclass(frozen=True) class TweedieModel`, con `trends`, `results: dict[str, GLMResults]`, `powers: dict[str, float]`, `levels: dict[str, FactorLevels]` y `train_years`.
  - `fit_tweedie(cells_yearly: pd.DataFrame, train_years: tuple[int, int], trends: dict[str, TrendModel], powers: tuple[float, ...]) -> TweedieModel`.
  - Método `TweedieModel.predict_cost(profile, year_c) -> pd.DataFrame`, con la misma salida que `TwoStageModel.predict_cost`.

Detalles: por tipo, Tweedie con link log sobre `reimbursed_capped_ult_uf / exposure_years`, con `var_weights = exposure_years`, los 6 factores y el offset de tendencia de frecuencia + severidad. La potencia se elige por la log-verosimilitud perfilada en la grilla (`statsmodels` `Tweedie(var_power=p)` y `.llf`).

- [ ] **Step 1: Write the failing tests:**
  - `test_tweedie_power_selected_from_grid`: la potencia elegida pertenece a `powers`;
  - `test_tweedie_total_matches_training_cost`: la suma de la predicción × exposición en el entrenamiento está a 2% o menos del costo limitado último observado, por tipo;
  - `test_tweedie_predict_cost_has_same_columns_as_two_stage(db_path)`.
- [ ] **Step 2:** `uv run pytest tests/test_tweedie.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implementar `tweedie.py`.
- [ ] **Step 4:** `uv run pytest tests/test_tweedie.py -v`. Expected: PASS.
- [ ] **Step 5:** `git commit -m "feat: Tweedie pure-premium challenger"`

### Task 8: Validación fuera de tiempo (línea base, campeón y retador)

**Files:**
- Create: `src/colectivos/models/oot.py`
- Test: `tests/test_oot.py`

**Interfaces:**
- Consumes:
  - `predict_cost_per_year` y `fit_all` (`glm.py`): línea base de la Fase 1, entrenada sobre `marts.mart_model_cells` pagado, sin cambios.
  - `TwoStageModel` (Task 6) y `TweedieModel` (Task 7).
- Produces:
  - `class CostPredictor(Protocol)`, con `predict_cost(profile: pd.DataFrame, year_c: float | pd.Series) -> pd.DataFrame`.
  - `BaselineModel(models: dict[str, FreqSevModel])`, que implementa `CostPredictor` envolviendo `predict_cost_per_year`.
  - `gini(predicted_rate: np.ndarray, actual: np.ndarray, exposure: np.ndarray) -> float`.
  - `out_of_time_report(predictors: dict[str, CostPredictor], test_cells: pd.DataFrame, test_year: int) -> dict[str, pd.DataFrame]`, con las claves:
    - `"by_type"`: modelo × tipo, con `actual_uf`, `expected_uf`, `ae`, `deviance`;
    - `"by_segment"`: modelo × factor × nivel, con `ae`; los factores son `industry`, `age_band`, `health_system` y el tamaño de empresa por cuartil de exposición;
    - `"contract"`: modelo, con `gini`, `rmse_per_py` y `ae`.

Detalles:
- `actual` = `reimbursed_capped_ult_uf` de 2025.
- Devianza: Poisson sobre los conteos para línea base y campeón; Tweedie sobre el costo para el retador. Cada una se reporta en su propio modelo, sin compararlas entre sí.
- Gini: se ordenan los contratos por la tasa predicha, ascendente, y se arma la curva de Lorenz (x = exposición acumulada / total, y = real acumulado / total). Gini = 1 − 2 × área bajo la curva, por trapecios.

- [ ] **Step 1: Write the failing tests:**
  - `test_gini_perfect_order_positive_and_reversed_negative`: con exposiciones iguales y reales [1, 2, 3, 4], ordenar por predicción [1, 2, 3, 4] da Gini > 0; por [4, 3, 2, 1] da el mismo valor con signo negativo; por una constante da 0;
  - `test_oot_report_has_all_models_and_types(db_path)`;
  - `test_baseline_matches_phase1_ae(db_path)`: la frecuencia A/E de la línea base contra 2025 **pagado** coincide con `actual_vs_expected` de la Fase 1, para fijar que la línea base no cambió.
- [ ] **Step 2:** `uv run pytest tests/test_oot.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implementar `oot.py`.
- [ ] **Step 4:** `uv run pytest tests/test_oot.py -v`. Expected: PASS.
- [ ] **Step 5:** `git commit -m "feat: out-of-time comparison of baseline, two-stage and Tweedie"`

### Task 9: Credibilidad Bühlmann-Straub y recargo por siniestros grandes

**Files:**
- Create: `src/colectivos/pricing/credibility.py`
- Test: `tests/test_credibility.py`

**Interfaces:**
- Consumes: `CostPredictor` (Task 8), la base anual de `to_yearly` (Task 4) y `PricingConfig`.
- Produces:
  - `@dataclass(frozen=True) class CredibilityResult`, con:
    - `s2: float`, `a: float`, `k: float` (`inf` si a ≤ 0), `center: float`;
    - `by_contract: pd.DataFrame`, con columnas `contract_id`, `weight`, `experience_ae`, `credibility_z`, `credibility_factor`, `n_years`.
  - `buhlmann_straub(experience: pd.DataFrame) -> CredibilityResult`: `experience` trae `contract_id`, `year`, `ratio` (X_cy) y `weight` (w_cy).
  - `contract_experience(cells_yearly: pd.DataFrame, model: CostPredictor, years: tuple[int, int]) -> pd.DataFrame`: X_cy = costo limitado último observado / esperado del modelo; w_cy = esperado.
  - `large_loss_load(cells_yearly: pd.DataFrame, model: CostPredictor, years: tuple[int, int]) -> float`: exceso último total (`reimbursed_ult_uf − reimbursed_capped_ult_uf`) / esperado limitado total.

Estimadores (Bühlmann y Gisler), con contratos i, años j y n_i años con w_ij > 0:

```text
w_i = Σ_j w_ij;  X̄_i = Σ_j w_ij X_ij / w_i;  w = Σ_i w_i;  X̄ = Σ_i w_i X̄_i / w
s² = Σ_i Σ_j w_ij (X_ij − X̄_i)² / Σ_i (n_i − 1)
a  = [Σ_i w_i (X̄_i − X̄)² − (I − 1) s²] / [w − Σ_i w_i² / w]
a ≤ 0  →  Z_i = 0 para todos, k = inf, y warning en el log.
k = s² / a;  Z_i = w_i / (w_i + k)
center = 1.0 si |X̄ − 1| ≤ 0.02; si no, X̄ (y warning en el log)
F_i = Z_i X̄_i + (1 − Z_i) · center
```

- [ ] **Step 1: Write the failing tests:**
  - `test_buhlmann_straub_textbook_values`: 3 contratos × 3 años con pesos y ratios fijos en el test. Se comparan s², a, k y Z contra valores calculados a mano con las fórmulas de arriba y escritos en el test como literales con 6 decimales.
  - `test_zero_between_variance_gives_zero_credibility`: todos los contratos con el mismo X̄_i → Z = 0, F = center y un warning capturado con `caplog` (Review Focus 4).
  - `test_single_year_and_tiny_weight_contract_is_finite`: un contrato con n_i = 1 y w = 1e-6 da Z ≈ 0 y F finito (Review Focus 3).
  - `test_large_loss_load_counts_excess_once(db_path)`: el recargo × el esperado limitado total es igual al exceso último total.
  - `test_credibility_reduces_rate_change_correlation_with_company_effect(medium_db_path)` (`slow`): lee `company_effects.parquet` **solo dentro del test**. corr(log F, log efecto) > 0,3. Si falla, es un hallazgo y se reporta.
- [ ] **Step 2:** `uv run pytest tests/test_credibility.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implementar `credibility.py`.
- [ ] **Step 4:** `uv run pytest tests/test_credibility.py -v -m "slow or not slow"`. Expected: PASS.
- [ ] **Step 5:** `git commit -m "feat: Bühlmann-Straub credibility by contract and large-loss load"`

### Task 10: Tarificación 2026 con modelo de dos etapas y credibilidad

**Files:**
- Modify: `src/colectivos/pricing/technical_premium.py` (`price_renewals`, `renewal_table`, `RENEWAL_COLUMNS`)
- Test: `tests/test_pricing.py`

**Interfaces:**
- Consumes: `CostPredictor` (Task 8), `CredibilityResult` y `large_loss_load` (Task 9).
- Produces:
  - `price_renewals(profile, terms, exposure_hist, model: CostPredictor, credibility: CredibilityResult, large_loss_load: float, mortality, pricing) -> pd.DataFrame`.
  - `renewal_table(db_path, model, credibility, large_loss_load, mortality, pricing, valuation_date=...)`.
  - `RENEWAL_COLUMNS`: las columnas actuales más `expected_health_cost_model_uf`, `experience_ae`, `credibility_z`, `credibility_factor`, `large_loss_load_uf` y `unseen_level_flag`.

Detalles:
- `expected_health_cost_uf = expected_health_cost_model_uf × credibility_factor + large_loss_load_uf`, con `large_loss_load_uf = large_loss_load × expected_health_cost_model_uf`.
- Un contrato sin fila en `credibility.by_contract` queda con Z = 0 y F = `credibility.center`.
- `unseen_level_flag` del contrato es el OR de sus asegurados. Si hay alguno, se loguea un warning con la lista de contratos.
- Los tests existentes de `test_pricing.py` que llaman a `price_renewals` se actualizan a la firma nueva, con un `CredibilityResult` neutro (Z = 0, center = 1) y `large_loss_load = 0`. Con esos valores, el resultado debe ser idéntico al del modelo solo.

- [ ] **Step 1: Write the failing tests:**
  - `test_neutral_credibility_equals_model_only`;
  - `test_credibility_factor_scales_health_cost_only`: la vida no cambia;
  - `test_large_loss_load_added`;
  - `test_contract_without_experience_gets_center`;
  - `test_unseen_level_flag_propagates_to_contract` (Review Focus 5).
- [ ] **Step 2:** `uv run pytest tests/test_pricing.py -v`. Expected: FAIL.
- [ ] **Step 3:** Modificar `technical_premium.py`.
- [ ] **Step 4:** `uv run pytest tests/test_pricing.py -v -m "slow or not slow"`. Expected: PASS.
- [ ] **Step 5:** `git commit -m "feat: 2026 pricing with two-stage model, credibility and large-loss load"`

### Task 11: Descomposición del reajuste agregado

**Files:**
- Create: `src/colectivos/report/decomposition.py`
- Modify: `src/colectivos/report/draft.py`, que agrega la sección "Descomposición del reajuste agregado" con la tabla
- Test: `tests/test_decomposition.py`

**Interfaces:**
- Consumes: `CostPredictor` (Task 8), `mart_renewal_2026` (Task 10) y la base anual (Task 4).
- Produces: `rate_change_decomposition(db_path: Path, model: CostPredictor, cells_yearly: pd.DataFrame, renewal: pd.DataFrame, pricing: PricingConfig) -> pd.DataFrame`, con las columnas `factor`, `multiplier` y `log_share`, y las filas en el orden y con las definiciones de la tabla de la sección 5.8 del spec. Las cantidades se calculan sobre los contratos de `renewal`, con R = `pricing.reference_year`.

- [ ] **Step 1: Write the failing tests:**
  - `test_decomposition_product_equals_aggregate_rate_change(db_path)`: el producto de `multiplier` es igual a Σ prima técnica / Σ prima vigente (rel = 1e-9);
  - `test_decomposition_rows_in_spec_order`;
  - `test_draft_contains_decomposition_section(db_path, tmp_path)`.
- [ ] **Step 2:** `uv run pytest tests/test_decomposition.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implementar `decomposition.py` y la sección del borrador. `build_draft` recibe la tabla ya calculada como parámetro opcional `decomposition: pd.DataFrame | None`.
- [ ] **Step 4:** `uv run pytest tests/test_decomposition.py -v`. Expected: PASS.
- [ ] **Step 5:** `git commit -m "feat: multiplicative decomposition of the aggregate rate change"`

### Task 12: Pipeline de Fase 2

**Files:**
- Modify: `src/colectivos/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: todas las tasks anteriores.
- Produces: el orden de la sección 5.10 del spec, con estos 8 pasos impresos:
  1. Generar.
  2. Warehouse (con `large_loss_threshold_uf` de `pricing.yaml`).
  3. Calibración.
  4. IBNR → `mart_ibnr`.
  5. Validación fuera de tiempo: imprime `by_type` y `contract`, y escribe las tres tablas en `marts.mart_oot_by_type`, `marts.mart_oot_by_segment` y `marts.mart_oot_contract`.
  6. Reentrenamiento 2021–2025, credibilidad y recargo.
  7. Tarificación 2026 y descomposición.
  8. Exportar y escribir el borrador.

  `pricing.yaml` se carga al inicio.

- [ ] **Step 1: Write the failing test:** `test_pipeline_small_end_to_end` verifica que existen `mart_ibnr`, los tres `mart_oot_*`, `mart_renewal_2026` con `credibility_factor`, y el CSV de cada mart en exports. También verifica que el borrador contiene "Descomposición del reajuste agregado".
- [ ] **Step 2:** `uv run pytest tests/test_pipeline.py -v`. Expected: FAIL.
- [ ] **Step 3:** Modificar `pipeline.py`.
- [ ] **Step 4:** `uv run pytest -v`. Expected: toda la suite PASS.
- [ ] **Step 5:** Correr a escala full: `uv run python -m colectivos.pipeline --config config/generator.yaml --out data --exports exports`. Expected: termina sin error y las 4 métricas de calibración están en rango. Anotar en el ledger, para el informe al autor: el tiempo total, la tabla `by_type`, la tabla `contract`, el reajuste agregado y el p10, la mediana y el p90. **Regla de decisión del spec (5.5):** el campeón de dos etapas tarifica. Si el retador Tweedie gana con claridad en `contract.gini` y en el A/E por segmento, se para y se muestra al autor antes de cambiar el modelo de tarificación.
- [ ] **Step 6:** `git commit -m "feat: phase 2 pipeline (IBNR, OOT validation, credibility, decomposition)"`

### Task 13: Validación contra la verdad

**Files:**
- Create:
  - `src/colectivos/validation/__init__.py`, `__main__.py`, `truth_checks.py`
  - `tests/test_validation.py`

**Interfaces:**
- Consumes: `truth_dir` (`data/truth/`), el warehouse y los modelos de las Tasks 4 a 9.
- Produces, en `truth_checks.py`:
  - `ibnr_error(db_path: Path, truth_dir: Path) -> pd.DataFrame`: tipo × trimestre, con `ibnr_est_uf`, `ibnr_true_uf`, `error_uf` y `error_rel`. El IBNR verdadero = Σ `health_claims_full.reimbursed_uf` con ocurrencia en el trimestre − lo pagado al corte.
  - `trend_recovery(trends: dict[str, TrendModel], truth_dir: Path) -> pd.DataFrame`: frente a `parameters.json`.
  - `relativity_recovery(model: TwoStageModel, truth_dir: Path) -> pd.DataFrame`: factor × nivel, estimada frente a verdadera, normalizadas al nivel base.
  - `pattern_detection(db_path: Path, model: TwoStageModel, renewal: pd.DataFrame, truth_dir: Path) -> pd.DataFrame`: una fila por patrón, con `detected: bool` y `evidence: str`, según los criterios de la tabla de la sección 5.9 del spec.
  - `credibility_gain(cells_yearly: pd.DataFrame, cfg: PricingConfig, truth_dir: Path) -> pd.DataFrame`: modelo y credibilidad estimados con 2021–2024, contra el costo realizado completo y limitado de 2025, por contrato. Columnas `metric` (`rmse_per_py`, `ae`, `corr_log_factor_log_effect`), `model_only` y `with_credibility`.
  - `oot_against_truth(predictors: dict[str, CostPredictor], test_cells: pd.DataFrame, db_path: Path, truth_dir: Path) -> dict[str, pd.DataFrame]`: el anexo de la sección 5.5 del spec. Usa el mismo `out_of_time_report` (Task 8), con el `actual` de 2025 reemplazado por el costo completo y limitado de `health_claims_full`, agregado a las mismas celdas. Agrega la columna `ae_shift` = A/E contra la verdad − A/E contra los siniestros últimos estimados, que es el error que aporta el IBNR.
- `python -m colectivos.validation --data data` imprime las seis tablas y las escribe en `data/reports/validacion/*.csv`.

- [ ] **Step 1: Write the failing tests** (con `db_path` y `truth_dir`):
  - `test_ibnr_error_rows_cover_all_types_and_quarters`;
  - `test_true_ibnr_nonnegative`;
  - `test_pattern_detection_reports_five_patterns`;
  - `test_credibility_gain_has_both_columns`;
  - `test_oot_against_truth_has_ae_shift_per_model_and_type`;
  - `test_pricing_modules_do_not_read_truth`: grep sobre `src/colectivos/{models,pricing,report,pipeline.py}` sin coincidencias de `"truth"`.
- [ ] **Step 2:** `uv run pytest tests/test_validation.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implementar `truth_checks.py` y `__main__.py`.
- [ ] **Step 4:** `uv run pytest tests/test_validation.py -v`. Expected: PASS.
- [ ] **Step 5:** Correr `uv run python -m colectivos.validation --data data` a escala full. Anotar en el ledger, como hallazgos para el autor:
  - error total del IBNR;
  - tendencia recuperada por tipo;
  - sector público estimado frente a 1,21;
  - patrones detectados;
  - ganancia de credibilidad.

  Lo que no se explique se para y se muestra.
- [ ] **Step 6:** `git commit -m "feat: validation against generator truth (IBNR, trend, relativities, patterns, credibility)"`

### Task 14: Notebook de validación y handoff

**Files:**
- Create: `notebooks/02_validacion_modelo.ipynb`
- Modify: `docs/HANDOFF.md` (secciones 4 a 7, con las cifras actuales y la Fase 2 hecha) y `README.md` (glosario: IBNR, chain-ladder, Cape Cod, credibilidad, efecto fijo y Tweedie)

**Interfaces:**
- Consumes: `colectivos.validation.truth_checks` y los marts `mart_ibnr` y `mart_oot_*`.

Secciones del notebook, en este orden. Cada una con su tabla, un gráfico matplotlib y dos o tres líneas de lectura:

1. IBNR: triángulo, factores de desarrollo y error contra la verdad.
2. Tendencia: Fase 1 contra dos etapas contra el generador.
3. Relatividades contra la verdad.
4. Validación fuera de tiempo: A/E por segmento, lift y Gini.
5. Credibilidad: Z contra exposición y F contra el efecto verdadero.
6. Patrones.
7. Reajuste 2026 y descomposición.

- [ ] **Step 1:** Escribir el notebook. Leer el skill `dataviz` antes del primer gráfico.
- [ ] **Step 2:** `uv run jupyter nbconvert --to notebook --execute --inplace notebooks/02_validacion_modelo.ipynb`. Expected: se ejecuta sin error.
- [ ] **Step 3:** Actualizar HANDOFF.md y README.md.
- [ ] **Step 4:** `uv run pytest`. Expected: toda la suite PASS.
- [ ] **Step 5:** `git commit -m "docs: phase 2 validation notebook, handoff and glossary"`

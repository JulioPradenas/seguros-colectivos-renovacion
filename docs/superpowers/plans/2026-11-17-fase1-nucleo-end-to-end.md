# Fase 1: Núcleo end-to-end — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un pipeline reproducible de un solo comando que hace lo siguiente:

- genera una cartera sintética de seguros colectivos de salud y vida calibrada con la CMF;
- la carga en DuckDB y construye las tablas analíticas;
- ajusta GLM de frecuencia y severidad;
- calcula la prima técnica 2026, el reajuste requerido y la suficiencia por contrato (todavía sin credibilidad);
- exporta los CSV para Tableau y un borrador de informe con cifras.

**Architecture:** Paquete Python `colectivos` con cuatro capas:

- `generator`: numpy y pandas, escribe parquet;
- `warehouse`: DuckDB más archivos SQL;
- `models`: GLM en statsmodels;
- `pricing`.

`colectivos.pipeline` las orquesta. Los parámetros viven en YAML. Los parámetros verdaderos del generador se escriben en `data/truth/` y ningún módulo de `models` ni de `pricing` los lee.

**Tech Stack:** Python 3.12, uv, pandas, numpy, pyarrow, duckdb, pyyaml, statsmodels, pytest.

**Spec:** `docs/superpowers/specs/2026-11-17-renovacion-colectivos-salud-vida-design.md`

**Fuera de esta fase** (cada una tendrá su propio plan): IBNR, credibilidad Bühlmann-Straub, retador LightGBM, escenarios y Monte Carlo, Streamlit, dashboard Tableau, cotizador Excel, informe final y documento de metodología.

## Global Constraints

- Compañía ficticia: "Compañía de Seguros Cordillera (ficticia)". Ninguna marca real en el código, los datos ni los textos.
- Período observado: 2021-01-01 a 2025-12-31. Fecha de valoración: 2025-12-31. Tarificación: renovaciones con inicio en 2026.
- Moneda: UF en todas las columnas monetarias (sufijo `_uf`).
- Tipos de prestación (valores exactos): `ambulatoria`, `hospitalaria`, `dental`, `farmacia`, `alto_costo`.
- Previsión (valores exactos): `isapre`, `fonasa`. Rol: `titular`, `carga`.
- Escala `full`: unas 300 empresas y entre 50.000 y 80.000 asegurados. Escala `small` para tests: 20 empresas.
- Los contratos renuevan en el aniversario de `client_since`, con meses repartidos durante el año.
- Toda cifra de calibración lleva fuente (URL CMF, INE o Superintendencia de Salud) o `assumption: true`.
- Los datos crudos que ven el warehouse y los modelos solo incluyen siniestros con `payment_date <= 2025-12-31`. La versión completa va únicamente a `data/truth/`.
- Código: f-strings, `pathlib.Path`, type hints en `src/`, nombres en inglés.
- SQL: keywords en MAYÚSCULAS, 4 espacios de indentación, CTEs en vez de subqueries anidadas y alias descriptivos.
- `data/` y `exports/` van en `.gitignore`. `config/` y `data/truth/README.md` sí se versionan.
- Commits terminan con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Un contrato sin asegurados vigentes al 2025-12-31 no aparece en la tabla de renovación y no provoca división por cero. Test en la Task 9.
2. Una celda o nivel de factor sin siniestros en entrenamiento (por ejemplo, dental en una región chica) produce predicciones finitas y positivas. Test en la Task 8.
3. Un siniestro pagado después de la fecha de valoración nunca llega a `data/raw/` ni al warehouse. Test en la Task 5.
4. Una carga cuyo titular se dio de baja tiene exposición cero desde la baja del titular. Test en la Task 2.
5. Un contrato con menos de 1 año-persona de exposición histórica queda marcado `low_exposure_flag = True`, porque su reajuste no es confiable sin credibilidad. Test en la Task 9.

---

## Estructura de archivos

```
pyproject.toml
.gitignore
config/
    generator.yaml              # parámetros del generador (escala full)
    generator_small.yaml        # escala de test
    calibration_targets.yaml    # objetivos CMF/INE con fuente
    pricing.yaml                # gastos, comisión, margen, umbrales
    mortality/<tabla_cmf>.csv   # age, sex, qx
src/colectivos/
    __init__.py
    config.py                   # carga y valida YAML
    generator/
        portfolio.py            # companies, plans, contracts, insureds
        exposure.py             # exposure_monthly
        health_claims.py        # frecuencia, severidad, reembolso, desfase
        life_claims.py
        premiums.py
        patterns.py             # multiplicadores de patrones plantados
        run.py                  # orquesta, corte de valoración, escribe parquet + truth
    warehouse/
        build.py                # carga parquet y ejecuta SQL en orden
        export.py
        sql/01_staging/*.sql
        sql/02_intermediate/*.sql
        sql/03_marts/*.sql
    calibration.py
    models/glm.py
    pricing/technical_premium.py
    report/draft.py
    pipeline.py                 # CLI
tests/
    conftest.py                 # fixture: cartera small generada una vez por sesión
    test_config.py
    test_portfolio.py
    test_exposure.py
    test_health_claims.py
    test_life_premiums.py
    test_patterns.py
    test_warehouse.py
    test_calibration.py
    test_glm.py
    test_pricing.py
    test_pipeline.py
notebooks/01_calidad_datos.ipynb
# el pipeline escribe <out>/reports/informe_borrador.md (con --out data/ queda en data/reports/)
```

---

### Task 1: Scaffolding y configuración

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/colectivos/__init__.py`, `src/colectivos/config.py`, `config/generator.yaml`, `config/generator_small.yaml`, `config/pricing.yaml`, `tests/conftest.py` (fixture de sesión `small_cfg`; las tareas siguientes le agregan fixtures)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `load_generator_config(path: Path) -> GeneratorConfig`
  - `load_pricing_config(path: Path) -> PricingConfig`
  - `GeneratorConfig` es una dataclass frozen con estos campos:
    - `seed: int`, `start: date`, `end: date`, `valuation_date: date`, `n_companies: int`;
    - `industries: dict[str, float]` (pesos), `regions: dict[str, float]`;
    - `company_size_lognormal: dict` (`mu`, `sigma`, `min`, `max` titulares);
    - `dependents_per_holder: float`, `fonasa_share: float`;
    - `claim_types: list[str]`;
    - `base_frequency: dict[str, float]` (siniestros por año-persona por tipo);
    - `relativities: dict[str, dict[str, float]]` (factor → nivel → multiplicador);
    - `annual_trend: dict[str, float]`;
    - `company_effect_shape: float` (gamma con media 1);
    - `severity: dict[str, dict]` (`dist`, parámetros en UF);
    - `catastrophic: dict` (`pareto_alpha`, `threshold_uf`, `annual_rate`);
    - `system_coverage: dict[str, dict[str, float]]` (previsión → tipo → fracción cubierta);
    - `plans: list[dict]`;
    - `payment_lag_days: dict[str, dict]` (lognormal `mu`, `sigma` por tipo);
    - `life_capital_uf: list[float]`, `initial_loading: float`;
    - `historic_rate_change: dict` (`mean`, `sd`);
    - `patterns: dict`.
  - `PricingConfig` es una dataclass con `expense_ratio`, `commission_ratio`, `target_margin`, `low_exposure_threshold_years` y `pricing_year: int`.

- [ ] **Step 1:** `git init`. Crear el proyecto con `uv init --package colectivos --python 3.12` y agregar las dependencias del Tech Stack. El `.gitignore` incluye `data/`, `exports/`, `.venv/` y `*.duckdb`.
- [ ] **Step 2:** Escribir el test que falla.

```python
def test_load_generator_config_small():
    cfg = load_generator_config(Path("config/generator_small.yaml"))
    assert cfg.n_companies == 20
    assert cfg.valuation_date == date(2025, 12, 31)
    assert set(cfg.claim_types) == {"ambulatoria", "hospitalaria", "dental", "farmacia", "alto_costo"}
    assert set(cfg.system_coverage) == {"isapre", "fonasa"}

def test_config_rejects_unknown_claim_type(tmp_path):
    # YAML con claim_types que incluye "optica" -> ValueError mencionando "optica"
    ...

def test_load_pricing_config():
    pc = load_pricing_config(Path("config/pricing.yaml"))
    assert 0 < pc.expense_ratio + pc.commission_ratio + pc.target_margin < 1
    assert pc.pricing_year == 2026
```

- [ ] **Step 3:** Ejecutar `uv run pytest tests/test_config.py -v`. Esperado: FAIL (ImportError).
- [ ] **Step 4:** Implementar `config.py`. La validación revisa tres cosas: que los tipos estén dentro de los 5 permitidos, que los pesos sumen 1 con tolerancia 1e-6, y que `valuation_date <= end`. Llenar los YAML con valores plausibles; cada valor que sea supuesto lleva un comentario `# supuesto`. `pricing.yaml` parte con `expense_ratio: 0.12`, `commission_ratio: 0.08`, `target_margin: 0.05`, `low_exposure_threshold_years: 1.0` y `pricing_year: 2026`, todos marcados como supuesto. `generator_small.yaml` es una copia con `n_companies: 20`.
- [ ] **Step 5:** Ejecutar `uv run pytest tests/test_config.py -v`. Esperado: PASS.
- [ ] **Step 6:** Commit con el mensaje `chore: scaffold project and config loading`.

---

### Task 2: Cartera (empresas, planes, contratos, asegurados) y exposición

**Files:**
- Create: `src/colectivos/generator/portfolio.py`, `src/colectivos/generator/exposure.py`
- Modify: `tests/conftest.py`: agrega los fixtures de sesión `companies`, `plans`, `insureds`, `contracts` y `exposure`, todos con `small_cfg` y `default_rng(small_cfg.seed)`.
- Test: `tests/test_portfolio.py`, `tests/test_exposure.py`

**Interfaces:**
- Consumes: `GeneratorConfig`.
- Produces:
  - `generate_companies(cfg, rng: np.random.Generator) -> pd.DataFrame`, con columnas `company_id, industry, region, n_holders_target, client_since`.
  - `generate_plans(cfg) -> pd.DataFrame`, con columnas `plan_id, claim_type, reimbursement_pct, deductible_uf, annual_cap_uf`.
  - `generate_insureds(cfg, companies, rng) -> pd.DataFrame`, con columnas `insured_id, company_id, holder_id` (nulo para el titular), `role, sex, birth_date, health_system, enrollment_date, termination_date` (nullable).
  - `generate_contracts(cfg, companies, rng) -> pd.DataFrame`, con columnas `contract_id, company_id, plan_id, term_start, term_end, life_capital_uf, expense_ratio, commission_ratio`. La prima se completa en la Task 4, porque depende del costo esperado. Hay una fila por vigencia anual. `term_start` cae en el mes aniversario de `client_since`, y las vigencias cubren el período observado más la vigencia que empieza en 2026.
  - `build_exposure(insureds, start: date, end: date) -> pd.DataFrame`, con columnas `insured_id, company_id, month` (primer día del mes), `exposure` (0–1, fracción de días del mes), `age` (entera al inicio del mes).

- [ ] **Step 1:** Escribir los tests que fallan.

```python
def test_companies_count_and_domains(small_cfg):
    companies = generate_companies(small_cfg, np.random.default_rng(1))
    assert len(companies) == 20
    assert set(companies.industry) <= set(small_cfg.industries)

def test_dependents_belong_to_holder_of_same_company(insureds):
    deps = insureds[insureds.role == "carga"]
    holders = insureds.set_index("insured_id")
    assert (holders.loc[deps.holder_id, "company_id"].values == deps.company_id.values).all()

def test_dependent_terminates_no_later_than_holder(insureds): ...
def test_birth_dates_give_ages_0_to_80_at_enrollment(insureds): ...
def test_contract_terms_are_annual_and_contiguous(contracts): ...
def test_same_seed_same_output(small_cfg): ...  # pd.testing.assert_frame_equal

def test_exposure_between_0_and_1_and_zero_outside_enrollment(exposure, insureds): ...
def test_dependent_exposure_zero_after_holder_termination(exposure, insureds): ...  # Review Focus 4
def test_exposure_years_full_month():
    # un asegurado inscrito el 2021-01-01 sin baja tiene exposure == 1.0 en todos los meses
    ...
```

- [ ] **Step 2:** Ejecutar `uv run pytest tests/test_portfolio.py tests/test_exposure.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implementar. Reglas:
  - El tamaño de cada empresa sale de una lognormal acotada.
  - Las cargas salen de una Poisson con media `dependents_per_holder`.
  - La previsión se asigna por titular y la heredan sus cargas.
  - Rotación anual de asegurados: 10% de bajas y altas equivalentes (supuesto en YAML).
  - `build_exposure` se vectoriza con `pd.period_range` y un merge, sin loops por asegurado.
- [ ] **Step 4:** Ejecutar los mismos tests. Esperado: PASS.
- [ ] **Step 5:** Commit con el mensaje `feat: generate portfolio and monthly exposure`.

---

### Task 3: Siniestros de salud

**Files:**
- Create: `src/colectivos/generator/health_claims.py`
- Modify: `tests/conftest.py`: agrega el fixture de sesión `claims`.
- Test: `tests/test_health_claims.py`

**Interfaces:**
- Consumes: la salida de la Task 2.
- Produces:
  - `expected_frequency(cfg, exposure_enriched: pd.DataFrame, claim_type: str, company_effect: pd.Series, pattern_multiplier: pd.Series | None = None) -> pd.Series`. Devuelve λ por fila de exposición.
  - `generate_health_claims(cfg, exposure, insureds, companies, contracts, plans, rng, pattern_multipliers: dict[str, pd.Series] | None = None) -> pd.DataFrame`, con columnas `claim_id, insured_id, company_id, contract_id, claim_type, occurrence_date, payment_date, billed_uf, system_covered_uf, reimbursed_uf`. Solo incluye filas con `reimbursed_uf > 0`.
  - `apply_reimbursement(claims, plans, contracts) -> pd.DataFrame`.

**Reglas de reembolso** (no las determina el test por sí solo):

```
copago = billed_uf - system_covered_uf
system_covered_uf = billed_uf * system_coverage[health_system][claim_type]
Deducible anual por asegurado × tipo × vigencia: se consume en orden de occurrence_date (cumsum del copago).
reembolsable = max(copago - deducible_restante, 0) * reimbursement_pct
Tope anual por asegurado × tipo × vigencia sobre el cumsum de reembolsable.
```

**Frecuencia:** λ = `base_frequency[tipo]` × producto de las relatividades (age_band, sex, health_system, role, industry, region) × (1 + trend)^(año − 2021) × efecto de empresa (gamma con media 1 y shape `company_effect_shape`) × estacionalidad × exposure / 12.

- Bandas de edad: `0-17, 18-29, 30-44, 45-59, 60-69, 70+`.
- Estacionalidad: multiplicador 1.25 en mayo–agosto para `ambulatoria` y `farmacia`; 1.0 en el resto.
- `alto_costo` usa una severidad Pareto sobre `threshold_uf`.

- [ ] **Step 1:** Escribir los tests que fallan.

```python
def test_reimbursement_respects_deductible_pct_and_cap():
    # plan: pct 0.8, deducible 1.0 UF, tope 10 UF; un asegurado isapre con cobertura 0.5
    # siniestros billed 4, 6, 30 UF en ese orden -> copagos 2, 3, 15
    # reembolsable: (2-1)*0.8=0.8, 3*0.8=2.4, 15*0.8=12 -> tope deja 10-3.2=6.8
    assert out.reimbursed_uf.round(6).tolist() == [0.8, 2.4, 6.8]

def test_reimbursed_never_exceeds_copay(claims): ...
def test_payment_after_occurrence(claims): assert (claims.payment_date >= claims.occurrence_date).all()
def test_claims_only_while_exposed(claims, exposure): ...
def test_fonasa_higher_copay_than_isapre_same_billed(): ...

@pytest.mark.slow
def test_empirical_frequency_matches_lambda(small_cfg):
    # con 200k meses-persona sintéticos, el conteo total queda dentro de ±3% de sum(λ)
    ...
```

- [ ] **Step 2:** Ejecutar `uv run pytest tests/test_health_claims.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implementar. El conteo es `rng.poisson(λ)` por fila de exposición y tipo, y luego se expande con `np.repeat`. La fecha de ocurrencia es uniforme dentro del mes. `payment_date` = ocurrencia + lognormal(`payment_lag_days[tipo]`), en días enteros. El deducible y el tope se calculan con `groupby([...]).cumsum()` después de ordenar.
- [ ] **Step 4:** Ejecutar `uv run pytest tests/test_health_claims.py -v -m "not slow"` y después `-m slow`. Esperado: PASS.
- [ ] **Step 5:** Commit con el mensaje `feat: generate health claims with reimbursement rules`.

---

### Task 4: Vida, primas, patrones plantados y orquestación del generador

**Files:**
- Create: `src/colectivos/generator/life_claims.py`, `premiums.py`, `patterns.py`, `run.py`, `config/mortality/<tabla_cmf>.csv`, `data/truth/README.md` (versionado con `git add -f`)
- Modify: `tests/conftest.py`
- Test: `tests/test_life_premiums.py`, `tests/test_patterns.py`

**Interfaces:**
- Consumes: las Tasks 2 y 3.
- Produces:
  - `load_mortality(path: Path) -> pd.DataFrame`, con columnas `age, sex, qx`.
  - `generate_life_claims(cfg, exposure, insureds, contracts, mortality, rng) -> pd.DataFrame`, con columnas `claim_id, insured_id, contract_id, death_date, capital_paid_uf`. Solo cubre titulares.
  - `price_contracts(cfg, contracts, exposure, expected_cost: pd.DataFrame, rng) -> pd.DataFrame`. Agrega `premium_holder_uf, premium_dependent_uf, rate_change_applied`.
  - `generate_premiums(contracts, exposure, insureds) -> pd.DataFrame`, con columnas `contract_id, month, earned_premium_uf`.
  - `pattern_multipliers(cfg, exposure_enriched, companies, contracts) -> dict[str, pd.Series]`.
  - `run_generator(cfg_path: Path, raw_dir: Path, truth_dir: Path) -> None`. Escribe en `raw_dir` `companies, plans, contracts, insureds, exposure_monthly, health_claims, life_claims, premiums_monthly` en `.parquet`, ya con el corte de valoración. En `truth_dir` escribe `health_claims_full.parquet`, `life_claims_full.parquet`, `company_effects.parquet`, `parameters.json` (la configuración efectiva) y `patterns.json`.

**Primas:**

- La prima inicial (primera vigencia de cada contrato) = costo esperado verdadero por titular y por carga × (1 + `initial_loading`) × ruido lognormal (sigma 0.10).
- En cada renovación posterior: prima × (1 + `rate_change`), con `rate_change` ~ Normal(`historic_rate_change.mean`, `sd`).
- La vigencia 2026 se crea con la prima vigente al 2025 y `rate_change_applied` nulo. Esa es la prima que la Task 9 compara contra la prima técnica.

**Patrones plantados** (valores en `config.patterns`, todos marcados supuesto):

| id | Efecto |
|---|---|
| `industry_hospital_trend` | `industry == "construccion"`: frecuencia `hospitalaria` × 1.08^(año−2021) |
| `adverse_selection` | 10 empresas con menos de 50 titulares: los asegurados que entran desde 2023-01-01 tienen frecuencia × 1.6 en todos los tipos |
| `catastrophic_event` | Un siniestro `alto_costo` de 8.000 UF en 2023 en una empresa de 200–500 titulares |
| `inadequate_rate_changes` | 15% de los contratos con `rate_change = 0` en todas sus renovaciones |
| `fonasa_shift` | Las altas de 2024–2025 entran con `fonasa_share` × 1.6 |

- [ ] **Step 1:** Buscar en la CMF la tabla de mortalidad oficial vigente que corresponda para seguros de vida (verificar el nombre exacto en cmfchile.cl, normativa de tablas de mortalidad). Guardarla como CSV con las columnas `age, sex, qx`. Registrar la URL en `config/mortality/README.md`.
- [ ] **Step 2:** Escribir los tests que fallan.

```python
def test_valuation_cut_excludes_late_payments(raw_dir, truth_dir):  # Review Focus 3
    raw = pd.read_parquet(raw_dir / "health_claims.parquet")
    full = pd.read_parquet(truth_dir / "health_claims_full.parquet")
    assert raw.payment_date.max() <= pd.Timestamp("2025-12-31")
    assert len(full) > len(raw)

def test_life_claims_only_holders_and_one_per_insured(life_claims, insureds): ...
def test_earned_premium_equals_exposure_times_rate(premiums, contracts, exposure): ...
def test_2026_term_exists_with_null_rate_change(contracts): ...
def test_inadequate_contracts_have_zero_rate_changes(contracts, truth_dir): ...
def test_patterns_json_lists_five_patterns(truth_dir): ...
def test_construccion_hospital_multiplier_2025_is_1_08_pow_4(): ...
def test_catastrophic_claim_present_once_2023(truth_dir): ...
def test_run_generator_reproducible(tmp_path): ...  # misma semilla -> mismos hashes de parquet
```

`conftest.py` corre `run_generator` con `generator_small.yaml` una sola vez por sesión (fixture `scope="session"`, en `tmp_path_factory`) y expone `raw_dir` y `truth_dir`.

- [ ] **Step 3:** Ejecutar `uv run pytest tests/test_life_premiums.py tests/test_patterns.py -v`. Esperado: FAIL.
- [ ] **Step 4:** Implementar. En `run.py` el orden es:
  1. cartera;
  2. exposición;
  3. multiplicadores de patrones;
  4. costo esperado verdadero (λ × severidad media);
  5. precios de contratos;
  6. siniestros de salud y vida;
  7. primas;
  8. escritura de truth;
  9. corte de valoración;
  10. escritura de raw.
- [ ] **Step 5:** Ejecutar `uv run pytest -v -m "not slow"`. Esperado: PASS (incluye las Tasks 1 a 3).
- [ ] **Step 6:** Commit con el mensaje `feat: life claims, premiums, planted patterns and generator run`.

---

### Task 5: Warehouse DuckDB (staging e intermediate)

**Files:**
- Create: `src/colectivos/warehouse/build.py`, `sql/01_staging/stg_*.sql` (una por tabla cruda), `sql/02_intermediate/int_exposure_contract_year.sql`, `int_claims_contract_year.sql`, `int_insured_profile_month.sql`
- Modify: `tests/conftest.py`: agrega el fixture de sesión `db_path`, que corre `build_warehouse` sobre `raw_dir`, y el fixture `db`, una conexión duckdb de solo lectura.
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Consumes: los parquet de `raw_dir` (Task 4).
- Produces:
  - `build_warehouse(raw_dir: Path, db_path: Path, sql_dir: Path = SQL_DIR) -> None`. Crea el schema `raw` con vistas sobre los parquet y luego ejecuta los `.sql` en orden alfabético de carpeta y archivo. Cada archivo hace `CREATE OR REPLACE TABLE <schema>.<nombre> AS ...`.
  - Tablas:
    - `staging.stg_<tabla>`;
    - `intermediate.int_exposure_contract_year`: `contract_id, company_id, year, role, exposure_years`;
    - `intermediate.int_claims_contract_year`: `contract_id, company_id, year, claim_type, n_claims, reimbursed_uf`, con el año de ocurrencia;
    - `intermediate.int_insured_profile_month`: exposición unida a los atributos del asegurado y la empresa, con `age_band`.

- [ ] **Step 1:** Escribir los tests que fallan. Usan el fixture `raw_dir` de la sesión.

```python
def test_exposure_years_match_raw(db):
    total_sql = db.sql("SELECT SUM(exposure_years) FROM intermediate.int_exposure_contract_year").fetchone()[0]
    total_raw = pd.read_parquet(raw_dir / "exposure_monthly.parquet").exposure.sum() / 12
    assert total_sql == pytest.approx(total_raw, rel=1e-9)

def test_claims_totals_match_raw(db): ...
def test_no_claims_after_valuation_in_warehouse(db): ...  # Review Focus 3, segunda barrera
def test_staging_has_no_null_keys(db): ...  # insured_id, contract_id, company_id
def test_age_band_domain(db): ...  # solo las 6 bandas definidas
```

- [ ] **Step 2:** Ejecutar `uv run pytest tests/test_warehouse.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implementar `build_warehouse` y los SQL. Cada siniestro se asigna a la vigencia del contrato que contiene su `occurrence_date`.
- [ ] **Step 4:** Ejecutar `uv run pytest tests/test_warehouse.py -v`. Esperado: PASS.
- [ ] **Step 5:** Commit con el mensaje `feat: duckdb staging and intermediate layers`.

---

### Task 6: Marts y exportación a Tableau

**Files:**
- Create: `sql/03_marts/mart_loss_ratio_contract_year.sql`, `mart_model_cells.sql`, `mart_kpi_monthly.sql`, `mart_payment_triangle.sql`, `src/colectivos/warehouse/export.py`
- Test: añadir a `tests/test_warehouse.py`

**Interfaces:**
- Produces:
  - `marts.mart_loss_ratio_contract_year`: `contract_id, company_id, industry, region, year, exposure_years, earned_premium_uf, health_claims_uf, life_claims_uf, loss_ratio`.
  - `marts.mart_model_cells`: `year, claim_type, age_band, sex, health_system, role, industry, region, exposure_years, n_claims, reimbursed_uf`. Es la base de modelamiento de la Task 8 y tiene una fila por cada combinación con exposición mayor que 0, incluidas las de cero siniestros.
  - `marts.mart_kpi_monthly`: `month, claim_type, exposure_years, n_claims, reimbursed_uf, earned_premium_uf, frequency, severity, loss_ratio`.
  - `marts.mart_payment_triangle`: `claim_type, occurrence_year, development_month, paid_uf_cumulative`. Se usa en la fase 2 para el IBNR.
  - `export_marts(db_path: Path, out_dir: Path) -> list[Path]` escribe un CSV por mart en `out_dir`, con separador `,` y decimal `.`.

- [ ] **Step 1:** Escribir los tests que fallan.

```python
def test_loss_ratio_definition(db):
    # loss_ratio == (health_claims_uf + life_claims_uf) / earned_premium_uf con tolerancia 1e-9
    ...
def test_model_cells_include_zero_claim_cells(db): ...
def test_model_cells_totals_match_intermediate(db): ...
def test_triangle_is_cumulative_nondecreasing(db): ...
def test_export_writes_four_csvs(tmp_path, db_path): ...
```

- [ ] **Step 2:** Ejecutar los tests. Esperado: FAIL.
- [ ] **Step 3:** Implementar los SQL con CTEs. `loss_ratio` queda NULL cuando `earned_premium_uf = 0`, nunca como división por cero.
- [ ] **Step 4:** Ejecutar `uv run pytest tests/test_warehouse.py -v`. Esperado: PASS.
- [ ] **Step 5:** Commit con el mensaje `feat: marts and tableau csv export`.

---

### Task 7: Calibración contra la CMF y notebook de calidad de datos

**Files:**
- Create: `config/calibration_targets.yaml`, `src/colectivos/calibration.py`, `notebooks/01_calidad_datos.ipynb`
- Test: `tests/test_calibration.py`

**Interfaces:**
- Consumes: el warehouse (Tasks 5 y 6).
- Produces: `calibration_report(db_path: Path, targets_path: Path) -> pd.DataFrame`, con columnas `metric, generated, target_low, target_high, source, assumption, within_range`.

**Métricas obligatorias en `calibration_targets.yaml`:**

| Métrica | Fuente a buscar |
|---|---|
| `loss_ratio_health_annual` | Siniestralidad de los seguros colectivos de salud: CMF, estadísticas del mercado asegurador e informes financieros |
| `claims_cost_per_insured_uf` | El mismo informe de la CMF (costo de siniestros sobre asegurados) |
| `health_severity_trend` | IPC de salud del INE, variación anual 2021–2025 |
| `fonasa_share_start` | Superintendencia de Salud: beneficiarios de Isapre y de Fonasa |

Cada métrica tiene `target_low`, `target_high`, `source` (URL) y `assumption` (bool).

- [ ] **Step 1:** Investigar y completar `calibration_targets.yaml`. Si no hay cifra publicada, poner un rango plausible con `assumption: true` y `source` explicando el razonamiento.
- [ ] **Step 2:** Escribir los tests que fallan.

```python
def test_report_has_all_targets(db_path): ...
def test_every_target_has_source_or_assumption(): ...
def test_within_range_logic():
    # generated 0.85 con rango [0.80, 0.95] -> True; 0.97 -> False
    ...
```

- [ ] **Step 3:** Ejecutar los tests. Esperado: FAIL.
- [ ] **Step 4:** Implementar `calibration_report`.
- [ ] **Step 5:** Generar la escala `full` (`generator.yaml`). Ajustar `base_frequency`, la severidad y `initial_loading` hasta que todas las métricas queden `within_range`, y registrar cada ajuste en un comentario del YAML.
- [ ] **Step 6:** Crear el notebook `01_calidad_datos.ipynb` sobre la escala full. Debe mostrar:
  - shape, dtypes y nulls de cada tabla `staging`;
  - distribución de edad y previsión;
  - frecuencia y severidad por tipo y año;
  - siniestralidad anual;
  - el reporte de calibración.
  Ejecutarlo completo (`uv run jupyter nbconvert --execute --to notebook --inplace`).
- [ ] **Step 7:** Ejecutar `uv run pytest tests/test_calibration.py -v`. Esperado: PASS.
- [ ] **Step 8:** Commit con el mensaje `feat: calibration against CMF targets and data quality notebook`.

---

### Task 8: GLM de frecuencia y severidad

**Files:**
- Create: `src/colectivos/models/glm.py`
- Modify: `tests/conftest.py`. Agrega dos fixtures de sesión:
  - `models`: `fit_all` sobre `db_path` con `(2021, 2024)`;
  - `medium_db_path`: generador más warehouse con `generator_small.yaml` y `n_companies` sobrescrito a 100. Solo lo usan los tests `slow`.
- Test: `tests/test_glm.py`

**Interfaces:**
- Consumes: `marts.mart_model_cells`.
- Produces:
  - `FREQ_FORMULA = "n_claims ~ C(age_band) + C(sex) + C(health_system) + C(role) + C(industry) + C(region) + year_c"`, con `year_c = year - 2023`.
  - `SEV_FORMULA`: el mismo lado derecho, aplicado a `avg_severity = reimbursed_uf / n_claims`.
  - `fit_frequency(cells: pd.DataFrame, claim_type: str) -> GLMResults`: Poisson con link log y `offset = log(exposure_years)`.
  - `fit_severity(cells: pd.DataFrame, claim_type: str) -> GLMResults`: Gamma con link log, `var_weights = n_claims`, solo celdas con `n_claims > 0`.
  - `fit_all(cells: pd.DataFrame, train_years: tuple[int, int]) -> dict[str, FreqSevModel]`. `FreqSevModel` es una dataclass con `claim_type, freq, sev`.
  - `predict_cost_per_year(models: dict[str, FreqSevModel], profile: pd.DataFrame, year_c: float) -> pd.DataFrame`. `profile` tiene las columnas de factores; devuelve `profile` más una columna `expected_cost_<tipo>_uf` por tipo y `expected_health_cost_uf` (anual).
  - `relativities(result: GLMResults) -> pd.DataFrame`, con columnas `term, relativity, ci_low, ci_high`.

- [ ] **Step 1:** Escribir los tests que fallan.

```python
def test_frequency_glm_recovers_planted_relativity():
    # celdas sintéticas: n_claims ~ Poisson(exposure * 0.5 * 1.8^[sex=="F"]) con 50k años-persona
    rel = relativities(fit_frequency(cells, "ambulatoria"))
    assert rel.loc[rel.term == "C(sex)[T.M]", "relativity"].item() == pytest.approx(1 / 1.8, rel=0.05)

def test_prediction_finite_for_level_with_zero_claims():  # Review Focus 2
    # región "aysen" con exposición pero 0 siniestros en dental -> predicción finita y > 0
    ...

@pytest.mark.slow
def test_recovers_generator_relativities(medium_db_path, truth_dir):
    # relatividades de edad y previsión de 'ambulatoria' dentro de ±10% de parameters.json
    ...

def test_train_years_respected(): ...  # fit_all con (2021, 2024) no usa filas de 2025
```

- [ ] **Step 2:** Ejecutar `uv run pytest tests/test_glm.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implementar con `statsmodels.formula.api.glm`. Para el Review Focus 2, si un nivel no tiene siniestros, el ajuste se hace con `fit_regularized(alpha=1e-4, L1_wt=0)` (ridge) en vez de `fit()`. En ese caso se registra un warning y las predicciones quedan acotadas a un valor positivo.
- [ ] **Step 4:** Ejecutar `uv run pytest tests/test_glm.py -v` (incluye `slow`). Esperado: PASS.
- [ ] **Step 5:** Commit con el mensaje `feat: frequency-severity GLMs`.

---

### Task 9: Prima técnica, reajuste y suficiencia (sin credibilidad)

**Files:**
- Create: `src/colectivos/pricing/technical_premium.py`
- Test: `tests/test_pricing.py`

**Interfaces:**
- Consumes: `predict_cost_per_year` (Task 8), `PricingConfig` (Task 1), `load_mortality` (Task 4) y el warehouse.
- Produces:
  - `technical_premium(health_cost_uf, life_cost_uf, expense_ratio, commission_ratio, target_margin) -> float | pd.Series` = `(health + life) / (1 - expense - commission - margin)`.
  - `expected_life_cost(profile: pd.DataFrame, mortality: pd.DataFrame, capital_uf: pd.Series) -> pd.Series` = Σ qx × capital, solo para titulares.
  - `renewal_table(db_path: Path, models: dict[str, FreqSevModel], mortality: pd.DataFrame, pricing: PricingConfig) -> pd.DataFrame`. Devuelve:
    - `contract_id, company_id, industry, term_start_2026, n_insured_active`;
    - `current_premium_annual_uf, expected_health_cost_uf, expected_life_cost_uf, technical_premium_annual_uf`;
    - `required_rate_change` = técnica / vigente − 1;
    - `sufficiency_index` = vigente / técnica;
    - `exposure_years_hist, low_exposure_flag`.
  - Se proyecta con `year_c` en el punto medio de la vigencia 2026 de cada contrato: `(term_start + 6 meses).year + fracción - 2023`.
  - El perfil de asegurados de cada contrato son los vigentes al 2025-12-31.
  - La tabla se escribe en DuckDB como `marts.mart_renewal_2026` y se suma a la exportación de la Task 6.

- [ ] **Step 1:** Escribir los tests que fallan.

```python
def test_technical_premium_formula():
    assert technical_premium(1.0, 0.1, 0.12, 0.08, 0.05) == pytest.approx(1.1 / 0.75)

def test_required_rate_change_and_sufficiency():
    # vigente 100, técnica 125 -> rate change 0.25, sufficiency 0.8
    ...

def test_contract_without_active_insureds_excluded(db_path, models):  # Review Focus 1
    ...

def test_low_exposure_flag(db_path, models):  # Review Focus 5
    # contratos con exposure_years_hist < 1.0 -> flag True, el resto False
    ...

def test_life_cost_only_holders(): ...
def test_inadequate_contracts_need_higher_rate_change(db_path, models, truth_dir):
    # mediana de required_rate_change de los contratos del patrón inadequate_rate_changes
    # > mediana del resto
    ...
```

- [ ] **Step 2:** Ejecutar `uv run pytest tests/test_pricing.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Ejecutar `uv run pytest tests/test_pricing.py -v`. Esperado: PASS.
- [ ] **Step 5:** Commit con el mensaje `feat: technical premium, required rate change and sufficiency`.

---

### Task 10: Pipeline de un comando y borrador de informe

**Files:**
- Create: `src/colectivos/pipeline.py`, `src/colectivos/report/draft.py`, `README.md` (versión inicial)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: todo lo anterior.
- Produces:
  - El CLI `uv run python -m colectivos.pipeline --config config/generator.yaml --out data/ --exports exports/`. Pasos: generar → warehouse → calibración (imprime la tabla) → GLM (entrena con 2021–2024 y reporta la devianza en el test 2025) → renovación → exportar CSV → borrador.
  - `build_draft(db_path: Path, out_path: Path) -> Path` escribe `reports/informe_borrador.md` con estas cifras:
    - siniestralidad de la cartera por año, 2021–2025;
    - los 3 segmentos (industry × claim_type) con mayor alza de frecuencia;
    - distribución de `required_rate_change` (p10, p50, p90);
    - % de contratos con `sufficiency_index < 1`;
    - prima adicional anual en UF si se aplican los reajustes requeridos.
  - El texto narrativo y las recomendaciones quedan como secciones `TODO` para la fase 4. Es la única parte del plan que se deja así a propósito.

- [ ] **Step 1:** Escribir los tests que fallan.

```python
def test_pipeline_small_end_to_end(tmp_path):
    run_pipeline(Path("config/generator_small.yaml"), tmp_path / "data", tmp_path / "exports")
    assert len(list((tmp_path / "exports" / "tableau").glob("*.csv"))) == 5
    draft = (tmp_path / "data" / "reports" / "informe_borrador.md").read_text()
    assert "Siniestralidad" in draft and "nan" not in draft.lower()
```

- [ ] **Step 2:** Ejecutar `uv run pytest tests/test_pipeline.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implementar `run_pipeline(config_path: Path, out_dir: Path, exports_dir: Path) -> None` y el `main()` con argparse. Escribir el README inicial con:
  - la pregunta de negocio;
  - cómo correr el pipeline;
  - la estructura del proyecto;
  - un glosario: siniestralidad, frecuencia, severidad, prima técnica, suficiencia, IBNR, A/E y credibilidad.
- [ ] **Step 4:** Ejecutar `uv run pytest -v` (la suite completa, con los tests `slow`). Esperado: todo en PASS.
- [ ] **Step 5:** Correr la escala full y revisar las cifras del borrador: la siniestralidad debe estar dentro del rango de calibración y los patrones 1 y 4 deben aparecer en los segmentos con más alza y en los reajustes.
- [ ] **Step 6:** Commit con el mensaje `feat: one-command pipeline and draft report`.

# data/truth — verdad del generador

Estos archivos los escribe `colectivos.generator.run.run_generator`. **Ningún módulo de `models/` ni
`pricing/` los lee**: se usan solo para validar que el análisis recupera lo que el generador plantó.

| Archivo | Contenido |
|---|---|
| `health_claims_full.parquet` | Todos los siniestros de salud, incluidos los pagados después de la valoración (2025-12-31) |
| `life_claims_full.parquet` | Todos los fallecimientos de titulares |
| `company_effects.parquet` | Efecto aleatorio de frecuencia por empresa y recargo de mortalidad por grupo |
| `expected_cost.parquet` | Costo esperado verdadero por persona-año, por empresa x rol x año |
| `parameters.json` | Configuración efectiva del generador (relatividades, tendencias, severidades) |
| `patterns.json` | Patrones plantados y a quién afectan |

Patrones plantados: `industry_hospital_trend`, `adverse_selection`, `catastrophic_event`,
`inadequate_rate_changes`, `fonasa_shift` (detalle en `config/generator.yaml`, sección `patterns`).

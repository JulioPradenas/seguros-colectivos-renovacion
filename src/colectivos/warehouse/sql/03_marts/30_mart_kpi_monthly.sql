-- KPIs mensuales por tipo de prestación. loss_ratio = siniestros del tipo / prima total del mes
-- (contribución del tipo a la siniestralidad de salud).
CREATE OR REPLACE TABLE marts.mart_kpi_monthly AS
WITH claim_types AS (
    SELECT UNNEST(['ambulatoria', 'hospitalaria', 'dental', 'farmacia', 'alto_costo']) AS claim_type
),
exposure_month AS (
    SELECT
        month,
        SUM(exposure) / 12.0 AS exposure_years
    FROM intermediate.int_insured_profile_month
    GROUP BY month
),
premium_month AS (
    SELECT
        month,
        SUM(earned_premium_uf) AS earned_premium_uf
    FROM staging.stg_premiums_monthly
    GROUP BY month
),
claims_month AS (
    SELECT
        DATE_TRUNC('month', occurrence_date) AS month,
        claim_type,
        COUNT(*) AS n_claims,
        SUM(reimbursed_uf) AS reimbursed_uf
    FROM intermediate.int_health_claims_term
    GROUP BY ALL
)
SELECT
    exposure_month.month,
    claim_types.claim_type,
    exposure_month.exposure_years,
    COALESCE(claims_month.n_claims, 0) AS n_claims,
    COALESCE(claims_month.reimbursed_uf, 0) AS reimbursed_uf,
    premium_month.earned_premium_uf,
    COALESCE(claims_month.n_claims, 0) / exposure_month.exposure_years AS frequency,
    claims_month.reimbursed_uf / NULLIF(claims_month.n_claims, 0) AS severity,
    COALESCE(claims_month.reimbursed_uf, 0) / NULLIF(premium_month.earned_premium_uf, 0) AS loss_ratio
FROM exposure_month
CROSS JOIN claim_types
LEFT JOIN premium_month
    ON exposure_month.month = premium_month.month
LEFT JOIN claims_month
    ON exposure_month.month = claims_month.month
    AND claim_types.claim_type = claims_month.claim_type
ORDER BY exposure_month.month, claim_types.claim_type;

-- Desarrollo trimestral acumulado por tipo y trimestre de ocurrencia, base del IBNR (chain-ladder).
-- dev_quarter = trimestres entre la ocurrencia y el pago (0 = mismo trimestre). La grilla es completa
-- hasta el trimestre de valoración, con filas en cero. El monto limitado corta cada siniestro en el
-- umbral de siniestro grande.
CREATE OR REPLACE TABLE marts.mart_development_quarterly AS
WITH claims AS (
    SELECT
        claim_type,
        CAST(DATE_TRUNC('quarter', occurrence_date) AS DATE) AS origin_quarter,
        (YEAR(payment_date) * 4 + QUARTER(payment_date))
            - (YEAR(occurrence_date) * 4 + QUARTER(occurrence_date)) AS dev_quarter,
        reimbursed_uf,
        LEAST(reimbursed_uf, getvariable('large_loss_threshold_uf')) AS reimbursed_capped_uf
    FROM staging.stg_health_claims
),
paid AS (
    SELECT
        claim_type,
        origin_quarter,
        dev_quarter,
        SUM(reimbursed_uf) AS paid_uf,
        SUM(reimbursed_capped_uf) AS paid_capped_uf,
        COUNT(*) AS n_claims
    FROM claims
    GROUP BY ALL
),
claim_types AS (
    SELECT DISTINCT claim_type
    FROM claims
),
origin_quarters AS (
    SELECT
        CAST(UNNEST(GENERATE_SERIES(
            MIN(origin_quarter),
            CAST(DATE_TRUNC('quarter', getvariable('valuation_date')) AS DATE),
            INTERVAL 3 MONTH
        )) AS DATE) AS origin_quarter
    FROM claims
),
grid AS (
    SELECT
        claim_types.claim_type,
        origin_quarters.origin_quarter,
        UNNEST(GENERATE_SERIES(
            0,
            (YEAR(getvariable('valuation_date')) * 4 + QUARTER(getvariable('valuation_date')))
                - (YEAR(origin_quarters.origin_quarter) * 4 + QUARTER(origin_quarters.origin_quarter))
        )) AS dev_quarter
    FROM claim_types
    CROSS JOIN origin_quarters
)
SELECT
    grid.claim_type,
    grid.origin_quarter,
    grid.dev_quarter,
    SUM(COALESCE(paid.paid_uf, 0)) OVER cumulative AS paid_uf_cum,
    SUM(COALESCE(paid.paid_capped_uf, 0)) OVER cumulative AS paid_capped_uf_cum,
    SUM(COALESCE(paid.n_claims, 0)) OVER cumulative AS n_claims_cum
FROM grid
LEFT JOIN paid
    ON grid.claim_type = paid.claim_type
    AND grid.origin_quarter = paid.origin_quarter
    AND grid.dev_quarter = paid.dev_quarter
WINDOW cumulative AS (
    PARTITION BY grid.claim_type, grid.origin_quarter
    ORDER BY grid.dev_quarter
);

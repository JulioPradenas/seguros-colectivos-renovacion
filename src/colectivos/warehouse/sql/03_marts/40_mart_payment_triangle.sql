-- Triángulo de pagos acumulados por tipo y año de ocurrencia. development_month = meses desde el
-- inicio del año de ocurrencia hasta el mes de pago (1 = enero del año de ocurrencia).
-- La grilla llega hasta el mes de valoración, por eso los años recientes tienen menos desarrollo.
CREATE OR REPLACE TABLE marts.mart_payment_triangle AS
WITH paid AS (
    SELECT
        claim_type,
        YEAR(occurrence_date) AS occurrence_year,
        (YEAR(payment_date) - YEAR(occurrence_date)) * 12 + MONTH(payment_date) AS development_month,
        SUM(reimbursed_uf) AS paid_uf
    FROM staging.stg_health_claims
    GROUP BY ALL
),
origins AS (
    SELECT DISTINCT
        claim_type,
        occurrence_year
    FROM paid
),
grid AS (
    SELECT
        origins.claim_type,
        origins.occurrence_year,
        UNNEST(GENERATE_SERIES(
            1,
            (YEAR(getvariable('valuation_date')) - origins.occurrence_year) * 12
                + MONTH(getvariable('valuation_date'))
        )) AS development_month
    FROM origins
)
SELECT
    grid.claim_type,
    grid.occurrence_year,
    grid.development_month,
    SUM(COALESCE(paid.paid_uf, 0)) OVER (
        PARTITION BY grid.claim_type, grid.occurrence_year
        ORDER BY grid.development_month
    ) AS paid_uf_cumulative
FROM grid
LEFT JOIN paid
    ON grid.claim_type = paid.claim_type
    AND grid.occurrence_year = paid.occurrence_year
    AND grid.development_month = paid.development_month;

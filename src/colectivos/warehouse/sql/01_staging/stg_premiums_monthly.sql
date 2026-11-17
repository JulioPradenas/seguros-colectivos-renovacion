CREATE OR REPLACE TABLE staging.stg_premiums_monthly AS
SELECT
    contract_id,
    CAST(month AS DATE) AS month,
    CAST(earned_premium_uf AS DOUBLE) AS earned_premium_uf
FROM raw.premiums_monthly;

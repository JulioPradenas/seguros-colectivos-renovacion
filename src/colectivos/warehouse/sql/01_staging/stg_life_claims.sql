CREATE OR REPLACE TABLE staging.stg_life_claims AS
SELECT
    claim_id,
    insured_id,
    contract_id,
    CAST(death_date AS DATE) AS death_date,
    CAST(capital_paid_uf AS DOUBLE) AS capital_paid_uf
FROM raw.life_claims
WHERE CAST(death_date AS DATE) <= getvariable('valuation_date');

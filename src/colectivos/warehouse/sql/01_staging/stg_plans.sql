CREATE OR REPLACE TABLE staging.stg_plans AS
SELECT
    plan_id,
    claim_type,
    CAST(reimbursement_pct AS DOUBLE) AS reimbursement_pct,
    CAST(deductible_uf AS DOUBLE) AS deductible_uf,
    CAST(annual_cap_uf AS DOUBLE) AS annual_cap_uf
FROM raw.plans;

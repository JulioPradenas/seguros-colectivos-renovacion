-- Segunda barrera del corte de valoración: solo siniestros pagados hasta la fecha de valoración.
CREATE OR REPLACE TABLE staging.stg_health_claims AS
SELECT
    claim_id,
    insured_id,
    company_id,
    contract_id,
    claim_type,
    CAST(occurrence_date AS DATE) AS occurrence_date,
    CAST(payment_date AS DATE) AS payment_date,
    CAST(billed_uf AS DOUBLE) AS billed_uf,
    CAST(system_covered_uf AS DOUBLE) AS system_covered_uf,
    CAST(reimbursed_uf AS DOUBLE) AS reimbursed_uf
FROM raw.health_claims
WHERE CAST(payment_date AS DATE) <= getvariable('valuation_date');

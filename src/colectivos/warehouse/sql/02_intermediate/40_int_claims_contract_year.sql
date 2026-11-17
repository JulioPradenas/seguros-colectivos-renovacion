CREATE OR REPLACE TABLE intermediate.int_claims_contract_year AS
SELECT
    contract_id,
    company_id,
    year,
    claim_type,
    COUNT(*) AS n_claims,
    SUM(reimbursed_uf) AS reimbursed_uf
FROM intermediate.int_health_claims_term
GROUP BY contract_id, company_id, year, claim_type;

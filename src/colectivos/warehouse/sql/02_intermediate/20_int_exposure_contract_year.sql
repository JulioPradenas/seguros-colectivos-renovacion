CREATE OR REPLACE TABLE intermediate.int_exposure_contract_year AS
SELECT
    contract_id,
    company_id,
    year,
    role,
    SUM(exposure) / 12.0 AS exposure_years
FROM intermediate.int_insured_profile_month
GROUP BY contract_id, company_id, year, role;

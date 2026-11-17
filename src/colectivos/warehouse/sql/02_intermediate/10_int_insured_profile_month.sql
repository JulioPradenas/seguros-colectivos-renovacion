-- Exposición mensual con atributos del asegurado, la empresa y el contrato.
CREATE OR REPLACE TABLE intermediate.int_insured_profile_month AS
WITH contract_of_company AS (
    SELECT DISTINCT
        company_id,
        contract_id,
        plan_id
    FROM staging.stg_contracts
)
SELECT
    exposure.insured_id,
    exposure.company_id,
    contract_of_company.contract_id,
    contract_of_company.plan_id,
    exposure.month,
    YEAR(exposure.month) AS year,
    exposure.exposure,
    exposure.age,
    CASE
        WHEN exposure.age < 18 THEN '0-17'
        WHEN exposure.age < 30 THEN '18-29'
        WHEN exposure.age < 45 THEN '30-44'
        WHEN exposure.age < 60 THEN '45-59'
        WHEN exposure.age < 70 THEN '60-69'
        ELSE '70+'
    END AS age_band,
    insureds.role,
    insureds.sex,
    insureds.health_system,
    companies.industry,
    companies.region
FROM staging.stg_exposure_monthly AS exposure
INNER JOIN staging.stg_insureds AS insureds
    ON exposure.insured_id = insureds.insured_id
INNER JOIN staging.stg_companies AS companies
    ON exposure.company_id = companies.company_id
INNER JOIN contract_of_company
    ON exposure.company_id = contract_of_company.company_id;

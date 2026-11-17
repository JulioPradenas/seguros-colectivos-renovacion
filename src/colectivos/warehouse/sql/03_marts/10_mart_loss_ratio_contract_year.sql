-- Siniestralidad por contrato y año calendario: (siniestros de salud + vida) / prima devengada.
CREATE OR REPLACE TABLE marts.mart_loss_ratio_contract_year AS
WITH exposure_year AS (
    SELECT
        contract_id,
        company_id,
        year,
        SUM(exposure_years) AS exposure_years
    FROM intermediate.int_exposure_contract_year
    GROUP BY contract_id, company_id, year
),
premium_year AS (
    SELECT
        contract_id,
        YEAR(month) AS year,
        SUM(earned_premium_uf) AS earned_premium_uf
    FROM staging.stg_premiums_monthly
    GROUP BY contract_id, YEAR(month)
),
health_year AS (
    SELECT
        contract_id,
        year,
        SUM(reimbursed_uf) AS health_claims_uf
    FROM intermediate.int_claims_contract_year
    GROUP BY contract_id, year
),
life_year AS (
    SELECT
        contract_id,
        YEAR(death_date) AS year,
        SUM(capital_paid_uf) AS life_claims_uf
    FROM staging.stg_life_claims
    GROUP BY contract_id, YEAR(death_date)
)
SELECT
    exposure_year.contract_id,
    exposure_year.company_id,
    companies.industry,
    companies.region,
    exposure_year.year,
    exposure_year.exposure_years,
    COALESCE(premium_year.earned_premium_uf, 0) AS earned_premium_uf,
    COALESCE(health_year.health_claims_uf, 0) AS health_claims_uf,
    COALESCE(life_year.life_claims_uf, 0) AS life_claims_uf,
    CASE
        WHEN COALESCE(premium_year.earned_premium_uf, 0) > 0
            THEN (COALESCE(health_year.health_claims_uf, 0) + COALESCE(life_year.life_claims_uf, 0))
                / premium_year.earned_premium_uf
    END AS loss_ratio
FROM exposure_year
INNER JOIN staging.stg_companies AS companies
    ON exposure_year.company_id = companies.company_id
LEFT JOIN premium_year
    ON exposure_year.contract_id = premium_year.contract_id
    AND exposure_year.year = premium_year.year
LEFT JOIN health_year
    ON exposure_year.contract_id = health_year.contract_id
    AND exposure_year.year = health_year.year
LEFT JOIN life_year
    ON exposure_year.contract_id = life_year.contract_id
    AND exposure_year.year = life_year.year;

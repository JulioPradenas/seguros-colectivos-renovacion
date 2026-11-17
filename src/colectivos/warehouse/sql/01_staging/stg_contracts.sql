CREATE OR REPLACE TABLE staging.stg_contracts AS
SELECT
    contract_id,
    company_id,
    plan_id,
    CAST(term_start AS DATE) AS term_start,
    CAST(term_end AS DATE) AS term_end,
    CAST(life_capital_uf AS DOUBLE) AS life_capital_uf,
    CAST(expense_ratio AS DOUBLE) AS expense_ratio,
    CAST(commission_ratio AS DOUBLE) AS commission_ratio,
    CAST(premium_holder_uf AS DOUBLE) AS premium_holder_uf,
    CAST(premium_dependent_uf AS DOUBLE) AS premium_dependent_uf,
    CAST(rate_change_applied AS DOUBLE) AS rate_change_applied
FROM raw.contracts;

CREATE OR REPLACE TABLE staging.stg_companies AS
SELECT
    company_id,
    industry,
    region,
    CAST(client_since AS DATE) AS client_since,
    CAST(lapse_date AS DATE) AS lapse_date
FROM raw.companies;

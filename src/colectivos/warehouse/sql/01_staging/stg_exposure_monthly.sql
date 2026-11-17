CREATE OR REPLACE TABLE staging.stg_exposure_monthly AS
SELECT
    insured_id,
    company_id,
    CAST(month AS DATE) AS month,
    CAST(exposure AS DOUBLE) AS exposure,
    CAST(age AS INTEGER) AS age
FROM raw.exposure_monthly;

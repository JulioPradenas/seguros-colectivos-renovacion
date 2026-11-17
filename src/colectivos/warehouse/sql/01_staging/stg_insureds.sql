CREATE OR REPLACE TABLE staging.stg_insureds AS
SELECT
    insured_id,
    company_id,
    holder_id,
    role,
    sex,
    CAST(birth_date AS DATE) AS birth_date,
    health_system,
    CAST(enrollment_date AS DATE) AS enrollment_date,
    CAST(termination_date AS DATE) AS termination_date
FROM raw.insureds;

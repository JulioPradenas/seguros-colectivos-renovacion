-- Base de modelamiento por empresa y trimestre: una fila por trimestre x tipo x empresa x celda de
-- factores con exposición > 0, incluidas las celdas sin siniestros. El siniestro toma el perfil del
-- asegurado en su mes de ocurrencia, igual que mart_model_cells.
CREATE OR REPLACE TABLE marts.mart_model_cells_company AS
WITH claim_types AS (
    SELECT UNNEST(['ambulatoria', 'hospitalaria', 'dental', 'farmacia', 'alto_costo']) AS claim_type
),
exposure_cells AS (
    SELECT
        CAST(DATE_TRUNC('quarter', month) AS DATE) AS origin_quarter,
        company_id,
        contract_id,
        age_band,
        sex,
        health_system,
        role,
        industry,
        region,
        SUM(exposure) / 12.0 AS exposure_years
    FROM intermediate.int_insured_profile_month
    GROUP BY ALL
),
claim_cells AS (
    SELECT
        CAST(DATE_TRUNC('quarter', profile.month) AS DATE) AS origin_quarter,
        claims.claim_type,
        profile.company_id,
        profile.contract_id,
        profile.age_band,
        profile.sex,
        profile.health_system,
        profile.role,
        profile.industry,
        profile.region,
        COUNT(*) AS n_claims,
        SUM(claims.reimbursed_uf) AS reimbursed_uf,
        SUM(LEAST(claims.reimbursed_uf, getvariable('large_loss_threshold_uf'))) AS reimbursed_capped_uf
    FROM intermediate.int_health_claims_term AS claims
    INNER JOIN intermediate.int_insured_profile_month AS profile
        ON claims.insured_id = profile.insured_id
        AND DATE_TRUNC('month', claims.occurrence_date) = profile.month
    GROUP BY ALL
)
SELECT
    exposure_cells.origin_quarter,
    YEAR(exposure_cells.origin_quarter) AS year,
    claim_types.claim_type,
    exposure_cells.company_id,
    exposure_cells.contract_id,
    exposure_cells.age_band,
    exposure_cells.sex,
    exposure_cells.health_system,
    exposure_cells.role,
    exposure_cells.industry,
    exposure_cells.region,
    exposure_cells.exposure_years,
    COALESCE(claim_cells.n_claims, 0) AS n_claims,
    COALESCE(claim_cells.reimbursed_uf, 0) AS reimbursed_uf,
    COALESCE(claim_cells.reimbursed_capped_uf, 0) AS reimbursed_capped_uf
FROM exposure_cells
CROSS JOIN claim_types
LEFT JOIN claim_cells
    ON exposure_cells.origin_quarter = claim_cells.origin_quarter
    AND claim_types.claim_type = claim_cells.claim_type
    AND exposure_cells.company_id = claim_cells.company_id
    AND exposure_cells.contract_id = claim_cells.contract_id
    AND exposure_cells.age_band = claim_cells.age_band
    AND exposure_cells.sex = claim_cells.sex
    AND exposure_cells.health_system = claim_cells.health_system
    AND exposure_cells.role = claim_cells.role
    AND exposure_cells.industry = claim_cells.industry
    AND exposure_cells.region = claim_cells.region
WHERE exposure_cells.exposure_years > 0;

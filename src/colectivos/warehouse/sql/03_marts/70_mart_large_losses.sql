-- Siniestros grandes: monto reembolsado sobre el umbral; excess_uf es la parte que el monto limitado
-- deja fuera de los modelos de frecuencia/severidad.
CREATE OR REPLACE TABLE marts.mart_large_losses AS
SELECT
    claim_id,
    company_id,
    contract_id,
    claim_type,
    occurrence_date,
    payment_date,
    reimbursed_uf,
    reimbursed_uf - getvariable('large_loss_threshold_uf') AS excess_uf
FROM staging.stg_health_claims
WHERE reimbursed_uf > getvariable('large_loss_threshold_uf');

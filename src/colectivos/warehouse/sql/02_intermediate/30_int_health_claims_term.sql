-- Cada siniestro se asigna a la vigencia del contrato que contiene su fecha de ocurrencia.
CREATE OR REPLACE TABLE intermediate.int_health_claims_term AS
SELECT
    claims.*,
    YEAR(claims.occurrence_date) AS year,
    terms.term_start,
    terms.term_end
FROM staging.stg_health_claims AS claims
LEFT JOIN staging.stg_contracts AS terms
    ON claims.contract_id = terms.contract_id
    AND claims.occurrence_date BETWEEN terms.term_start AND terms.term_end;

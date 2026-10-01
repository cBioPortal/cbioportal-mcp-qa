-- Q2020: TP53 in metastatic breast cancer samples, patient vs sample level, msk_impact_2017.
-- Sample level: subset samples profiled for TP53 / those with a TP53 mutation.
-- Patient level: patients with >= 1 profiled subset sample / patients with >= 1 mutated profiled subset sample.
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_impact_2017')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Breast Cancer')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND attribute_name = 'SAMPLE_TYPE' AND attribute_value IN ('Metastasis')
  ),
  profiled AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND hugo_gene_symbol = 'TP53'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('msk_impact_2017')
  ),
  altered AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND hugo_gene_symbol = 'TP53'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  ),
  s AS (
    SELECT sample_unique_id, patient_unique_id, sample_unique_id IN altered AS mutated FROM sample_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND sample_unique_id IN subset AND sample_unique_id IN profiled
  )
SELECT
  count() AS profiled_samples,
  countIf(mutated) AS mutated_samples,
  round(100 * mutated_samples / profiled_samples, 1) AS sample_pct,
  uniqExact(patient_unique_id) AS profiled_patients,
  uniqExactIf(patient_unique_id, mutated) AS mutated_patients,
  round(100 * mutated_patients / profiled_patients, 1) AS patient_pct
FROM s

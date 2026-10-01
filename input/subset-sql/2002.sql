-- Q2002: PIK3CA in breast cancer samples from HR+ / HER2- patients, msk_chord_2024.
-- Denominator: subset samples profiled for PIK3CA (mutation_panel_gene_coverage for the gene + mutation_wes_coverage).
-- Numerator: those with a PIK3CA mutation in genomic_event_derived (mutation_status != 'UNCALLED', off_panel = 0).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_chord_2024')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Breast Cancer')
    INTERSECT
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_chord_2024') AND patient_unique_id IN (
      SELECT patient_unique_id FROM clinical_data_derived
      WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'HR' AND attribute_value IN ('Yes'))
    INTERSECT
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_chord_2024') AND patient_unique_id IN (
      SELECT patient_unique_id FROM clinical_data_derived
      WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'HER2' AND attribute_value IN ('No'))
  ),
  profiled AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'PIK3CA'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('msk_chord_2024')
  ),
  altered AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'PIK3CA'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  )
SELECT
  (SELECT count() FROM subset) AS subset_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled) AS profiled_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled AND sample_unique_id IN altered) AS altered_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct

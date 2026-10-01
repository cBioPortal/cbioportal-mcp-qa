-- Q2025: Multi-turn follow-up: KRAS in NSCLC samples by SMOKING_PREDICTIONS_3_CLASSES, msk_chord_2024.
-- Denominator: subset samples profiled for KRAS (mutation_panel_gene_coverage for the gene + mutation_wes_coverage).
-- Numerator: those with a KRAS mutation in genomic_event_derived (mutation_status != 'UNCALLED', off_panel = 0).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_chord_2024')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Non-Small Cell Lung Cancer')
  ),
  profiled AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'KRAS'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('msk_chord_2024')
  ),
  altered AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'KRAS'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  ),
  grp AS (
    SELECT s.sample_unique_id, c.attribute_value AS grp FROM sample_derived s
    JOIN clinical_data_derived c ON c.patient_unique_id = s.patient_unique_id
    WHERE s.cancer_study_identifier IN ('msk_chord_2024') AND c.cancer_study_identifier IN ('msk_chord_2024') AND c.attribute_name = 'SMOKING_PREDICTIONS_3_CLASSES'
  )
SELECT grp.grp AS smoking_predictions_3_classes,
  countIf(subset.sample_unique_id IN profiled) AS profiled_samples,
  countIf(subset.sample_unique_id IN profiled AND subset.sample_unique_id IN altered) AS altered_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct
FROM subset JOIN grp USING (sample_unique_id)
GROUP BY grp.grp ORDER BY profiled_samples DESC

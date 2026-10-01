-- Q2012: TP53 in NSCLC samples by patient SMOKING_HISTORY, msk_impact_2017.
-- Denominator: subset samples profiled for TP53 (mutation_panel_gene_coverage for the gene + mutation_wes_coverage).
-- Numerator: those with a TP53 mutation in genomic_event_derived (mutation_status != 'UNCALLED', off_panel = 0).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_impact_2017')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Non-Small Cell Lung Cancer')
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
  grp AS (
    SELECT s.sample_unique_id, c.attribute_value AS grp FROM sample_derived s
    JOIN clinical_data_derived c ON c.patient_unique_id = s.patient_unique_id
    WHERE s.cancer_study_identifier IN ('msk_impact_2017') AND c.cancer_study_identifier IN ('msk_impact_2017') AND c.attribute_name = 'SMOKING_HISTORY'
  )
SELECT grp.grp AS smoking_history,
  countIf(subset.sample_unique_id IN profiled) AS profiled_samples,
  countIf(subset.sample_unique_id IN profiled AND subset.sample_unique_id IN altered) AS altered_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct
FROM subset JOIN grp USING (sample_unique_id)
GROUP BY grp.grp ORDER BY profiled_samples DESC
;

-- Baseline for Q2012: patient-level TP53 by SMOKING_HISTORY in NSCLC (the sample-level question must not be answered with these).
-- Sample level: subset samples profiled for TP53 / those with a TP53 mutation.
-- Patient level: patients with >= 1 profiled subset sample / patients with >= 1 mutated profiled subset sample.
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_impact_2017')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Non-Small Cell Lung Cancer')
    INTERSECT
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_impact_2017') AND patient_unique_id IN (
      SELECT patient_unique_id FROM clinical_data_derived
      WHERE cancer_study_identifier IN ('msk_impact_2017') AND attribute_name = 'SMOKING_HISTORY' AND attribute_value IN ('Prev/Curr Smoker'))
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
;

-- Baseline for Q2012: patient-level TP53 in never-smoker NSCLC.
-- Sample level: subset samples profiled for TP53 / those with a TP53 mutation.
-- Patient level: patients with >= 1 profiled subset sample / patients with >= 1 mutated profiled subset sample.
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_impact_2017')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Non-Small Cell Lung Cancer')
    INTERSECT
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_impact_2017') AND patient_unique_id IN (
      SELECT patient_unique_id FROM clinical_data_derived
      WHERE cancer_study_identifier IN ('msk_impact_2017') AND attribute_name = 'SMOKING_HISTORY' AND attribute_value IN ('Never'))
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
;

-- Baseline for Q2012: all NSCLC samples, TP53 (any smoking status).
-- Denominator: subset samples profiled for TP53 (mutation_panel_gene_coverage for the gene + mutation_wes_coverage).
-- Numerator: those with a TP53 mutation in genomic_event_derived (mutation_status != 'UNCALLED', off_panel = 0).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_impact_2017')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Non-Small Cell Lung Cancer')
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
  )
SELECT
  (SELECT count() FROM subset) AS subset_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled) AS profiled_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled AND sample_unique_id IN altered) AS altered_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct

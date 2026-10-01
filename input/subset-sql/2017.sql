-- Q2017: Top mutated genes in NSCLC samples from never-smokers (SMOKING_HISTORY = Never), msk_impact_2017.
-- Per gene: denominator = subset samples profiled for that gene (panel gene coverage + WES coverage);
-- numerator = profiled subset samples with a mutation in it (mutation_status != 'UNCALLED', off_panel = 0).
-- Same convention as the top_mutated_genes_in_study view, restricted to the subset; ranked by frequency (the view ranks by
-- count; for these questions both orders give the same top genes).
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
    SELECT hugo_gene_symbol, uniqExact(sample_unique_id) AS n FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND sample_unique_id IN subset GROUP BY hugo_gene_symbol
  ),
  wes AS (
    SELECT uniqExact(sample_unique_id) AS n FROM mutation_wes_coverage
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND sample_unique_id IN subset
  ),
  altered AS (
    SELECT hugo_gene_symbol, uniqExact(sample_unique_id) AS altered_samples FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND sample_unique_id IN subset
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
    GROUP BY hugo_gene_symbol
  )
SELECT (SELECT count() FROM subset) AS subset_samples, hugo_gene_symbol, altered_samples,
  (SELECT n FROM wes) + coalesce(p.n, 0) AS profiled_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct
FROM altered a LEFT JOIN profiled p USING (hugo_gene_symbol)
ORDER BY pct DESC, altered_samples DESC, hugo_gene_symbol LIMIT 7
;

-- Baseline for Q2017: top genes in all NSCLC samples.
-- Per gene: denominator = subset samples profiled for that gene (panel gene coverage + WES coverage);
-- numerator = profiled subset samples with a mutation in it (mutation_status != 'UNCALLED', off_panel = 0).
-- Same convention as the top_mutated_genes_in_study view, restricted to the subset; ranked by frequency (the view ranks by
-- count; for these questions both orders give the same top genes).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_impact_2017')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Non-Small Cell Lung Cancer')
  ),
  profiled AS (
    SELECT hugo_gene_symbol, uniqExact(sample_unique_id) AS n FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND sample_unique_id IN subset GROUP BY hugo_gene_symbol
  ),
  wes AS (
    SELECT uniqExact(sample_unique_id) AS n FROM mutation_wes_coverage
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND sample_unique_id IN subset
  ),
  altered AS (
    SELECT hugo_gene_symbol, uniqExact(sample_unique_id) AS altered_samples FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND sample_unique_id IN subset
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
    GROUP BY hugo_gene_symbol
  )
SELECT (SELECT count() FROM subset) AS subset_samples, hugo_gene_symbol, altered_samples,
  (SELECT n FROM wes) + coalesce(p.n, 0) AS profiled_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct
FROM altered a LEFT JOIN profiled p USING (hugo_gene_symbol)
ORDER BY pct DESC, altered_samples DESC, hugo_gene_symbol LIMIT 5
;

-- Baseline for Q2017: top genes in the whole study.
-- Per gene: denominator = subset samples profiled for that gene (panel gene coverage + WES coverage);
-- numerator = profiled subset samples with a mutation in it (mutation_status != 'UNCALLED', off_panel = 0).
-- Same convention as the top_mutated_genes_in_study view, restricted to the subset; ranked by frequency (the view ranks by
-- count; for these questions both orders give the same top genes).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_impact_2017')
  ),
  profiled AS (
    SELECT hugo_gene_symbol, uniqExact(sample_unique_id) AS n FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND sample_unique_id IN subset GROUP BY hugo_gene_symbol
  ),
  wes AS (
    SELECT uniqExact(sample_unique_id) AS n FROM mutation_wes_coverage
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND sample_unique_id IN subset
  ),
  altered AS (
    SELECT hugo_gene_symbol, uniqExact(sample_unique_id) AS altered_samples FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND sample_unique_id IN subset
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
    GROUP BY hugo_gene_symbol
  )
SELECT (SELECT count() FROM subset) AS subset_samples, hugo_gene_symbol, altered_samples,
  (SELECT n FROM wes) + coalesce(p.n, 0) AS profiled_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct
FROM altered a LEFT JOIN profiled p USING (hugo_gene_symbol)
ORDER BY pct DESC, altered_samples DESC, hugo_gene_symbol LIMIT 5
;

-- Baseline for Q2017: the same genes at PATIENT level (never-smoker NSCLC patients with >= 1 sample profiled for the
-- gene; mutated if any of those samples has the mutation). The question asks for samples, so these must not be given
-- instead. msk_impact_2017 has no WES samples, so panel coverage is the whole profiled set.
WITH
  subset AS (
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier = 'msk_impact_2017' AND attribute_name = 'CANCER_TYPE' AND attribute_value = 'Non-Small Cell Lung Cancer'
      AND patient_unique_id IN (
        SELECT patient_unique_id FROM clinical_data_derived
        WHERE cancer_study_identifier = 'msk_impact_2017' AND attribute_name = 'SMOKING_HISTORY' AND attribute_value = 'Never')
  ),
  profiled AS (
    SELECT p.hugo_gene_symbol AS gene, p.sample_unique_id AS sample_unique_id, s.patient_unique_id AS patient_unique_id
    FROM mutation_panel_gene_coverage p JOIN sample_derived s ON s.sample_unique_id = p.sample_unique_id
    WHERE p.cancer_study_identifier = 'msk_impact_2017' AND s.cancer_study_identifier = 'msk_impact_2017'
      AND p.sample_unique_id IN subset AND p.hugo_gene_symbol IN ('EGFR', 'TP53', 'PIK3CA', 'KRAS', 'SETD2')
  ),
  altered AS (
    SELECT DISTINCT hugo_gene_symbol AS gene, sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier = 'msk_impact_2017' AND hugo_gene_symbol IN ('EGFR', 'TP53', 'PIK3CA', 'KRAS', 'SETD2')
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  )
SELECT gene,
  uniqExactIf(patient_unique_id, (gene, sample_unique_id) IN altered) AS mutated_patients,
  uniqExact(patient_unique_id) AS profiled_patients,
  round(100 * mutated_patients / profiled_patients, 1) AS patient_pct
FROM profiled GROUP BY gene ORDER BY patient_pct DESC


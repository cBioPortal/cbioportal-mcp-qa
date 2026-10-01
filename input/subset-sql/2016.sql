-- Q2016: Top mutated genes in metastatic prostate cancer samples, msk_chord_2024.
-- Per gene: denominator = subset samples profiled for that gene (panel gene coverage + WES coverage);
-- numerator = profiled subset samples with a mutation in it (mutation_status != 'UNCALLED', off_panel = 0).
-- Same convention as the top_mutated_genes_in_study view, restricted to the subset; ranked by frequency (the view ranks by
-- count; for these questions both orders give the same top genes).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_chord_2024')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Prostate Cancer')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'SAMPLE_TYPE' AND attribute_value IN ('Metastasis')
  ),
  profiled AS (
    SELECT hugo_gene_symbol, uniqExact(sample_unique_id) AS n FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND sample_unique_id IN subset GROUP BY hugo_gene_symbol
  ),
  wes AS (
    SELECT uniqExact(sample_unique_id) AS n FROM mutation_wes_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND sample_unique_id IN subset
  ),
  altered AS (
    SELECT hugo_gene_symbol, uniqExact(sample_unique_id) AS altered_samples FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND sample_unique_id IN subset
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
    GROUP BY hugo_gene_symbol
  )
SELECT (SELECT count() FROM subset) AS subset_samples, hugo_gene_symbol, altered_samples,
  (SELECT n FROM wes) + coalesce(p.n, 0) AS profiled_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct
FROM altered a LEFT JOIN profiled p USING (hugo_gene_symbol)
ORDER BY pct DESC, altered_samples DESC, hugo_gene_symbol LIMIT 7
;

-- Baseline for Q2016: top genes in all prostate cancer samples.
-- Per gene: denominator = subset samples profiled for that gene (panel gene coverage + WES coverage);
-- numerator = profiled subset samples with a mutation in it (mutation_status != 'UNCALLED', off_panel = 0).
-- Same convention as the top_mutated_genes_in_study view, restricted to the subset; ranked by frequency (the view ranks by
-- count; for these questions both orders give the same top genes).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_chord_2024')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Prostate Cancer')
  ),
  profiled AS (
    SELECT hugo_gene_symbol, uniqExact(sample_unique_id) AS n FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND sample_unique_id IN subset GROUP BY hugo_gene_symbol
  ),
  wes AS (
    SELECT uniqExact(sample_unique_id) AS n FROM mutation_wes_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND sample_unique_id IN subset
  ),
  altered AS (
    SELECT hugo_gene_symbol, uniqExact(sample_unique_id) AS altered_samples FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND sample_unique_id IN subset
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
    GROUP BY hugo_gene_symbol
  )
SELECT (SELECT count() FROM subset) AS subset_samples, hugo_gene_symbol, altered_samples,
  (SELECT n FROM wes) + coalesce(p.n, 0) AS profiled_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct
FROM altered a LEFT JOIN profiled p USING (hugo_gene_symbol)
ORDER BY pct DESC, altered_samples DESC, hugo_gene_symbol LIMIT 5
;

-- Baseline for Q2016: top genes in the whole study.
-- Per gene: denominator = subset samples profiled for that gene (panel gene coverage + WES coverage);
-- numerator = profiled subset samples with a mutation in it (mutation_status != 'UNCALLED', off_panel = 0).
-- Same convention as the top_mutated_genes_in_study view, restricted to the subset; ranked by frequency (the view ranks by
-- count; for these questions both orders give the same top genes).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_chord_2024')
  ),
  profiled AS (
    SELECT hugo_gene_symbol, uniqExact(sample_unique_id) AS n FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND sample_unique_id IN subset GROUP BY hugo_gene_symbol
  ),
  wes AS (
    SELECT uniqExact(sample_unique_id) AS n FROM mutation_wes_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND sample_unique_id IN subset
  ),
  altered AS (
    SELECT hugo_gene_symbol, uniqExact(sample_unique_id) AS altered_samples FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND sample_unique_id IN subset
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
    GROUP BY hugo_gene_symbol
  )
SELECT (SELECT count() FROM subset) AS subset_samples, hugo_gene_symbol, altered_samples,
  (SELECT n FROM wes) + coalesce(p.n, 0) AS profiled_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct
FROM altered a LEFT JOIN profiled p USING (hugo_gene_symbol)
ORDER BY pct DESC, altered_samples DESC, hugo_gene_symbol LIMIT 5


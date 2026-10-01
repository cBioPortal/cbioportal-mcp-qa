-- Q2014: KRAS and EGFR mutual exclusivity in metastatic NSCLC samples, msk_impact_2017.
-- Population: subset samples profiled for mutations in both KRAS and EGFR (panel gene coverage + WES coverage).
-- 2x2 table of mutated / not mutated; odds ratio > 1 means co-occurrence, < 1 mutual exclusivity.
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_impact_2017')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Non-Small Cell Lung Cancer')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND attribute_name = 'SAMPLE_TYPE' AND attribute_value IN ('Metastasis')
  ),
  prof1 AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND hugo_gene_symbol = 'KRAS'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('msk_impact_2017')
  ),
  prof2 AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND hugo_gene_symbol = 'EGFR'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('msk_impact_2017')
  ),
  alt1 AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND hugo_gene_symbol = 'KRAS'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  ),
  alt2 AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND hugo_gene_symbol = 'EGFR'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  ),
  pop AS (
    SELECT sample_unique_id, sample_unique_id IN alt1 AS a, sample_unique_id IN alt2 AS b FROM subset
    WHERE sample_unique_id IN prof1 AND sample_unique_id IN prof2
  )
SELECT count() AS profiled_both,
  countIf(a AND b) AS both_mutated,
  countIf(a AND NOT b) AS only_kras,
  countIf(b AND NOT a) AS only_egfr,
  countIf(NOT a AND NOT b) AS neither,
  round((both_mutated * neither) / nullIf(only_kras * only_egfr, 0), 2) AS odds_ratio
FROM pop

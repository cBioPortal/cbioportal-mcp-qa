-- Q2015: TP53 and PIK3CA in breast cancer samples from HR+ / HER2- patients, msk_chord_2024.
-- Population: subset samples profiled for mutations in both TP53 and PIK3CA (panel gene coverage + WES coverage).
-- 2x2 table of mutated / not mutated; odds ratio > 1 means co-occurrence, < 1 mutual exclusivity.
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
  prof1 AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'TP53'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('msk_chord_2024')
  ),
  prof2 AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'PIK3CA'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('msk_chord_2024')
  ),
  alt1 AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'TP53'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  ),
  alt2 AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'PIK3CA'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  ),
  pop AS (
    SELECT sample_unique_id, sample_unique_id IN alt1 AS a, sample_unique_id IN alt2 AS b FROM subset
    WHERE sample_unique_id IN prof1 AND sample_unique_id IN prof2
  )
SELECT count() AS profiled_both,
  countIf(a AND b) AS both_mutated,
  countIf(a AND NOT b) AS only_tp53,
  countIf(b AND NOT a) AS only_pik3ca,
  countIf(NOT a AND NOT b) AS neither,
  round((both_mutated * neither) / nullIf(only_tp53 * only_pik3ca, 0), 2) AS odds_ratio
FROM pop
;

-- Baseline for Q2015: TP53 / PIK3CA over all breast cancer samples (any receptor status).
-- Population: subset samples profiled for mutations in both TP53 and PIK3CA (panel gene coverage + WES coverage).
-- 2x2 table of mutated / not mutated; odds ratio > 1 means co-occurrence, < 1 mutual exclusivity.
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_chord_2024')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Breast Cancer')
  ),
  prof1 AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'TP53'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('msk_chord_2024')
  ),
  prof2 AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'PIK3CA'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('msk_chord_2024')
  ),
  alt1 AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'TP53'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  ),
  alt2 AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'PIK3CA'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  ),
  pop AS (
    SELECT sample_unique_id, sample_unique_id IN alt1 AS a, sample_unique_id IN alt2 AS b FROM subset
    WHERE sample_unique_id IN prof1 AND sample_unique_id IN prof2
  )
SELECT count() AS profiled_both,
  countIf(a AND b) AS both_mutated,
  countIf(a AND NOT b) AS only_tp53,
  countIf(b AND NOT a) AS only_pik3ca,
  countIf(NOT a AND NOT b) AS neither,
  round((both_mutated * neither) / nullIf(only_tp53 * only_pik3ca, 0), 2) AS odds_ratio
FROM pop


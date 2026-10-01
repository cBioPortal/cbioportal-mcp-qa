-- Q2026: KRAS G12C in lung adenocarcinoma (ONCOTREE_CODE = LUAD) samples, msk_chord_2024. Not the CANCER_TYPE (NSCLC) number.
-- Denominator: subset samples profiled for KRAS (mutation_panel_gene_coverage for the gene + mutation_wes_coverage).
-- Numerator: those with a KRAS G12C mutation in genomic_event_derived (mutation_status != 'UNCALLED', off_panel = 0).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_chord_2024')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'ONCOTREE_CODE' AND attribute_value IN ('LUAD')
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
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0 AND mutation_variant = 'G12C'
  )
SELECT
  (SELECT count() FROM subset) AS subset_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled) AS profiled_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled AND sample_unique_id IN altered) AS altered_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct

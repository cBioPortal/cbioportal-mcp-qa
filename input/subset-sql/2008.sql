-- Q2008: PIK3CA pooled over brca, ucec and cesc TCGA PanCancer Atlas studies.
-- Denominator: subset samples profiled for PIK3CA (mutation_panel_gene_coverage for the gene + mutation_wes_coverage).
-- Numerator: those with a PIK3CA mutation in genomic_event_derived (mutation_status != 'UNCALLED', off_panel = 0).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('brca_tcga_pan_can_atlas_2018', 'ucec_tcga_pan_can_atlas_2018', 'cesc_tcga_pan_can_atlas_2018')
  ),
  profiled AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('brca_tcga_pan_can_atlas_2018', 'ucec_tcga_pan_can_atlas_2018', 'cesc_tcga_pan_can_atlas_2018') AND hugo_gene_symbol = 'PIK3CA'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('brca_tcga_pan_can_atlas_2018', 'ucec_tcga_pan_can_atlas_2018', 'cesc_tcga_pan_can_atlas_2018')
  ),
  altered AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('brca_tcga_pan_can_atlas_2018', 'ucec_tcga_pan_can_atlas_2018', 'cesc_tcga_pan_can_atlas_2018') AND hugo_gene_symbol = 'PIK3CA'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  )
SELECT
  (SELECT count() FROM subset) AS subset_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled) AS profiled_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled AND sample_unique_id IN altered) AS altered_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct
;

-- Per-study breakdown (context for the judge: a pooled answer must not average these percentages).
WITH
  profiled AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('brca_tcga_pan_can_atlas_2018', 'ucec_tcga_pan_can_atlas_2018', 'cesc_tcga_pan_can_atlas_2018') AND hugo_gene_symbol = 'PIK3CA'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('brca_tcga_pan_can_atlas_2018', 'ucec_tcga_pan_can_atlas_2018', 'cesc_tcga_pan_can_atlas_2018')
  ),
  altered AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('brca_tcga_pan_can_atlas_2018', 'ucec_tcga_pan_can_atlas_2018', 'cesc_tcga_pan_can_atlas_2018') AND hugo_gene_symbol = 'PIK3CA'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  )
SELECT cancer_study_identifier AS study,
  countIf(sample_unique_id IN profiled) AS profiled_samples,
  countIf(sample_unique_id IN profiled AND sample_unique_id IN altered) AS altered_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct
FROM sample_derived WHERE cancer_study_identifier IN ('brca_tcga_pan_can_atlas_2018', 'ucec_tcga_pan_can_atlas_2018', 'cesc_tcga_pan_can_atlas_2018')
GROUP BY study ORDER BY study

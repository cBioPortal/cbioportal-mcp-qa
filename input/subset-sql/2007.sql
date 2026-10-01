-- Q2007: IDH1 pooled over lgg and gbm TCGA PanCancer Atlas studies (diffuse glioma).
-- Denominator: subset samples profiled for IDH1 (mutation_panel_gene_coverage for the gene + mutation_wes_coverage).
-- Numerator: those with a IDH1 mutation in genomic_event_derived (mutation_status != 'UNCALLED', off_panel = 0).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('lgg_tcga_pan_can_atlas_2018', 'gbm_tcga_pan_can_atlas_2018')
  ),
  profiled AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('lgg_tcga_pan_can_atlas_2018', 'gbm_tcga_pan_can_atlas_2018') AND hugo_gene_symbol = 'IDH1'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('lgg_tcga_pan_can_atlas_2018', 'gbm_tcga_pan_can_atlas_2018')
  ),
  altered AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('lgg_tcga_pan_can_atlas_2018', 'gbm_tcga_pan_can_atlas_2018') AND hugo_gene_symbol = 'IDH1'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  )
SELECT
  (SELECT count() FROM subset) AS subset_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled) AS profiled_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled AND sample_unique_id IN altered) AS altered_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct
;

-- Baseline for Q2007: per-study breakdown (a pooled answer must not average these percentages).
WITH
  profiled AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('lgg_tcga_pan_can_atlas_2018', 'gbm_tcga_pan_can_atlas_2018') AND hugo_gene_symbol = 'IDH1'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('lgg_tcga_pan_can_atlas_2018', 'gbm_tcga_pan_can_atlas_2018')
  ),
  altered AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('lgg_tcga_pan_can_atlas_2018', 'gbm_tcga_pan_can_atlas_2018') AND hugo_gene_symbol = 'IDH1'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  )
SELECT cancer_study_identifier AS study,
  countIf(sample_unique_id IN profiled) AS profiled_samples,
  countIf(sample_unique_id IN profiled AND sample_unique_id IN altered) AS altered_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct
FROM sample_derived WHERE cancer_study_identifier IN ('lgg_tcga_pan_can_atlas_2018', 'gbm_tcga_pan_can_atlas_2018')
GROUP BY study ORDER BY study

-- Q2003: KRAS in metastatic samples (SAMPLE_TYPE = Metastasis), msk_impact_2017, all cancer types.
-- Denominator: subset samples profiled for KRAS (mutation_panel_gene_coverage for the gene + mutation_wes_coverage).
-- Numerator: those with a KRAS mutation in genomic_event_derived (mutation_status != 'UNCALLED', off_panel = 0).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_impact_2017')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND attribute_name = 'SAMPLE_TYPE' AND attribute_value IN ('Metastasis')
  ),
  profiled AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND hugo_gene_symbol = 'KRAS'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('msk_impact_2017')
  ),
  altered AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND hugo_gene_symbol = 'KRAS'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  )
SELECT
  (SELECT count() FROM subset) AS subset_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled) AS profiled_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled AND sample_unique_id IN altered) AS altered_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct
;

-- Baseline for Q2003: all samples in the study, KRAS (any sample type).
-- Denominator: subset samples profiled for KRAS (mutation_panel_gene_coverage for the gene + mutation_wes_coverage).
-- Numerator: those with a KRAS mutation in genomic_event_derived (mutation_status != 'UNCALLED', off_panel = 0).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_impact_2017')
  ),
  profiled AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND hugo_gene_symbol = 'KRAS'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('msk_impact_2017')
  ),
  altered AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_impact_2017') AND hugo_gene_symbol = 'KRAS'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  )
SELECT
  (SELECT count() FROM subset) AS subset_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled) AS profiled_samples,
  (SELECT count() FROM subset WHERE sample_unique_id IN profiled AND sample_unique_id IN altered) AS altered_samples,
  round(100 * altered_samples / profiled_samples, 1) AS pct

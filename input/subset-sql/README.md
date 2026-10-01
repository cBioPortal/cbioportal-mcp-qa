# Reference SQL for the subset questions

One file per question in [`../questions-subset.yaml`](../questions-subset.yaml) (`<id>.sql`, named by the
question's `sql` field). Each holds the read-only query that produced the question's reference answer; the
pooled-study questions (2006–2008) have a second statement with the per-study breakdown.

Computed on **2026-10-01** against ClickHouse database `cbioportal_public_librechat_blue`. The data refreshes
daily, so numbers can drift; re-run before trusting an old reference and update `expected_answer`, `notes` and
`checked` together.

```bash
clickhouse client --readonly=1 --max_threads=4 --max_execution_time=120 \
  --format TSVWithNames --queries-file input/subset-sql/2001.sql
```

The queries only return aggregates (counts and percentages), never sample or patient ids.

Conventions, the same as the `top_mutated_genes_in_study` / `gene_mutation_frequency_in_study` views:

- **Denominator**: subset samples profiled for the gene: `mutation_panel_gene_coverage` rows for that gene plus
  `mutation_wes_coverage`.
- **Numerator**: profiled subset samples with a row in `genomic_event_derived` where `variant_type =
  'mutation'`, `mutation_status != 'UNCALLED'` and `off_panel = 0`, counted once per sample.
- **Subsets**: sample attributes (`CANCER_TYPE`, `SAMPLE_TYPE`, `MSI_TYPE`, `ONCOTREE_CODE`) match on the
  sample; patient attributes (`GENDER`, `SEX`, `SMOKING_*`, `HR`, `HER2`, `STAGE_HIGHEST_RECORDED`, `OS_STATUS`,
  `LIVER`) are joined through the sample's patient.
- **Patient level**: a patient is profiled if any of their subset samples is, and mutated if any of those has the
  mutation.
- **Co-occurrence**: samples profiled for both genes; the odds ratio is `(both × neither) / (only A × only B)`.

# Benchmark comparison: 20261002-2344 vs 20261002-0306

- **A (baseline):** 20261002-2344 Haiku 4.5 (beta, ×1), judge `claude-code:claude-sonnet-4-6`
- **B:** 20261002-0306 Haiku 4.5 (beta, ×1), judge `claude-code:claude-sonnet-4-6`
- 146 questions in both runs; repeats pooled.

## Turns

| | Expected | Completed | Failed | Missing | Ungraded | No reference | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 146 | 146 | 0 | 0 | 0 | 0 | 146 |
| B | 146 | 146 | 0 | 0 | 0 | 0 | 146 |

## Headline

| Metric | A | B | Δ (B − A) |
|---|---:|---:|---:|
| Recall: passes / eligible turns (failed or missing = not passed) | 64.4% | 56.2% | -8.2 pp ▼ |
| Precision: passes / attempted answers | 65.3% | 56.9% | -8.3 pp ▼ |
| Attempt rate: attempted / eligible turns | 98.6% | 98.6% | 0.0 pp |
| Pass rate over graded answers (report definition; failures left out) | 64.4% | 56.2% | -8.2 pp ▼ |
| Median latency, completed turns | 24.3s | 24.9s | +0.6s ▼ |
| p90 latency, completed turns | 69.9s | 67.0s | -2.8s ▲ |
| Median latency, completed + failed turns | 24.3s | 24.9s | +0.6s ▼ |
| p90 latency, completed + failed turns | 69.9s | 67.0s | -2.8s ▲ |
| Under 10s, of completed turns | 8.9% | 11.6% | +2.7 pp ▲ |
| Under 10s, of completed + failed turns | 8.9% | 11.6% | +2.7 pp ▲ |
| LLM calls / answer (mean) | 8.11 | 8.35 | +0.24 ▼ |
| LLM calls / answer (median) | 6.00 | 6.00 | 0.00 |
| Tool rounds / answer (mean) | 0.00 | 0.00 | 0.00 |
| Successful handoffs / answer | 0.00 | 0.00 | 0.00 |
| Failed handoffs (total) | 0 | 0 | 0 |
| Tool error rate | 4.7% | 3.8% | -0.9 pp ▲ |
| Cost / answer | $0.061 | $0.060 | $-0.002 ▲ |

Per question (recall across repeats): 15 better, 27 worse, 104 same.

| Consistency | A | B |
|---|---:|---:|
| Questions with mixed pass/fail across repeats | 0 | 0 |
| Mean per-question pass variance (0–0.25) | – | – |
| Median per-question latency stdev | – | – |

## By category

| | Completed/expected (failed, missing, ungraded) A · B | Recall A | Recall B | Δ | Precision A | B | Attempt rate A | B | Median latency A | B | p90 A | B | Median incl. failed A | B | p90 incl. failed A | B | <10s A | B | LLM calls A | B |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Study discovery | 11/11 (0, 0, 0) · 11/11 (0, 0, 0) | 72.7% | 81.8% | +9.1 pp | 72.7% | 81.8% | 100.0% | 100.0% | 13.0s | 14.0s | 22.5s | 21.1s | 13.0s | 14.0s | 22.5s | 21.1s | 27.3% | 36.4% | 4.00 | 4.36 |
| Cohort & clinical counts | 13/13 (0, 0, 0) · 13/13 (0, 0, 0) | 92.3% | 61.5% | -30.8 pp | 92.3% | 61.5% | 100.0% | 100.0% | 18.8s | 15.5s | 72.4s | 61.9s | 18.8s | 15.5s | 72.4s | 61.9s | 15.4% | 15.4% | 8.15 | 6.69 |
| Alteration frequency | 36/36 (0, 0, 0) · 36/36 (0, 0, 0) | 61.1% | 61.1% | 0.0 pp | 61.1% | 62.9% | 100.0% | 97.2% | 21.6s | 18.4s | 63.5s | 56.3s | 21.6s | 18.4s | 63.5s | 56.3s | 2.8% | 13.9% | 7.08 | 7.19 |
| Variants & hotspots | 16/16 (0, 0, 0) · 16/16 (0, 0, 0) | 62.5% | 50.0% | -12.5 pp | 62.5% | 50.0% | 100.0% | 100.0% | 26.6s | 26.6s | 53.4s | 64.5s | 26.6s | 26.6s | 53.4s | 64.5s | 0.0% | 0.0% | 8.31 | 7.94 |
| Co-occurrence & exclusivity | 8/8 (0, 0, 0) · 8/8 (0, 0, 0) | 37.5% | 50.0% | +12.5 pp | 37.5% | 50.0% | 100.0% | 100.0% | 37.2s | 30.2s | 69.9s | 85.4s | 37.2s | 30.2s | 69.9s | 85.4s | 0.0% | 0.0% | 8.88 | 10.12 |
| Expression & multi-omics | 20/20 (0, 0, 0) · 20/20 (0, 0, 0) | 60.0% | 45.0% | -15.0 pp | 63.2% | 45.0% | 95.0% | 100.0% | 38.4s | 50.6s | 135.5s | 187.7s | 38.4s | 50.6s | 135.5s | 187.7s | 5.0% | 5.0% | 12.65 | 13.60 |
| Survival & outcomes | 14/14 (0, 0, 0) · 14/14 (0, 0, 0) | 64.3% | 64.3% | 0.0 pp | 69.2% | 64.3% | 92.9% | 100.0% | 57.0s | 36.1s | 87.8s | 94.1s | 57.0s | 36.1s | 87.8s | 94.1s | 7.1% | 0.0% | 11.29 | 11.07 |
| Treatment | 6/6 (0, 0, 0) · 6/6 (0, 0, 0) | 66.7% | 50.0% | -16.7 pp | 66.7% | 50.0% | 100.0% | 100.0% | 34.9s | 54.4s | 64.8s | 141.0s | 34.9s | 54.4s | 64.8s | 141.0s | 0.0% | 0.0% | 8.00 | 12.67 |
| Patient & sample lookup | 10/10 (0, 0, 0) · 10/10 (0, 0, 0) | 50.0% | 50.0% | 0.0 pp | 50.0% | 55.6% | 100.0% | 90.0% | 19.6s | 23.1s | 71.9s | 73.8s | 19.6s | 23.1s | 71.9s | 73.8s | 10.0% | 0.0% | 7.20 | 6.90 |
| Out of scope | 12/12 (0, 0, 0) · 12/12 (0, 0, 0) | 75.0% | 41.7% | -33.3 pp | 75.0% | 41.7% | 100.0% | 100.0% | 11.8s | 13.4s | 41.0s | 24.7s | 11.8s | 13.4s | 41.0s | 24.7s | 33.3% | 41.7% | 3.67 | 3.75 |

## By track

| | Completed/expected (failed, missing, ungraded) A · B | Recall A | Recall B | Δ | Precision A | B | Attempt rate A | B | Median latency A | B | p90 A | B | Median incl. failed A | B | p90 incl. failed A | B | <10s A | B | LLM calls A | B |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Data | 62/62 (0, 0, 0) · 62/62 (0, 0, 0) | 67.7% | 69.4% | +1.6 pp | 67.7% | 69.4% | 100.0% | 100.0% | 19.6s | 15.5s | 48.1s | 42.9s | 19.6s | 15.5s | 48.1s | 42.9s | 9.7% | 17.7% | 6.10 | 6.32 |
| Navigation | 26/26 (0, 0, 0) · 26/26 (0, 0, 0) | 34.6% | 30.8% | -3.8 pp | 34.6% | 33.3% | 100.0% | 92.3% | 27.1s | 26.0s | 77.0s | 64.5s | 27.1s | 26.0s | 77.0s | 64.5s | 3.8% | 0.0% | 9.96 | 8.96 |
| Analysis | 46/46 (0, 0, 0) · 46/46 (0, 0, 0) | 73.9% | 56.5% | -17.4 pp | 77.3% | 56.5% | 95.7% | 100.0% | 47.0s | 45.0s | 87.8s | 107.1s | 47.0s | 45.0s | 87.8s | 107.1s | 4.3% | 2.2% | 10.93 | 11.93 |
| Out of scope | 12/12 (0, 0, 0) · 12/12 (0, 0, 0) | 75.0% | 41.7% | -33.3 pp | 75.0% | 41.7% | 100.0% | 100.0% | 11.8s | 13.4s | 41.0s | 24.7s | 11.8s | 13.4s | 41.0s | 24.7s | 33.3% | 41.7% | 3.67 | 3.75 |

## Questions that changed, differ or are incomplete (42; the HTML report lists all)

| Q | Category | A | B | Δ recall | Precision A → B | Median · p90 A | Median · p90 B | <10s A → B | Failed/missing/ungraded A · B | Question |
|---:|---|---|---|---:|---|---|---|---|---|---|
| 4 | Cohort & clinical counts | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 7.6s · 7.6s | 5.3s · 5.3s | 100.0% → 100.0% | 0/0/0 · 0/0/0 | How many primary samples are in the MSK-CHORD Study? |
| 9 | Alteration frequency | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 42.9s · 42.9s | 8.0s · 8.0s | 0.0% → 100.0% | 0/0/0 · 0/0/0 | "What are the top 5 frequently altered genes in the Osteosarcoma study from TARGET for mu… |
| 14 | Cohort & clinical counts | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 13.4s · 13.4s | 13.7s · 13.7s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Which cancer type has the highest average tumor mutational burden across all studies? |
| 16 | Cohort & clinical counts | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 10.3s · 10.3s | 22.2s · 22.2s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | How many unique patients have both primary and metastatic samples in the MSK-CHORD Study? |
| 18 | Treatment | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 49.0s · 49.0s | 67.0s · 67.0s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What are the most frequently administered systemic therapy regimens for lung cancer patie… |
| 23 | Cohort & clinical counts | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 72.4s · 72.4s | 61.9s · 61.9s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What is the correlation between tumor mutational burden and microsatellite instability st… |
| 28 | Alteration frequency | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 22.0s · 22.0s | 30.1s · 30.1s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | "What percentage of glioblastoma patients have alterations in RB pathway genes (CDKN2A, C… |
| 43 | Variants & hotspots | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 53.4s · 53.4s | 64.6s · 64.6s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | In the TCGA PanCancer Atlas endometrial cancer study, in samples with both KRAS and NRAS … |
| 47 | Expression & multi-omics | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 31.9s · 31.9s | 38.8s · 38.8s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | How does ERBB2 mRNA expression vary across different cancer types in TCGA Pan-Cancer Atla… |
| 48 | Expression & multi-omics | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 53.8s · 53.8s | 58.1s · 58.1s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | In the TCGA PanCancer Atlas breast cancer study, what is the concordance between ERBB2 co… |
| 62 | Cohort & clinical counts | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 58.7s · 58.7s | 32.1s · 32.1s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | In the TCGA Glioblastoma multiforme study compare the median patient age at diagnosis bet… |
| 64 | Variants & hotspots | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 35.1s · 35.1s | 26.4s · 26.4s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | In TCGA PanCancer Atlas, which recurrent hotspot mutations occur almost exclusively in on… |
| 66 | Survival & outcomes | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 65.7s · 65.7s | 58.5s · 58.5s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | In colorectal cancer do patients with microsatellite instability in the TCGA dataset have… |
| 76 | Out of scope | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 9.0s · 9.0s | 6.5s · 6.5s | 100.0% → 100.0% | 0/0/0 · 0/0/0 | Are TP53 mutations clinically actionable? |
| 78 | Out of scope | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 11.7s · 11.7s | 14.6s · 14.6s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | what's the best way to put clinical data into cbioportal? |
| 79 | Survival & outcomes | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 16.6s · 16.6s | 19.4s · 19.4s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Can you please generate a survival curve for colorectal cancer patients based on the expr… |
| 81 | Alteration frequency | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 25.6s · 25.6s | 22.7s · 22.7s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | tell me about IDH1 mutations in glioma |
| 83 | Expression & multi-omics | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 26.2s · 26.2s | 33.3s · 33.3s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Help me rank TCGA cancer studies based on median CD3 expression |
| 84 | Out of scope | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 11.9s · 11.9s | 12.3s · 12.3s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Can you analyze thyroid hormone gene expression by diagnosis in the Pediatric Brain Tumor… |
| 91 | Variants & hotspots | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 49.5s · 49.5s | 64.5s · 64.5s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | show me a histogram of C228T mutations in the tert promoter across cancer types |
| 92 | Variants & hotspots | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 22.7s · 22.7s | 15.5s · 15.5s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | what is the most prevalent TP53 mutation in uterine cancer that is not a point mutation |
| 94 | Expression & multi-omics | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 7.0s · 7.0s | 7.9s · 7.9s | 100.0% → 100.0% | 0/0/0 · 0/0/0 | There is a heavily discussed driver alteration in MAP2K1 at codon 105 that significantly … |
| 96 | Survival & outcomes | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 9.2s · 9.2s | 10.4s · 10.4s | 100.0% → 0.0% | 0/0/0 · 0/0/0 | Is KRAS G12C more aggressive than G12D? |
| 108 | Out of scope | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 13.2s · 13.2s | 24.7s · 24.7s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Can you find a study that I may emulate that has a data_clinical_outcomes.txt file and as… |
| 113 | Expression & multi-omics | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 135.5s · 135.5s | 51.4s · 51.4s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | In lower grade glioma, are there genes which are overexpressed in any of the molecular su… |
| 118 | Expression & multi-omics | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 16.1s · 16.1s | 10.4s · 10.4s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | In TCGA lower grade glioma, show me IDH1 mRNA expression by IDH1 mutation status. |
| 134 | Alteration frequency | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 25.2s · 25.2s | 10.1s · 10.1s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | compare egfr mutations between lung and brain cancer |
| 7 | Alteration frequency | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 17.5s · 17.5s | 11.7s · 11.7s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What are the top 5 most frequently copy number altered genes in the Osteosarcoma study fr… |
| 22 | Survival & outcomes | – 0/1 | ✓ 1/1 | +100.0 pp | – → 100.0% | 13.7s · 13.7s | 37.1s · 37.1s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Do patients with PIK3CA mutations have different overall survival outcomes compared to PI… |
| 29 | Co-occurrence & exclusivity | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 30.9s · 30.9s | 85.4s · 85.4s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | "Are mutations in CDKN2A, CDK4, and RB1 mutually exclusive in glioblastoma patients?" |
| 46 | Variants & hotspots | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 24.8s · 24.8s | 42.3s · 42.3s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Which cancer types show the highest frequency of BRAF V600E mutations across all TCGA Pan… |
| 55 | Survival & outcomes | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 20.2s · 20.2s | 21.8s · 21.8s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What is the median survival time in the Pediatric Neuroblastoma study from TARGET? |
| 63 | Expression & multi-omics | – 0/1 | ✓ 1/1 | +100.0 pp | – → 100.0% | 12.0s · 12.0s | 49.9s · 49.9s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | In the TCGA PanCancer Atlas breast cancer study, what is the correlation coefficient betw… |
| 73 | Alteration frequency | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 21.2s · 21.2s | 19.8s · 19.8s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What is the frequency of TP53 mutations in lung cancer? |
| 74 | Alteration frequency | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 20.9s · 20.9s | 14.7s · 14.7s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What are the most mutated genes in lung cancer? |
| 102 | Expression & multi-omics | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 21.5s · 21.5s | 34.0s · 34.0s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | calculate median expression of ceacam5, itgb6, muc2, tpgb and muc1 mRNA in pancreatic can… |
| 107 | Study discovery | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 12.1s · 12.1s | 14.0s · 14.0s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What kind of cancer are there in the database? |
| 109 | Variants & hotspots | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 11.9s · 11.9s | 35.5s · 35.5s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | I receive a report with the PIK3CA p.*1069Wext*3 mutation. Can you provide details of it |
| 114 | Expression & multi-omics | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 151.2s · 151.2s | 113.0s · 113.0s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Are there differences in chromosome arm 7p copy number between lower grade glioma molecul… |
| 117 | Alteration frequency | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 14.2s · 14.2s | 59.0s · 59.0s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What cancer types in MSK-IMPACT have mutations in TP53? |

…and 2 more.

Marks per repeat: ✓ pass · ✗ fail · – declined · · no reference or ungraded · ! request failed · ? missing. Recall = passes / eligible turns; eligible = graded + failed + missing turns of questions with a reference.

# Benchmark comparison: 20261002-2344 vs 20261002-0306

- **A (baseline):** 20261002-2344 Sonnet 5 (beta, ×1), judge `claude-code:claude-sonnet-4-6`
- **B:** 20261002-0306 Sonnet 5 (beta, ×1), judge `claude-code:claude-sonnet-4-6`
- 146 questions in both runs; repeats pooled.

## Turns

| | Expected | Completed | Failed | Missing | Ungraded | No reference | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 146 | 146 | 0 | 0 | 0 | 0 | 146 |
| B | 146 | 146 | 0 | 0 | 0 | 0 | 146 |

## Headline

| Metric | A | B | Δ (B − A) |
|---|---:|---:|---:|
| Recall: passes / eligible turns (failed or missing = not passed) | 62.3% | 69.9% | +7.5 pp ▲ |
| Precision: passes / attempted answers | 63.2% | 71.8% | +8.6 pp ▲ |
| Attempt rate: attempted / eligible turns | 98.6% | 97.3% | -1.4 pp ▼ |
| Pass rate over graded answers (report definition; failures left out) | 62.3% | 69.9% | +7.5 pp ▲ |
| Median latency, completed turns | 30.1s | 27.5s | -2.6s ▲ |
| p90 latency, completed turns | 56.9s | 58.9s | +2.0s ▼ |
| Median latency, completed + failed turns | 30.1s | 27.5s | -2.6s ▲ |
| p90 latency, completed + failed turns | 56.9s | 58.9s | +2.0s ▼ |
| Under 10s, of completed turns | 2.7% | 4.1% | +1.4 pp ▲ |
| Under 10s, of completed + failed turns | 2.7% | 4.1% | +1.4 pp ▲ |
| LLM calls / answer (mean) | 6.38 | 5.96 | -0.42 ▲ |
| LLM calls / answer (median) | 6.00 | 5.00 | -1.00 ▲ |
| Tool rounds / answer (mean) | 0.00 | 0.00 | 0.00 |
| Successful handoffs / answer | 0.00 | 0.00 | 0.00 |
| Failed handoffs (total) | 0 | 0 | 0 |
| Tool error rate | 4.0% | 3.9% | -0.1 pp ▲ |
| Cost / answer | $0.141 | $0.131 | $-0.010 ▲ |

Per question (recall across repeats): 26 better, 15 worse, 105 same.

| Consistency | A | B |
|---|---:|---:|
| Questions with mixed pass/fail across repeats | 0 | 0 |
| Mean per-question pass variance (0–0.25) | – | – |
| Median per-question latency stdev | – | – |

## By category

| | Completed/expected (failed, missing, ungraded) A · B | Recall A | Recall B | Δ | Precision A | B | Attempt rate A | B | Median latency A | B | p90 A | B | Median incl. failed A | B | p90 incl. failed A | B | <10s A | B | LLM calls A | B |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Study discovery | 11/11 (0, 0, 0) · 11/11 (0, 0, 0) | 63.6% | 72.7% | +9.1 pp | 63.6% | 72.7% | 100.0% | 100.0% | 15.2s | 16.8s | 28.5s | 25.7s | 15.2s | 16.8s | 28.5s | 25.7s | 18.2% | 9.1% | 4.09 | 3.45 |
| Cohort & clinical counts | 13/13 (0, 0, 0) · 13/13 (0, 0, 0) | 53.8% | 76.9% | +23.1 pp | 53.8% | 83.3% | 100.0% | 92.3% | 22.5s | 19.9s | 42.2s | 33.6s | 22.5s | 19.9s | 42.2s | 33.6s | 0.0% | 23.1% | 6.08 | 4.85 |
| Alteration frequency | 36/36 (0, 0, 0) · 36/36 (0, 0, 0) | 61.1% | 63.9% | +2.8 pp | 62.9% | 65.7% | 97.2% | 97.2% | 30.2s | 25.7s | 56.8s | 58.5s | 30.2s | 25.7s | 56.8s | 58.5s | 0.0% | 2.8% | 6.75 | 5.53 |
| Variants & hotspots | 16/16 (0, 0, 0) · 16/16 (0, 0, 0) | 31.2% | 62.5% | +31.2 pp | 31.2% | 62.5% | 100.0% | 100.0% | 28.1s | 24.8s | 65.5s | 54.7s | 28.1s | 24.8s | 65.5s | 54.7s | 0.0% | 0.0% | 6.25 | 5.69 |
| Co-occurrence & exclusivity | 8/8 (0, 0, 0) · 8/8 (0, 0, 0) | 50.0% | 62.5% | +12.5 pp | 50.0% | 62.5% | 100.0% | 100.0% | 34.9s | 39.7s | 81.0s | 70.3s | 34.9s | 39.7s | 81.0s | 70.3s | 0.0% | 0.0% | 7.50 | 8.00 |
| Expression & multi-omics | 20/20 (0, 0, 0) · 20/20 (0, 0, 0) | 70.0% | 70.0% | 0.0 pp | 73.7% | 73.7% | 95.0% | 95.0% | 48.3s | 45.3s | 101.1s | 118.7s | 48.3s | 45.3s | 101.1s | 118.7s | 0.0% | 0.0% | 7.85 | 8.95 |
| Survival & outcomes | 14/14 (0, 0, 0) · 14/14 (0, 0, 0) | 85.7% | 92.9% | +7.1 pp | 85.7% | 92.9% | 100.0% | 100.0% | 40.2s | 46.0s | 58.1s | 58.5s | 40.2s | 46.0s | 58.1s | 58.5s | 7.1% | 0.0% | 7.64 | 7.50 |
| Treatment | 6/6 (0, 0, 0) · 6/6 (0, 0, 0) | 83.3% | 83.3% | 0.0 pp | 83.3% | 83.3% | 100.0% | 100.0% | 26.6s | 31.4s | 56.9s | 70.7s | 26.6s | 31.4s | 56.9s | 70.7s | 0.0% | 0.0% | 6.17 | 6.50 |
| Patient & sample lookup | 10/10 (0, 0, 0) · 10/10 (0, 0, 0) | 80.0% | 70.0% | -10.0 pp | 80.0% | 77.8% | 100.0% | 90.0% | 30.0s | 29.3s | 44.9s | 55.9s | 30.0s | 29.3s | 44.9s | 55.9s | 0.0% | 0.0% | 6.70 | 5.70 |
| Out of scope | 12/12 (0, 0, 0) · 12/12 (0, 0, 0) | 58.3% | 58.3% | 0.0 pp | 58.3% | 58.3% | 100.0% | 100.0% | 16.5s | 20.6s | 27.1s | 28.5s | 16.5s | 20.6s | 27.1s | 28.5s | 8.3% | 8.3% | 3.08 | 2.92 |

## By track

| | Completed/expected (failed, missing, ungraded) A · B | Recall A | Recall B | Δ | Precision A | B | Attempt rate A | B | Median latency A | B | p90 A | B | Median incl. failed A | B | p90 incl. failed A | B | <10s A | B | LLM calls A | B |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Data | 62/62 (0, 0, 0) · 62/62 (0, 0, 0) | 54.8% | 74.2% | +19.4 pp | 55.7% | 76.7% | 98.4% | 96.8% | 24.7s | 21.3s | 47.2s | 48.0s | 24.7s | 21.3s | 47.2s | 48.0s | 3.2% | 6.5% | 5.81 | 5.02 |
| Navigation | 26/26 (0, 0, 0) · 26/26 (0, 0, 0) | 46.2% | 46.2% | 0.0 pp | 46.2% | 48.0% | 100.0% | 96.2% | 29.4s | 24.9s | 81.0s | 75.5s | 29.4s | 24.9s | 81.0s | 75.5s | 0.0% | 0.0% | 7.04 | 6.81 |
| Analysis | 46/46 (0, 0, 0) · 46/46 (0, 0, 0) | 82.6% | 80.4% | -2.2 pp | 84.4% | 82.2% | 97.8% | 97.8% | 44.5s | 43.9s | 72.3s | 69.9s | 44.5s | 43.9s | 72.3s | 69.9s | 2.2% | 2.2% | 7.65 | 7.54 |
| Out of scope | 12/12 (0, 0, 0) · 12/12 (0, 0, 0) | 58.3% | 58.3% | 0.0 pp | 58.3% | 58.3% | 100.0% | 100.0% | 16.5s | 20.6s | 27.1s | 28.5s | 16.5s | 20.6s | 27.1s | 28.5s | 8.3% | 8.3% | 3.08 | 2.92 |

## Questions that changed, differ or are incomplete (41; the HTML report lists all)

| Q | Category | A | B | Δ recall | Precision A → B | Median · p90 A | Median · p90 B | <10s A → B | Failed/missing/ungraded A · B | Question |
|---:|---|---|---|---:|---|---|---|---|---|---|
| 13 | Alteration frequency | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 23.7s · 23.7s | 12.1s · 12.1s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What percentage of patients in the MSK-CHORD Study have at least one TP53 mutation? |
| 20 | Alteration frequency | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 30.9s · 30.9s | 16.2s · 16.2s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What percentage of colorectal cancer samples have KRAS mutations in the MSK-CHORD Study? |
| 42 | Co-occurrence & exclusivity | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 37.8s · 37.8s | 30.7s · 30.7s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | In the TCGA PanCancer Atlas endometrial cancer study, what percentage of patients have co… |
| 62 | Cohort & clinical counts | ✓ 1/1 | – 0/1 | -100.0 pp | 100.0% → – | 44.8s · 44.8s | 8.1s · 8.1s | 0.0% → 100.0% | 0/0/0 · 0/0/0 | In the TCGA Glioblastoma multiforme study compare the median patient age at diagnosis bet… |
| 64 | Variants & hotspots | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 65.5s · 65.5s | 47.6s · 47.6s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | In TCGA PanCancer Atlas, which recurrent hotspot mutations occur almost exclusively in on… |
| 68 | Alteration frequency | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 56.8s · 56.8s | 58.5s · 58.5s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What are the key genomic differences between lung adenocarcinomas and squamous cell carci… |
| 85 | Alteration frequency | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 46.6s · 46.6s | 53.9s · 53.9s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | generate a oncoprint of kras, stk11, keap1, tp53 alterations stratified by smoking status… |
| 86 | Alteration frequency | ✓ 1/1 | – 0/1 | -100.0 pp | 100.0% → – | 56.3s · 56.3s | 13.6s · 13.6s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | what are the most common events in her2- breast cancer? |
| 96 | Survival & outcomes | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 8.8s · 8.8s | 16.5s · 16.5s | 100.0% → 0.0% | 0/0/0 · 0/0/0 | Is KRAS G12C more aggressive than G12D? |
| 102 | Expression & multi-omics | ✓ 1/1 | – 0/1 | -100.0 pp | 100.0% → – | 49.4s · 49.4s | 15.4s · 15.4s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | calculate median expression of ceacam5, itgb6, muc2, tpgb and muc1 mRNA in pancreatic can… |
| 104 | Out of scope | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 20.7s · 20.7s | 27.7s · 27.7s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | write me python code that can query the timeline files for msk-chord |
| 114 | Expression & multi-omics | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 59.8s · 59.8s | 118.7s · 118.7s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Are there differences in chromosome arm 7p copy number between lower grade glioma molecul… |
| 123 | Patient & sample lookup | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 34.2s · 34.2s | 37.6s · 37.6s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | In TCGA lower grade glioma, show me samples that are TP53 mutant or EGFR amplified. |
| 141 | Expression & multi-omics | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 55.9s · 55.9s | 182.7s · 182.7s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | is there a relatinoship between mgmt methylation and idh1 mutation in glioma? |
| 145 | Alteration frequency | ✓ 1/1 | ✗ 0/1 | -100.0 pp | 100.0% → 0.0% | 74.9s · 74.9s | 11.8s · 11.8s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Which genes are enriched for mutations between NSCLC vs squamous cell carcinoma? |
| 3 | Cohort & clinical counts | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 14.3s · 14.3s | 8.0s · 8.0s | 0.0% → 100.0% | 0/0/0 · 0/0/0 | How many patients and samples are in the MSK-CHORD Study? |
| 7 | Alteration frequency | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 32.6s · 32.6s | 33.6s · 33.6s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What are the top 5 most frequently copy number altered genes in the Osteosarcoma study fr… |
| 16 | Cohort & clinical counts | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 17.0s · 17.0s | 24.2s · 24.2s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | How many unique patients have both primary and metastatic samples in the MSK-CHORD Study? |
| 17 | Cohort & clinical counts | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 12.7s · 12.7s | 20.4s · 20.4s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What are the top 5 most common primary diagnosis sites in the MSK-CHORD Study? |
| 21 | Co-occurrence & exclusivity | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 26.9s · 26.9s | 25.4s · 25.4s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What are the most commonly co-occurring mutation pairs in breast cancer samples from the … |
| 40 | Alteration frequency | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 31.6s · 31.6s | 22.1s · 22.1s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What are the most frequently altered genes in KRAS wild-type lung adenocarcinoma patients? |
| 49 | Expression & multi-omics | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 44.1s · 44.1s | 64.4s · 64.4s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Which cancer types have the highest aneuploidy scores and how does this correlate with mu… |
| 51 | Cohort & clinical counts | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 23.6s · 23.6s | 20.8s · 20.8s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What fraction of patients were older than five when diagnosed according to the Pediatric … |
| 52 | Variants & hotspots | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 16.8s · 16.8s | 12.3s · 12.3s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What is the most frequent mutation in the TP53 gene in the TCGA breast cancer study? |
| 53 | Alteration frequency | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 30.0s · 30.0s | 9.9s · 9.9s | 0.0% → 100.0% | 0/0/0 · 0/0/0 | How many patients have an EGFR amplification in the TCGA Lung Adenocarcinoma study? |
| 54 | Variants & hotspots | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 21.3s · 21.3s | 16.3s · 16.3s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Which KRAS mutations are most common in colorectal cancer? |
| 55 | Survival & outcomes | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 19.2s · 19.2s | 21.6s · 21.6s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What is the median survival time in the Pediatric Neuroblastoma study from TARGET? |
| 60 | Expression & multi-omics | – 0/1 | ✓ 1/1 | +100.0 pp | – → 100.0% | 27.5s · 27.5s | 47.8s · 47.8s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | In the Breast Invasive Carcinoma TCGA study what are the top 5 down-regulated genes in TP… |
| 65 | Alteration frequency | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 44.4s · 44.4s | 27.5s · 27.5s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | In the TCGA PanCancer Atlas breast cancer study, what is the average tumor mutational bur… |
| 73 | Alteration frequency | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 28.7s · 28.7s | 21.0s · 21.0s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What is the frequency of TP53 mutations in lung cancer? |
| 76 | Out of scope | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 9.6s · 9.6s | 28.5s · 28.5s | 100.0% → 0.0% | 0/0/0 · 0/0/0 | Are TP53 mutations clinically actionable? |
| 81 | Alteration frequency | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 30.2s · 30.2s | 29.3s · 29.3s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | tell me about IDH1 mutations in glioma |
| 83 | Expression & multi-omics | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 52.2s · 52.2s | 41.5s · 41.5s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Help me rank TCGA cancer studies based on median CD3 expression |
| 92 | Variants & hotspots | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 29.3s · 29.3s | 25.4s · 25.4s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | what is the most prevalent TP53 mutation in uterine cancer that is not a point mutation |
| 97 | Co-occurrence & exclusivity | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 24.2s · 24.2s | 46.9s · 46.9s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | give me a contingency table with the number of lung cancer patients with EGFR and/or KRAS… |
| 106 | Study discovery | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 31.8s · 31.8s | 20.0s · 20.0s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | Which studies have RNA expression for renal cancer? |
| 109 | Variants & hotspots | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 42.8s · 42.8s | 32.3s · 32.3s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | I receive a report with the PIK3CA p.*1069Wext*3 mutation. Can you provide details of it |
| 116 | Variants & hotspots | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 15.7s · 15.7s | 21.8s · 21.8s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What are the frequencies of different KRAS mutations in TCGA PanCan Lung Adenocarcinoma? |
| 117 | Alteration frequency | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 25.3s · 25.3s | 25.2s · 25.2s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | What cancer types in MSK-IMPACT have mutations in TP53? |
| 135 | Survival & outcomes | ✗ 0/1 | ✓ 1/1 | +100.0 pp | 0.0% → 100.0% | 87.3s · 87.3s | 121.5s · 121.5s | 0.0% → 0.0% | 0/0/0 · 0/0/0 | How does overall survival compare between prostate cancer patients where TMPRSS2 is actin… |

…and 1 more.

Marks per repeat: ✓ pass · ✗ fail · – declined · · no reference or ungraded · ! request failed · ? missing. Recall = passes / eligible turns; eligible = graded + failed + missing turns of questions with a reference.

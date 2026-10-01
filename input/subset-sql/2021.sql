-- Q2021: Vital status (OS_STATUS) of NSCLC patients with KRAS G12C, msk_chord_2024.
-- Patients with >= 1 subset sample profiled for KRAS; "mutated" = >= 1 such sample with a KRAS G12C mutation
-- (mutation_status != 'UNCALLED', off_panel = 0); "not mutated" = the other profiled patients.
-- Then the distribution of the patient attribute OS_STATUS in each group.
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_chord_2024')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Non-Small Cell Lung Cancer')
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
  ),
  pts AS (
    SELECT patient_unique_id, max(sample_unique_id IN altered) AS mutated FROM sample_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND sample_unique_id IN subset AND sample_unique_id IN profiled
    GROUP BY patient_unique_id
  ),
  attr AS (
    SELECT patient_unique_id, attribute_value FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'OS_STATUS'
  )
SELECT if(mutated, 'mutated', 'not mutated') AS grp, attr.attribute_value AS os_status, count() AS patients,
  round(100 * patients / sum(patients) OVER (PARTITION BY grp), 1) AS pct_of_group
FROM pts LEFT JOIN attr USING (patient_unique_id)
GROUP BY grp, os_status ORDER BY grp, patients DESC
;

-- Baseline for Q2021: vital status of all KRAS-mutant NSCLC patients (any variant).
-- Patients with >= 1 subset sample profiled for KRAS; "mutated" = >= 1 such sample with a KRAS mutation
-- (mutation_status != 'UNCALLED', off_panel = 0); "not mutated" = the other profiled patients.
-- Then the distribution of the patient attribute OS_STATUS in each group.
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_chord_2024')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Non-Small Cell Lung Cancer')
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
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  ),
  pts AS (
    SELECT patient_unique_id, max(sample_unique_id IN altered) AS mutated FROM sample_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND sample_unique_id IN subset AND sample_unique_id IN profiled
    GROUP BY patient_unique_id
  ),
  attr AS (
    SELECT patient_unique_id, attribute_value FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'OS_STATUS'
  )
SELECT if(mutated, 'mutated', 'not mutated') AS grp, attr.attribute_value AS os_status, count() AS patients,
  round(100 * patients / sum(patients) OVER (PARTITION BY grp), 1) AS pct_of_group
FROM pts LEFT JOIN attr USING (patient_unique_id)
GROUP BY grp, os_status ORDER BY grp, patients DESC


-- Q2023: Liver metastasis (LIVER) among breast cancer patients with a TP53 mutation, msk_chord_2024.
-- Patients with >= 1 subset sample profiled for TP53; "mutated" = >= 1 such sample with a TP53 mutation
-- (mutation_status != 'UNCALLED', off_panel = 0); "not mutated" = the other profiled patients.
-- Then the distribution of the patient attribute LIVER in each group, among patients with a known status (LIVER = Yes or
-- No; LIVER = Unknown is left out of the denominators).
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_chord_2024')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Breast Cancer')
  ),
  profiled AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'TP53'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('msk_chord_2024')
  ),
  altered AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'TP53'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  ),
  pts AS (
    SELECT patient_unique_id, max(sample_unique_id IN altered) AS mutated FROM sample_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND sample_unique_id IN subset AND sample_unique_id IN profiled
    GROUP BY patient_unique_id
  ),
  attr AS (
    SELECT patient_unique_id, attribute_value FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'LIVER'
  )
SELECT if(mutated, 'mutated', 'not mutated') AS grp, attr.attribute_value AS liver, count() AS patients,
  round(100 * patients / sum(patients) OVER (PARTITION BY grp), 1) AS pct_of_group
FROM pts JOIN attr USING (patient_unique_id)
WHERE attr.attribute_value IN ('Yes', 'No')
GROUP BY grp, liver ORDER BY grp, patients DESC
;

-- Baseline for Q2023 (Unknown kept in the denominators, the other convention): Liver metastasis (LIVER) among breast cancer patients with a TP53 mutation, msk_chord_2024.
-- Patients with >= 1 subset sample profiled for TP53; "mutated" = >= 1 such sample with a TP53 mutation
-- (mutation_status != 'UNCALLED', off_panel = 0); "not mutated" = the other profiled patients.
-- Then the distribution of the patient attribute LIVER in each group.
WITH
  subset AS (
    SELECT sample_unique_id FROM sample_derived WHERE cancer_study_identifier IN ('msk_chord_2024')
    INTERSECT
    SELECT sample_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'CANCER_TYPE' AND attribute_value IN ('Breast Cancer')
  ),
  profiled AS (
    SELECT sample_unique_id FROM mutation_panel_gene_coverage
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'TP53'
    UNION DISTINCT
    SELECT sample_unique_id FROM mutation_wes_coverage WHERE cancer_study_identifier IN ('msk_chord_2024')
  ),
  altered AS (
    SELECT DISTINCT sample_unique_id FROM genomic_event_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND hugo_gene_symbol = 'TP53'
      AND variant_type = 'mutation' AND mutation_status != 'UNCALLED' AND off_panel = 0
  ),
  pts AS (
    SELECT patient_unique_id, max(sample_unique_id IN altered) AS mutated FROM sample_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND sample_unique_id IN subset AND sample_unique_id IN profiled
    GROUP BY patient_unique_id
  ),
  attr AS (
    SELECT patient_unique_id, attribute_value FROM clinical_data_derived
    WHERE cancer_study_identifier IN ('msk_chord_2024') AND attribute_name = 'LIVER'
  )
SELECT if(mutated, 'mutated', 'not mutated') AS grp, attr.attribute_value AS liver, count() AS patients,
  round(100 * patients / sum(patients) OVER (PARTITION BY grp), 1) AS pct_of_group
FROM pts LEFT JOIN attr USING (patient_unique_id)
GROUP BY grp, liver ORDER BY grp, patients DESC
;

-- Baseline for Q2023: LIVER among all breast cancer patients (no TP53 split), known status only.
SELECT attribute_value AS liver, count() AS patients, round(100 * patients / sum(patients) OVER (), 1) AS pct
FROM clinical_data_derived
WHERE cancer_study_identifier = 'msk_chord_2024' AND attribute_name = 'LIVER' AND attribute_value IN ('Yes', 'No')
  AND patient_unique_id IN (
    SELECT patient_unique_id FROM clinical_data_derived
    WHERE cancer_study_identifier = 'msk_chord_2024' AND attribute_name = 'CANCER_TYPE' AND attribute_value = 'Breast Cancer')
GROUP BY liver ORDER BY liver DESC

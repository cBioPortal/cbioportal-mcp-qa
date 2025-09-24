-- ===========================================
-- TABLE COMMENTS
-- ===========================================

ALTER TABLE type_of_cancer MODIFY COMMENT 'Lookup table for cancer types.';

ALTER TABLE reference_genome MODIFY COMMENT 'Reference genome definitions (e.g. hg19, GRCh38).';

ALTER TABLE cancer_study MODIFY COMMENT 'Contains metadata for each cancer study in the portal. References type_of_cancer and reference_genome.';

ALTER TABLE cancer_study_tags MODIFY COMMENT 'Tags associated with a cancer study. References cancer_study.';

ALTER TABLE patient MODIFY COMMENT 'Stores patient-level identifiers of patients enrolled in a cancer study. References cancer_study.';

ALTER TABLE sample MODIFY COMMENT 'Biological samples collected from patients. References patient.';

ALTER TABLE sample_list MODIFY COMMENT 'Named collections of samples within a study. References cancer_study.';

ALTER TABLE sample_list_list MODIFY COMMENT 'Join table linking sample lists to samples. References sample and sample_list.';

ALTER TABLE genetic_entity MODIFY COMMENT 'Abstract entity representing a gene, gene set, or other genomic element.';

ALTER TABLE gene MODIFY COMMENT 'Gene metadata (Entrez ID, HUGO symbol). References genetic_entity.';

ALTER TABLE gene_alias MODIFY COMMENT 'Alternative symbols/aliases for genes. References gene.';

ALTER TABLE geneset MODIFY COMMENT 'Collection of genes grouped into functional sets. References genetic_entity.';

ALTER TABLE geneset_gene MODIFY COMMENT 'Join table linking genesets to genes. References geneset and gene.';

ALTER TABLE geneset_hierarchy_node MODIFY COMMENT 'Hierarchy node for organizing gene sets. May reference parent node within same table.';

ALTER TABLE geneset_hierarchy_leaf MODIFY COMMENT 'Mapping of hierarchy nodes to specific gene sets. References geneset_hierarchy_node and geneset.';

ALTER TABLE genetic_profile MODIFY COMMENT 'Defines a molecular profile (e.g. mutations, CNA, mRNA expression). References cancer_study.';

ALTER TABLE genetic_profile_link MODIFY COMMENT 'Links between genetic profiles. References genetic_profile (source and target).';

ALTER TABLE genetic_alteration MODIFY COMMENT 'Stores genetic alteration values (for many genetic alteration types. e.g. MRNA_EXPRESSION, PROTEIN_LEVEL, GENERIC_ASSAY,...). References genetic_profile and genetic_entity.';

ALTER TABLE genetic_profile_samples MODIFY COMMENT 'Stores ordered sample lists for a genetic profile (for many genetic alteration types. e.g. MRNA_EXPRESSION, PROTEIN_LEVEL, GENERIC_ASSAY,...). References genetic_profile.';

ALTER TABLE gene_panel MODIFY COMMENT 'Defines a targeted gene panel used in sequencing.';

ALTER TABLE gene_panel_list MODIFY COMMENT 'Join table linking gene panels to genes. References gene_panel and gene.';

ALTER TABLE sample_profile MODIFY COMMENT 'Links samples to genetic profiles, optionally via a gene panel. References sample, genetic_profile, and gene_panel.';

ALTER TABLE structural_variant MODIFY COMMENT 'Structural variant data (fusions, translocations). References genetic_profile, sample, and gene (site1/site2).';

ALTER TABLE alteration_driver_annotation MODIFY COMMENT 'Annotations for genetic alterations classified as potential drivers. References genetic_profile and sample.';

ALTER TABLE mutation_event MODIFY COMMENT 'Defines unique mutation events (by position, gene, allele change). References gene.';

ALTER TABLE mutation MODIFY COMMENT 'Mutation observations in specific samples and profiles. References mutation_event, gene, genetic_profile, and sample.';

ALTER TABLE mutation_count_by_keyword MODIFY COMMENT 'Stores keyword-based aggregated mutation counts. References genetic_profile and gene.';

ALTER TABLE clinical_patient MODIFY COMMENT 'Patient-level clinical attribute values. References patient.';

ALTER TABLE clinical_sample MODIFY COMMENT 'Sample-level clinical attribute values. References sample.';

ALTER TABLE clinical_attribute_meta MODIFY COMMENT 'Metadata describing clinical attributes. References cancer_study.';

ALTER TABLE mut_sig MODIFY COMMENT 'MutSig significance analysis results. References cancer_study and gene.';

ALTER TABLE gistic MODIFY COMMENT 'GISTIC-identified copy number alteration regions. References cancer_study.';

ALTER TABLE gistic_to_gene MODIFY COMMENT 'Mapping of GISTIC regions to genes. References gistic and gene.';

ALTER TABLE cna_event MODIFY COMMENT 'Copy number alteration event definition. References gene.';

ALTER TABLE sample_cna_event MODIFY COMMENT 'Observed CNA events per sample and profile. References cna_event, sample, and genetic_profile.';

ALTER TABLE copy_number_seg MODIFY COMMENT 'Raw segmented copy number data. References cancer_study and sample.';

ALTER TABLE copy_number_seg_file MODIFY COMMENT 'File metadata for segmented copy number input. References cancer_study.';

ALTER TABLE cosmic_mutation MODIFY COMMENT 'COSMIC mutation data imported into cBioPortal. References gene.';

ALTER TABLE clinical_event MODIFY COMMENT 'Time-bound clinical events for patients. References patient.';

ALTER TABLE clinical_event_data MODIFY COMMENT 'Key-value attributes for clinical events. References clinical_event.';

ALTER TABLE reference_genome_gene MODIFY COMMENT 'Mapping of reference genome builds to genes. References reference_genome and gene.';

ALTER TABLE allele_specific_copy_number MODIFY COMMENT 'Allele-specific CNA data for mutations. References mutation_event, genetic_profile, and sample.';

ALTER TABLE info MODIFY COMMENT 'General schema and versioning information.';

ALTER TABLE resource_definition MODIFY COMMENT 'Definitions of external resources (study, patient, sample level). References cancer_study.';

ALTER TABLE resource_sample MODIFY COMMENT 'Links external resources to samples. References sample.';

ALTER TABLE resource_patient MODIFY COMMENT 'Links external resources to patients. References patient.';

ALTER TABLE resource_study MODIFY COMMENT 'Links external resources to cancer studies. References cancer_study.';

ALTER TABLE generic_entity_properties MODIFY COMMENT 'Properties for generic entities. References genetic_entity.';

-- ===========================================
-- COLUMN COMMENTS
-- ===========================================

-- Table: type_of_cancer
ALTER TABLE type_of_cancer COMMENT COLUMN type_of_cancer_id 'Primary key. Unique identifier for the cancer type.';
ALTER TABLE type_of_cancer COMMENT COLUMN name 'Full descriptive name of the cancer type.';
ALTER TABLE type_of_cancer COMMENT COLUMN dedicated_color 'Color code (hex or name) used for visualization.';
ALTER TABLE type_of_cancer COMMENT COLUMN short_name 'Abbreviated name of the cancer type.';
ALTER TABLE type_of_cancer COMMENT COLUMN parent 'References type_of_cancer.type_of_cancer_id (hierarchical parent).';

-- Table: reference_genome
ALTER TABLE reference_genome COMMENT COLUMN reference_genome_id 'Primary key. Unique identifier for the reference genome.';
ALTER TABLE reference_genome COMMENT COLUMN species 'Species name (e.g. Homo sapiens).';
ALTER TABLE reference_genome COMMENT COLUMN name 'Short name of the reference genome (e.g. hg19, GRCh38).';
ALTER TABLE reference_genome COMMENT COLUMN build_name 'Build identifier for the reference genome.';
ALTER TABLE reference_genome COMMENT COLUMN genome_size 'Total genome size in base pairs.';
ALTER TABLE reference_genome COMMENT COLUMN url 'URL link to the genome resource or documentation.';
ALTER TABLE reference_genome COMMENT COLUMN release_date 'Date when the reference genome build was released.';

-- Table: cancer_study
ALTER TABLE cancer_study COMMENT COLUMN cancer_study_id 'Primary key. Unique identifier for the cancer study.';
ALTER TABLE cancer_study COMMENT COLUMN cancer_study_identifier 'Stable string identifier for the study (used in URLs/APIs).';
ALTER TABLE cancer_study COMMENT COLUMN type_of_cancer_id 'References type_of_cancer.type_of_cancer_id.';
ALTER TABLE cancer_study COMMENT COLUMN name 'Full name of the cancer study.';
ALTER TABLE cancer_study COMMENT COLUMN description 'Detailed description of the study.';
ALTER TABLE cancer_study COMMENT COLUMN public 'Flag indicating if the study is publicly accessible.';
ALTER TABLE cancer_study COMMENT COLUMN pmid 'PubMed ID(s) associated with the study.';
ALTER TABLE cancer_study COMMENT COLUMN citation 'Citation string for the study.';
ALTER TABLE cancer_study COMMENT COLUMN status 'Import status (0=pending, 1=complete).';
ALTER TABLE cancer_study COMMENT COLUMN import_date 'Date when study was imported into the portal.';
ALTER TABLE cancer_study COMMENT COLUMN reference_genome_id 'References reference_genome.reference_genome_id.';

-- Table: cancer_study_tags
ALTER TABLE cancer_study_tags COMMENT COLUMN cancer_study_id 'References cancer_study.cancer_study_id.';
ALTER TABLE cancer_study_tags COMMENT COLUMN tags 'Tag values describing the study.';

-- Table: patient
ALTER TABLE patient COMMENT COLUMN internal_id 'Primary key. Unique internal identifier for the patient.';
ALTER TABLE patient COMMENT COLUMN stable_id 'Stable patient identifier within the study.';
ALTER TABLE patient COMMENT COLUMN cancer_study_id 'References cancer_study.cancer_study_id.';

-- Table: sample
ALTER TABLE sample COMMENT COLUMN internal_id 'Primary key. Unique internal identifier for the sample.';
ALTER TABLE sample COMMENT COLUMN stable_id 'Stable identifier for the sample within the study.';
ALTER TABLE sample COMMENT COLUMN sample_type 'Type of biological sample (free text. could contain arbitrary spelling e.g. Primary, Metastatic/Metastasis, Recurrent,..).';
ALTER TABLE sample COMMENT COLUMN patient_id 'References patient.internal_id.';

-- Table: sample_list
ALTER TABLE sample_list COMMENT COLUMN list_id 'Primary key. Unique identifier for the sample list.';
ALTER TABLE sample_list COMMENT COLUMN cancer_study_id 'References cancer_study.cancer_study_id.';
ALTER TABLE sample_list COMMENT COLUMN stable_id 'Stable identifier for the sample list.';
ALTER TABLE sample_list COMMENT COLUMN name 'Descriptive name for the sample list.';
ALTER TABLE sample_list COMMENT COLUMN description 'Detailed description of the sample list.';
ALTER TABLE sample_list COMMENT COLUMN category 'Category/type of the sample list.';

-- Table: sample_list_list
ALTER TABLE sample_list_list COMMENT COLUMN list_id 'References sample_list.list_id.';
ALTER TABLE sample_list_list COMMENT COLUMN sample_id 'References sample.internal_id.';

-- Table: genetic_entity
ALTER TABLE genetic_entity COMMENT COLUMN id 'Primary key. Unique identifier for the genetic entity.';
ALTER TABLE genetic_entity COMMENT COLUMN entity_type 'Type of genetic entity (e.g. GENE, GENESET).';
ALTER TABLE genetic_entity COMMENT COLUMN stable_id 'Stable external identifier of the genetic entity.';

-- Table: gene
ALTER TABLE gene COMMENT COLUMN entrez_gene_id 'Primary key. Entrez Gene ID.';
ALTER TABLE gene COMMENT COLUMN hugo_gene_symbol 'Official HUGO gene symbol.';
ALTER TABLE gene COMMENT COLUMN genetic_entity_id 'References genetic_entity.id.';
ALTER TABLE gene COMMENT COLUMN type 'Gene type (e.g. protein-coding, phosphoprotein, pseudogene, ncRNA, tRNA,...).';

-- Table: gene_alias
ALTER TABLE gene_alias COMMENT COLUMN entrez_gene_id 'References gene.entrez_gene_id.';
ALTER TABLE gene_alias COMMENT COLUMN gene_alias 'Alternative symbol or alias for the gene.';

-- Table: geneset
ALTER TABLE geneset COMMENT COLUMN id 'Primary key. Unique identifier for the gene set.';
ALTER TABLE geneset COMMENT COLUMN genetic_entity_id 'References genetic_entity.id.';
ALTER TABLE geneset COMMENT COLUMN external_id 'External identifier for the gene set (e.g. WP_SARSCOV2_AND_COVID19_PATHWAY, ZHU_SKIL_TARGETS_DN,...).';
ALTER TABLE geneset COMMENT COLUMN name 'Name of the gene set.';
ALTER TABLE geneset COMMENT COLUMN description 'Description of the gene set.';
ALTER TABLE geneset COMMENT COLUMN ref_link 'Optional reference link to source or publication.';

-- Table: geneset_gene
ALTER TABLE geneset_gene COMMENT COLUMN geneset_id 'References geneset.id.';
ALTER TABLE geneset_gene COMMENT COLUMN entrez_gene_id 'References gene.entrez_gene_id.';

-- Table: geneset_hierarchy_node
ALTER TABLE geneset_hierarchy_node COMMENT COLUMN node_id 'Primary key. Unique identifier for the hierarchy node.';
ALTER TABLE geneset_hierarchy_node COMMENT COLUMN node_name 'Name of the hierarchy node.';
ALTER TABLE geneset_hierarchy_node COMMENT COLUMN parent_id 'References geneset_hierarchy_node.node_id (parent node).';

-- Table: geneset_hierarchy_leaf
ALTER TABLE geneset_hierarchy_leaf COMMENT COLUMN node_id 'References geneset_hierarchy_node.node_id.';
ALTER TABLE geneset_hierarchy_leaf COMMENT COLUMN geneset_id 'References geneset.id.';

-- Table: generic_entity_properties
ALTER TABLE generic_entity_properties COMMENT COLUMN id 'Primary key. Unique identifier for this property.';
ALTER TABLE generic_entity_properties COMMENT COLUMN genetic_entity_id 'References genetic_entity.id.';
ALTER TABLE generic_entity_properties COMMENT COLUMN name 'Name of the property.';
ALTER TABLE generic_entity_properties COMMENT COLUMN value 'Value of the property.';

-- Table: genetic_profile
ALTER TABLE genetic_profile COMMENT COLUMN genetic_profile_id 'Primary key. Unique identifier for the genetic profile.';
ALTER TABLE genetic_profile COMMENT COLUMN stable_id 'Stable external identifier of the genetic profile.';
ALTER TABLE genetic_profile COMMENT COLUMN cancer_study_id 'References cancer_study.cancer_study_id.';
ALTER TABLE genetic_profile COMMENT COLUMN genetic_alteration_type 'Type of genetic alteration (e.g. MUTATION_EXTENDED, COPY_NUMBER_ALTERATION, MRNA_EXPRESSION, PROTEIN_LEVEL, GENERIC_ASSAY, STRUCTURAL_VARIANT, METHYLATION).';
ALTER TABLE genetic_profile COMMENT COLUMN generic_assay_type 'Type of assay used (TREATMENT_RESPONSE, PHOSPHOSITE_QUANTIFICATION, ...;only if genetic_alteration_type=GENERIC_ASSAY).';
ALTER TABLE genetic_profile COMMENT COLUMN datatype 'Datatype of the profile (e.g. MAF, DISCRETE, CONTINUOUS, LOG2-VALUE, Z-SCORE, LIMIT-VALUE, CATEGORICAL, SV,...). Togather with genetic_alteration_type defines a unique datatype.';
ALTER TABLE genetic_profile COMMENT COLUMN name 'Human-readable name of the genetic profile.';
ALTER TABLE genetic_profile COMMENT COLUMN description 'Detailed description of the genetic profile.';
ALTER TABLE genetic_profile COMMENT COLUMN show_profile_in_analysis_tab 'Flag to indicate if this profile should be shown in analysis tab.';
ALTER TABLE genetic_profile COMMENT COLUMN pivot_threshold 'Threshold value used for pivoting in visualization (optional).';
ALTER TABLE genetic_profile COMMENT COLUMN sort_order 'Sort order of values in the profile (ASC or DESC; optional).';
ALTER TABLE genetic_profile COMMENT COLUMN patient_level 'Indicates if profile is at patient level (1) or sample level (0).';

-- Table: genetic_profile_link
ALTER TABLE genetic_profile_link COMMENT COLUMN referring_genetic_profile_id 'References genetic_profile.genetic_profile_id (profile that refers).';
ALTER TABLE genetic_profile_link COMMENT COLUMN referred_genetic_profile_id 'References genetic_profile.genetic_profile_id (profile being referred).';
ALTER TABLE genetic_profile_link COMMENT COLUMN reference_type 'Type of reference: AGGREGATION (e.g., GSVA) or STATISTIC (e.g., Z-SCORES).';

-- Table: genetic_alteration
ALTER TABLE genetic_alteration COMMENT COLUMN genetic_profile_id 'References genetic_profile.genetic_profile_id.';
ALTER TABLE genetic_alteration COMMENT COLUMN genetic_entity_id 'References genetic_entity.id.';
ALTER TABLE genetic_alteration COMMENT COLUMN values 'Comma-separated genetic alteration values (e.g., mutations, CNA) in longtext format. Order of values matches order of corresponding sample identifiers in genetic_profile_samples.ordered_sample_list';

-- Table: genetic_profile_samples
ALTER TABLE genetic_profile_samples COMMENT COLUMN genetic_profile_id 'References genetic_profile.genetic_profile_id.';
ALTER TABLE genetic_profile_samples COMMENT COLUMN ordered_sample_list 'Comma-separated ordered list of sample IDs associated with this genetic profile.';

-- Table: gene_panel
ALTER TABLE gene_panel COMMENT COLUMN internal_id 'Primary key. Unique identifier for the gene panel.';
ALTER TABLE gene_panel COMMENT COLUMN stable_id 'Stable external identifier for the gene panel.';
ALTER TABLE gene_panel COMMENT COLUMN description 'Description of the gene panel contents.';

-- Table: gene_panel_list
ALTER TABLE gene_panel_list COMMENT COLUMN internal_id 'References gene_panel.internal_id.';
ALTER TABLE gene_panel_list COMMENT COLUMN gene_id 'References gene.entrez_gene_id.';

-- Table: sample_profile
ALTER TABLE sample_profile COMMENT COLUMN sample_id 'References sample.internal_id.';
ALTER TABLE sample_profile COMMENT COLUMN genetic_profile_id 'References genetic_profile.genetic_profile_id.';
ALTER TABLE sample_profile COMMENT COLUMN panel_id 'References gene_panel.internal_id. Optional.';

-- Table: structural_variant
ALTER TABLE structural_variant COMMENT COLUMN internal_id 'Primary key. Unique identifier for the structural variant.';
ALTER TABLE structural_variant COMMENT COLUMN genetic_profile_id 'References genetic_profile.genetic_profile_id.';
ALTER TABLE structural_variant COMMENT COLUMN sample_id 'References sample.internal_id.';
ALTER TABLE structural_variant COMMENT COLUMN site1_entrez_gene_id 'References gene.entrez_gene_id for site 1.';
ALTER TABLE structural_variant COMMENT COLUMN site2_entrez_gene_id 'References gene.entrez_gene_id for site 2.';
ALTER TABLE structural_variant COMMENT COLUMN site1_ensembl_transcript_id 'ENSEMBL transcript ID for site 1.';
ALTER TABLE structural_variant COMMENT COLUMN site1_chromosome 'Chromosome for site 1.';
ALTER TABLE structural_variant COMMENT COLUMN site1_region 'Region for site 1.';
ALTER TABLE structural_variant COMMENT COLUMN site1_region_number 'Region number for site 1.';
ALTER TABLE structural_variant COMMENT COLUMN site1_contig 'Contig for site 1.';
ALTER TABLE structural_variant COMMENT COLUMN site1_position 'Genomic position for site 1.';
ALTER TABLE structural_variant COMMENT COLUMN site1_description 'Description for site 1.';
ALTER TABLE structural_variant COMMENT COLUMN site2_ensembl_transcript_id 'ENSEMBL transcript ID for site 2.';
ALTER TABLE structural_variant COMMENT COLUMN site2_chromosome 'Chromosome for site 2.';
ALTER TABLE structural_variant COMMENT COLUMN site2_region 'Region for site 2.';
ALTER TABLE structural_variant COMMENT COLUMN site2_region_number 'Region number for site 2.';
ALTER TABLE structural_variant COMMENT COLUMN site2_contig 'Contig for site 2.';
ALTER TABLE structural_variant COMMENT COLUMN site2_position 'Genomic position for site 2.';
ALTER TABLE structural_variant COMMENT COLUMN site2_description 'Description for site 2.';
ALTER TABLE structural_variant COMMENT COLUMN site2_effect_on_frame 'Effect on reading frame for site 2.';
ALTER TABLE structural_variant COMMENT COLUMN ncbi_build 'NCBI genome build used.';
ALTER TABLE structural_variant COMMENT COLUMN dna_support 'DNA support flag.';
ALTER TABLE structural_variant COMMENT COLUMN rna_support 'RNA support flag.';
ALTER TABLE structural_variant COMMENT COLUMN normal_read_count 'Read count in normal sample.';
ALTER TABLE structural_variant COMMENT COLUMN tumor_read_count 'Read count in tumor sample.';
ALTER TABLE structural_variant COMMENT COLUMN normal_variant_count 'Variant count in normal sample.';
ALTER TABLE structural_variant COMMENT COLUMN tumor_variant_count 'Variant count in tumor sample.';
ALTER TABLE structural_variant COMMENT COLUMN normal_paired_end_read_count 'Paired-end read count in normal sample.';
ALTER TABLE structural_variant COMMENT COLUMN tumor_paired_end_read_count 'Paired-end read count in tumor sample.';
ALTER TABLE structural_variant COMMENT COLUMN normal_split_read_count 'Split read count in normal sample.';
ALTER TABLE structural_variant COMMENT COLUMN tumor_split_read_count 'Split read count in tumor sample.';
ALTER TABLE structural_variant COMMENT COLUMN annotation 'Additional annotation.';
ALTER TABLE structural_variant COMMENT COLUMN breakpoint_type 'Type of genomic breakpoint.';
ALTER TABLE structural_variant COMMENT COLUMN connection_type 'Connection type of the SV.';
ALTER TABLE structural_variant COMMENT COLUMN event_info 'Additional event info.';
ALTER TABLE structural_variant COMMENT COLUMN class 'Class of structural variant.';
ALTER TABLE structural_variant COMMENT COLUMN length 'Length of structural variant.';
ALTER TABLE structural_variant COMMENT COLUMN comments 'Comments about the variant.';
ALTER TABLE structural_variant COMMENT COLUMN sv_status 'GERMLINE or SOMATIC.';
ALTER TABLE structural_variant COMMENT COLUMN annotation_json 'JSON-formatted annotation details.';

-- Table: alteration_driver_annotation
ALTER TABLE alteration_driver_annotation COMMENT COLUMN alteration_event_id 'Identifier of the alteration event.';
ALTER TABLE alteration_driver_annotation COMMENT COLUMN genetic_profile_id 'References genetic_profile.genetic_profile_id.';
ALTER TABLE alteration_driver_annotation COMMENT COLUMN sample_id 'References sample.internal_id.';
ALTER TABLE alteration_driver_annotation COMMENT COLUMN driver_filter 'Driver filter applied.';
ALTER TABLE alteration_driver_annotation COMMENT COLUMN driver_filter_annotation 'Annotation for driver filter.';
ALTER TABLE alteration_driver_annotation COMMENT COLUMN driver_tiers_filter 'Driver tiers filter applied.';
ALTER TABLE alteration_driver_annotation COMMENT COLUMN driver_tiers_filter_annotation 'Annotation for driver tiers filter.';

-- Table: mutation_event
ALTER TABLE mutation_event COMMENT COLUMN mutation_event_id 'Primary key. Unique identifier for the mutation event.';
ALTER TABLE mutation_event COMMENT COLUMN entrez_gene_id 'References gene.entrez_gene_id.';
ALTER TABLE mutation_event COMMENT COLUMN chr 'Chromosome where mutation occurs.';
ALTER TABLE mutation_event COMMENT COLUMN start_position 'Start genomic position.';
ALTER TABLE mutation_event COMMENT COLUMN end_position 'End genomic position.';
ALTER TABLE mutation_event COMMENT COLUMN reference_allele 'Reference allele sequence.';
ALTER TABLE mutation_event COMMENT COLUMN tumor_seq_allele 'Tumor allele sequence.';
ALTER TABLE mutation_event COMMENT COLUMN protein_change 'Protein-level change caused by mutation.';
ALTER TABLE mutation_event COMMENT COLUMN mutation_type 'Type of mutation (e.g., Missense, Nonsense).';
ALTER TABLE mutation_event COMMENT COLUMN ncbi_build 'NCBI genome build used.';
ALTER TABLE mutation_event COMMENT COLUMN strand 'Strand (+/-) of the mutation.';
ALTER TABLE mutation_event COMMENT COLUMN variant_type 'Variant type (e.g., SNP, INDEL).';
ALTER TABLE mutation_event COMMENT COLUMN db_snp_rs 'dbSNP identifier.';
ALTER TABLE mutation_event COMMENT COLUMN db_snp_val_status 'Validation status in dbSNP.';
ALTER TABLE mutation_event COMMENT COLUMN refseq_mrna_id 'RefSeq mRNA ID.';
ALTER TABLE mutation_event COMMENT COLUMN codon_change 'Codon change.';
ALTER TABLE mutation_event COMMENT COLUMN uniprot_accession 'UniProt accession ID.';
ALTER TABLE mutation_event COMMENT COLUMN protein_pos_start 'Start position on protein.';
ALTER TABLE mutation_event COMMENT COLUMN protein_pos_end 'End position on protein.';
ALTER TABLE mutation_event COMMENT COLUMN canonical_transcript 'Flag for canonical transcript.';
ALTER TABLE mutation_event COMMENT COLUMN keyword 'Keyword annotation (e.g., truncating, V200 Missense).';

-- Table: mutation
ALTER TABLE mutation COMMENT COLUMN mutation_event_id 'References mutation_event.mutation_event_id.';
ALTER TABLE mutation COMMENT COLUMN genetic_profile_id 'References genetic_profile.genetic_profile_id.';
ALTER TABLE mutation COMMENT COLUMN sample_id 'References sample.internal_id.';
ALTER TABLE mutation COMMENT COLUMN entrez_gene_id 'References gene.entrez_gene_id.';
ALTER TABLE mutation COMMENT COLUMN center 'Center where sequencing was performed.';
ALTER TABLE mutation COMMENT COLUMN sequencer 'Sequencing platform used.';
ALTER TABLE mutation COMMENT COLUMN mutation_status 'Mutation status: Germline, Somatic, or LOH.';
ALTER TABLE mutation COMMENT COLUMN validation_status 'Validation status.';
ALTER TABLE mutation COMMENT COLUMN tumor_seq_allele1 'Tumor allele 1 sequence.';
ALTER TABLE mutation COMMENT COLUMN tumor_seq_allele2 'Tumor allele 2 sequence.';
ALTER TABLE mutation COMMENT COLUMN matched_norm_sample_barcode 'Matched normal sample barcode.';
ALTER TABLE mutation COMMENT COLUMN match_norm_seq_allele1 'Matched normal allele 1 sequence.';
ALTER TABLE mutation COMMENT COLUMN match_norm_seq_allele2 'Matched normal allele 2 sequence.';
ALTER TABLE mutation COMMENT COLUMN tumor_validation_allele1 'Tumor validation allele 1 sequence.';
ALTER TABLE mutation COMMENT COLUMN tumor_validation_allele2 'Tumor validation allele 2 sequence.';
ALTER TABLE mutation COMMENT COLUMN match_norm_validation_allele1 'Matched normal validation allele 1.';
ALTER TABLE mutation COMMENT COLUMN match_norm_validation_allele2 'Matched normal validation allele 2.';
ALTER TABLE mutation COMMENT COLUMN verification_status 'Verification status.';
ALTER TABLE mutation COMMENT COLUMN sequencing_phase 'Sequencing phase.';
ALTER TABLE mutation COMMENT COLUMN sequence_source 'Source of sequencing data.';
ALTER TABLE mutation COMMENT COLUMN validation_method 'Validation method used.';
ALTER TABLE mutation COMMENT COLUMN score 'Score or quality metric.';
ALTER TABLE mutation COMMENT COLUMN bam_file 'Associated BAM file.';
ALTER TABLE mutation COMMENT COLUMN tumor_alt_count 'Tumor alternate allele count.';
ALTER TABLE mutation COMMENT COLUMN tumor_ref_count 'Tumor reference allele count.';
ALTER TABLE mutation COMMENT COLUMN normal_alt_count 'Normal alternate allele count.';
ALTER TABLE mutation COMMENT COLUMN normal_ref_count 'Normal reference allele count.';
ALTER TABLE mutation COMMENT COLUMN amino_acid_change 'Amino acid change from mutation.';
ALTER TABLE mutation COMMENT COLUMN annotation_json 'JSON-formatted annotations.';

-- Table: mutation_count_by_keyword
ALTER TABLE mutation_count_by_keyword COMMENT COLUMN genetic_profile_id 'References genetic_profile.genetic_profile_id.';
ALTER TABLE mutation_count_by_keyword COMMENT COLUMN keyword 'Mutation keyword annotation.';
ALTER TABLE mutation_count_by_keyword COMMENT COLUMN entrez_gene_id 'References gene.entrez_gene_id.';
ALTER TABLE mutation_count_by_keyword COMMENT COLUMN keyword_count 'Number of mutations matching the keyword.';
ALTER TABLE mutation_count_by_keyword COMMENT COLUMN gene_count 'Number of mutations for the gene.';

-- Table: clinical_patient
ALTER TABLE clinical_patient COMMENT COLUMN internal_id 'References patient.internal_id.';
ALTER TABLE clinical_patient COMMENT COLUMN attr_id 'Attribute identifier.';
ALTER TABLE clinical_patient COMMENT COLUMN attr_value 'Value of the clinical attribute.';

-- Table: clinical_sample
ALTER TABLE clinical_sample COMMENT COLUMN internal_id 'References sample.internal_id.';
ALTER TABLE clinical_sample COMMENT COLUMN attr_id 'Attribute identifier.';
ALTER TABLE clinical_sample COMMENT COLUMN attr_value 'Value of the clinical attribute.';

-- Table: clinical_attribute_meta
ALTER TABLE clinical_attribute_meta COMMENT COLUMN attr_id 'Clinical attribute identifier.';
ALTER TABLE clinical_attribute_meta COMMENT COLUMN display_name 'Human-readable display name of the attribute.';
ALTER TABLE clinical_attribute_meta COMMENT COLUMN description 'Description of the attribute.';
ALTER TABLE clinical_attribute_meta COMMENT COLUMN datatype 'Data type: NUMBER, BOOLEAN, or STRING.';
ALTER TABLE clinical_attribute_meta COMMENT COLUMN patient_attribute 'Flag indicating if the attribute is for patient-level data.';
ALTER TABLE clinical_attribute_meta COMMENT COLUMN priority 'Priority for display or processing.';
ALTER TABLE clinical_attribute_meta COMMENT COLUMN cancer_study_id 'References cancer_study.cancer_study_id.';

-- Table: mut_sig
ALTER TABLE mut_sig COMMENT COLUMN cancer_study_id 'References cancer_study.cancer_study_id.';
ALTER TABLE mut_sig COMMENT COLUMN entrez_gene_id 'References gene.entrez_gene_id.';
ALTER TABLE mut_sig COMMENT COLUMN rank 'Rank of the gene in mutational significance.';
ALTER TABLE mut_sig COMMENT COLUMN NumBasesCovered 'Number of bases covered in the study for this gene.';
ALTER TABLE mut_sig COMMENT COLUMN NumMutations 'Number of mutations observed in this gene.';
ALTER TABLE mut_sig COMMENT COLUMN p_value 'P-value of mutational significance.';
ALTER TABLE mut_sig COMMENT COLUMN q_value 'Q-value (FDR) of mutational significance.';

-- Table: gistic
ALTER TABLE gistic COMMENT COLUMN gistic_roi_id 'Primary key. Unique identifier for GISTIC region of interest.';
ALTER TABLE gistic COMMENT COLUMN cancer_study_id 'References cancer_study.cancer_study_id.';
ALTER TABLE gistic COMMENT COLUMN chromosome 'Chromosome of the ROI.';
ALTER TABLE gistic COMMENT COLUMN cytoband 'Cytogenetic band of the ROI.';
ALTER TABLE gistic COMMENT COLUMN wide_peak_start 'Start position of the wide peak.';
ALTER TABLE gistic COMMENT COLUMN wide_peak_end 'End position of the wide peak.';
ALTER TABLE gistic COMMENT COLUMN q_value 'Q-value of the GISTIC peak.';
ALTER TABLE gistic COMMENT COLUMN amp '1 if amplified, 0 otherwise.';

-- Table: gistic_to_gene
ALTER TABLE gistic_to_gene COMMENT COLUMN gistic_roi_id 'References gistic.gistic_roi_id.';
ALTER TABLE gistic_to_gene COMMENT COLUMN entrez_gene_id 'References gene.entrez_gene_id.';

-- Table: cna_event
ALTER TABLE cna_event COMMENT COLUMN cna_event_id 'Primary key. Unique identifier for CNA event.';
ALTER TABLE cna_event COMMENT COLUMN entrez_gene_id 'References gene.entrez_gene_id.';
ALTER TABLE cna_event COMMENT COLUMN alteration 'Type of copy number alteration (e.g., gain or loss).';

-- Table: sample_cna_event
ALTER TABLE sample_cna_event COMMENT COLUMN cna_event_id 'References cna_event.cna_event_id.';
ALTER TABLE sample_cna_event COMMENT COLUMN sample_id 'References sample.internal_id.';
ALTER TABLE sample_cna_event COMMENT COLUMN genetic_profile_id 'References genetic_profile.genetic_profile_id.';
ALTER TABLE sample_cna_event COMMENT COLUMN annotation_json 'JSON-formatted annotation details.';

-- Table: copy_number_seg
ALTER TABLE copy_number_seg COMMENT COLUMN seg_id 'Primary key. Unique segment identifier.';
ALTER TABLE copy_number_seg COMMENT COLUMN cancer_study_id 'References cancer_study.cancer_study_id.';
ALTER TABLE copy_number_seg COMMENT COLUMN sample_id 'References sample.internal_id.';
ALTER TABLE copy_number_seg COMMENT COLUMN chr 'Chromosome of the segment.';
ALTER TABLE copy_number_seg COMMENT COLUMN start 'Start position of the segment.';
ALTER TABLE copy_number_seg COMMENT COLUMN end 'End position of the segment.';
ALTER TABLE copy_number_seg COMMENT COLUMN num_probes 'Number of probes used for this segment.';
ALTER TABLE copy_number_seg COMMENT COLUMN segment_mean 'Segment mean copy number.';

-- Table: copy_number_seg_file
ALTER TABLE copy_number_seg_file COMMENT COLUMN seg_file_id 'Primary key. Unique segment file identifier.';
ALTER TABLE copy_number_seg_file COMMENT COLUMN cancer_study_id 'References cancer_study.cancer_study_id.';
ALTER TABLE copy_number_seg_file COMMENT COLUMN reference_genome_id 'Reference genome version used.';
ALTER TABLE copy_number_seg_file COMMENT COLUMN description 'Description of the file.';
ALTER TABLE copy_number_seg_file COMMENT COLUMN filename 'Name of the segment file.';

-- Table: cosmic_mutation
ALTER TABLE cosmic_mutation COMMENT COLUMN cosmic_mutation_id 'Primary key. COSMIC mutation identifier.';
ALTER TABLE cosmic_mutation COMMENT COLUMN chr 'Chromosome where mutation occurs.';
ALTER TABLE cosmic_mutation COMMENT COLUMN start_position 'Start genomic position of the mutation.';
ALTER TABLE cosmic_mutation COMMENT COLUMN reference_allele 'Reference allele sequence.';
ALTER TABLE cosmic_mutation COMMENT COLUMN tumor_seq_allele 'Tumor allele sequence.';
ALTER TABLE cosmic_mutation COMMENT COLUMN strand 'Strand (+/-) of the mutation.';
ALTER TABLE cosmic_mutation COMMENT COLUMN codon_change 'Codon change annotation.';
ALTER TABLE cosmic_mutation COMMENT COLUMN entrez_gene_id 'References gene.entrez_gene_id.';
ALTER TABLE cosmic_mutation COMMENT COLUMN protein_change 'Protein-level change caused by mutation.';
ALTER TABLE cosmic_mutation COMMENT COLUMN count 'Number of samples observed with this mutation.';
ALTER TABLE cosmic_mutation COMMENT COLUMN keyword 'Keyword annotation.';

-- Table: clinical_event
ALTER TABLE clinical_event COMMENT COLUMN patient_id 'References patient.internal_id.';
ALTER TABLE clinical_event COMMENT COLUMN start_date 'Start date of the clinical event (epoch or numeric format).';
ALTER TABLE clinical_event COMMENT COLUMN stop_date 'Stop date of the clinical event (optional).';
ALTER TABLE clinical_event COMMENT COLUMN event_type 'Type of clinical event (e.g. Specimen, Treatment, Surgery,...).';

-- Table: clinical_event_data
ALTER TABLE clinical_event_data COMMENT COLUMN key 'Data key.';
ALTER TABLE clinical_event_data COMMENT COLUMN value 'Value associated with the key.';

-- Table: reference_genome_gene
ALTER TABLE reference_genome_gene COMMENT COLUMN entrez_gene_id 'References gene.entrez_gene_id.';
ALTER TABLE reference_genome_gene COMMENT COLUMN reference_genome_id 'References reference_genome.reference_genome_id.';
ALTER TABLE reference_genome_gene COMMENT COLUMN chr 'Chromosome of the gene (optional).';
ALTER TABLE reference_genome_gene COMMENT COLUMN cytoband 'Cytoband location of the gene (optional).';
ALTER TABLE reference_genome_gene COMMENT COLUMN start 'Start position of the gene (optional).';
ALTER TABLE reference_genome_gene COMMENT COLUMN end 'End position of the gene (optional).';

-- Table: allele_specific_copy_number
ALTER TABLE allele_specific_copy_number COMMENT COLUMN mutation_event_id 'References mutation_event.mutation_event_id.';
ALTER TABLE allele_specific_copy_number COMMENT COLUMN genetic_profile_id 'References genetic_profile.genetic_profile_id.';
ALTER TABLE allele_specific_copy_number COMMENT COLUMN sample_id 'References sample.internal_id.';
ALTER TABLE allele_specific_copy_number COMMENT COLUMN ascn_integer_copy_number 'Allele-specific integer copy number (optional).';
ALTER TABLE allele_specific_copy_number COMMENT COLUMN ascn_method 'Method used to determine ASCN.';
ALTER TABLE allele_specific_copy_number COMMENT COLUMN ccf_expected_copies_upper 'Expected upper bound of CCF copies.';
ALTER TABLE allele_specific_copy_number COMMENT COLUMN ccf_expected_copies 'Expected copies from CCF.';
ALTER TABLE allele_specific_copy_number COMMENT COLUMN clonal 'Clonality annotation (optional).';
ALTER TABLE allele_specific_copy_number COMMENT COLUMN minor_copy_number 'Minor allele copy number (optional).';
ALTER TABLE allele_specific_copy_number COMMENT COLUMN expected_alt_copies 'Expected alternate allele copies.';
ALTER TABLE allele_specific_copy_number COMMENT COLUMN total_copy_number 'Total copy number.';

-- Table: info
ALTER TABLE info COMMENT COLUMN db_schema_version 'Version of the database schema.';
ALTER TABLE info COMMENT COLUMN geneset_version 'Version of the geneset.';

-- Table: resource_definition
ALTER TABLE resource_definition COMMENT COLUMN resource_id 'Primary key. Unique identifier for the resource.';
ALTER TABLE resource_definition COMMENT COLUMN display_name 'Human-readable name of the resource.';
ALTER TABLE resource_definition COMMENT COLUMN description 'Description of the resource (optional).';
ALTER TABLE resource_definition COMMENT COLUMN resource_type 'Type of resource: STUDY, PATIENT, or SAMPLE.';
ALTER TABLE resource_definition COMMENT COLUMN open_by_default 'Whether the resource is open by default.';
ALTER TABLE resource_definition COMMENT COLUMN priority 'Priority of the resource for display or access.';
ALTER TABLE resource_definition COMMENT COLUMN cancer_study_id 'References cancer_study.cancer_study_id.';
ALTER TABLE resource_definition COMMENT COLUMN custom_metadata 'Optional JSON field for custom metadata.';

-- Table: resource_sample
ALTER TABLE resource_sample COMMENT COLUMN internal_id 'References sample.internal_id.';
ALTER TABLE resource_sample COMMENT COLUMN resource_id 'References resource_definition.resource_id.';
ALTER TABLE resource_sample COMMENT COLUMN url 'URL or link associated with this resource and sample.';

-- Table: resource_patient
ALTER TABLE resource_patient COMMENT COLUMN internal_id 'References patient.internal_id.';
ALTER TABLE resource_patient COMMENT COLUMN resource_id 'References resource_definition.resource_id.';
ALTER TABLE resource_patient COMMENT COLUMN url 'URL or link associated with this resource and patient.';

-- Table: resource_study
ALTER TABLE resource_study COMMENT COLUMN internal_id 'References cancer_study.cancer_study_id.';
ALTER TABLE resource_study COMMENT COLUMN resource_id 'References resource_definition.resource_id.';
ALTER TABLE resource_study COMMENT COLUMN url 'URL or link associated with this resource and study.';

-- ===========================================
-- Table: sample_to_gene_panel_derived
-- ===========================================
ALTER TABLE sample_to_gene_panel_derived MODIFY COMMENT 'Denormalized mapping table linking samples to their associated gene panels for each genetic alteration type. Derived from sample_profile, genetic_profile, gene_panel, sample, and cancer_study tables. Defaults to WES (Whole Exome Sequencing) when no specific gene panel is assigned.';

-- ===========================================
-- Column Comments
-- ===========================================
ALTER TABLE sample_to_gene_panel_derived COMMENT COLUMN sample_unique_id 'Unique identifier for the sample, constructed as cancer_study_identifier + "_" + sample.stable_id to ensure global uniqueness across studies.';
ALTER TABLE sample_to_gene_panel_derived COMMENT COLUMN alteration_type 'Type of genetic alteration (e.g. MUTATION_EXTENDED, COPY_NUMBER_ALTERATION, MRNA_EXPRESSION, PROTEIN_LEVEL, GENERIC_ASSAY, STRUCTURAL_VARIANT, METHYLATION). References genetic_profile.genetic_alteration_type.';
ALTER TABLE sample_to_gene_panel_derived COMMENT COLUMN gene_panel_id 'Identifier of the gene panel used for this sample and alteration type. Defaults to "WES" (Whole Exome Sequencing) when no specific panel is assigned (panel_id is NULL).';
ALTER TABLE sample_to_gene_panel_derived COMMENT COLUMN cancer_study_identifier 'Stable string identifier for the cancer study, used in URLs and APIs. References cancer_study.cancer_study_identifier.';
ALTER TABLE sample_to_gene_panel_derived COMMENT COLUMN genetic_profile_id 'Stable identifier of the genetic profile. References genetic_profile.stable_id.';

-- ===========================================
-- Table: gene_panel_to_gene_derived
-- ===========================================
ALTER TABLE gene_panel_to_gene_derived MODIFY COMMENT 'Denormalized mapping table linking gene panels to their constituent genes. Includes both specific targeted gene panels (from gene_panel and gene_panel_list tables) and a comprehensive WES (Whole Exome Sequencing) panel containing all genes with valid Entrez IDs. Used for efficient gene panel coverage queries.';

-- ===========================================
-- Column Comments
-- ===========================================
ALTER TABLE gene_panel_to_gene_derived COMMENT COLUMN gene_panel_id 'Identifier of the gene panel. Contains actual gene panel stable IDs from gene_panel table, plus "WES" representing Whole Exome Sequencing which includes all genes with positive Entrez IDs.';
ALTER TABLE gene_panel_to_gene_derived COMMENT COLUMN gene 'HUGO gene symbol from the gene table. References gene.hugo_gene_symbol for genes included in the specified panel.';

-- ===========================================
-- Table: sample_derived
-- ===========================================
ALTER TABLE sample_derived MODIFY COMMENT 'Denormalized sample table with globally unique identifiers and enriched metadata. Combines sample, patient, and cancer_study data with computed flags for sequencing status and copy number segment availability. Optimized for summary and detailed projections with base64-encoded identifiers for URL-safe usage.';

-- ===========================================
-- Column Comments
-- ===========================================
ALTER TABLE sample_derived COMMENT COLUMN sample_unique_id 'Globally unique sample identifier constructed as cancer_study_identifier + "_" + sample.stable_id to ensure uniqueness across all studies.';
ALTER TABLE sample_derived COMMENT COLUMN sample_unique_id_base64 'Base64-encoded version of sample.stable_id for URL-safe usage in web applications and APIs.';
ALTER TABLE sample_derived COMMENT COLUMN sample_stable_id 'Original stable identifier of the sample within its study. References sample.stable_id.';
ALTER TABLE sample_derived COMMENT COLUMN patient_unique_id 'Globally unique patient identifier constructed as cancer_study_identifier + "_" + patient.stable_id to ensure uniqueness across all studies.';
ALTER TABLE sample_derived COMMENT COLUMN patient_unique_id_base64 'Base64-encoded version of patient.stable_id for URL-safe usage in web applications and APIs.';
ALTER TABLE sample_derived COMMENT COLUMN patient_stable_id 'Original stable identifier of the patient within its study. References patient.stable_id.';
ALTER TABLE sample_derived COMMENT COLUMN cancer_study_identifier 'Stable string identifier for the cancer study, used in URLs and APIs. References cancer_study.cancer_study_identifier.';
ALTER TABLE sample_derived COMMENT COLUMN internal_id 'Internal database identifier for the sample. References sample.internal_id.';
ALTER TABLE sample_derived COMMENT COLUMN patient_internal_id 'Internal database identifier for the patient. References patient.internal_id.';
ALTER TABLE sample_derived COMMENT COLUMN sample_type 'Type of biological sample (free text, e.g. Primary, Metastatic, Recurrent). References sample.sample_type.';
ALTER TABLE sample_derived COMMENT COLUMN sequenced 'Flag indicating if the sample has sequencing data available (1=yes, 0=no). Determined by membership in study-specific sequenced sample lists with naming pattern: cancer_study_identifier + "_sequenced". Used for DETAILED projection optimization.';
ALTER TABLE sample_derived COMMENT COLUMN copy_number_segment_present 'Flag indicating if copy number segmentation data is available for this sample (1=yes, 0=no). Determined by presence in copy_number_seg table. Used for DETAILED projection optimization.';

-- ===========================================
-- Table: genomic_event_derived
-- ===========================================
ALTER TABLE genomic_event_derived MODIFY COMMENT 'Unified genomic events table combining mutations, copy number alterations (CNA), and structural variants into a single denormalized view. Each row represents a gene-level genomic event observed in a sample. Structural variants are split into separate rows for site1 and site2 genes (excluding duplicates). Includes off-panel detection to identify events in genes not covered by the associated gene panel.';

-- ===========================================
-- Column Comments
-- ===========================================
ALTER TABLE genomic_event_derived COMMENT COLUMN sample_unique_id 'Globally unique sample identifier constructed as cancer_study_identifier + "_" + sample.stable_id to ensure uniqueness across all studies.';
ALTER TABLE genomic_event_derived COMMENT COLUMN hugo_gene_symbol 'Official HUGO gene symbol for the affected gene. References gene.hugo_gene_symbol.';
ALTER TABLE genomic_event_derived COMMENT COLUMN entrez_gene_id 'Entrez Gene ID for the affected gene. References gene.entrez_gene_id.';
ALTER TABLE genomic_event_derived COMMENT COLUMN gene_panel_stable_id 'Identifier of the gene panel used for this sample. Defaults to "WES" (Whole Exome Sequencing) when no specific panel is assigned.';
ALTER TABLE genomic_event_derived COMMENT COLUMN cancer_study_identifier 'Stable string identifier for the cancer study. References cancer_study.cancer_study_identifier.';
ALTER TABLE genomic_event_derived COMMENT COLUMN genetic_profile_stable_id 'Stable identifier of the genetic profile containing this event. References genetic_profile.stable_id.';
ALTER TABLE genomic_event_derived COMMENT COLUMN variant_type 'Type of genomic variant: "mutation" for point mutations/indels, "cna" for copy number alterations, "structural_variant" for structural rearrangements.';
ALTER TABLE genomic_event_derived COMMENT COLUMN mutation_variant 'Protein-level change for mutations (e.g., p.V600E). Set to "NA" for non-mutation events. References mutation_event.protein_change.';
ALTER TABLE genomic_event_derived COMMENT COLUMN mutation_type 'Classification of mutation type (e.g., Missense, Nonsense, Frame_Shift). Set to "NA" for non-mutation events. References mutation_event.mutation_type.';
ALTER TABLE genomic_event_derived COMMENT COLUMN mutation_status 'Mutation status: Germline, Somatic, or LOH. Set to "NA" for non-mutation events. References mutation.mutation_status.';
ALTER TABLE genomic_event_derived COMMENT COLUMN driver_filter 'Driver annotation filter applied to the alteration. Currently set to "NA" for all events (driver annotations not yet implemented).';
ALTER TABLE genomic_event_derived COMMENT COLUMN driver_tiers_filter 'Driver tiers annotation filter. Currently set to "NA" for all events (driver annotations not yet implemented).';
ALTER TABLE genomic_event_derived COMMENT COLUMN cna_alteration 'Copy number alteration value (e.g., -2 for deep deletion, +2 for amplification). NULL for non-CNA events. References cna_event.alteration.';
ALTER TABLE genomic_event_derived COMMENT COLUMN cna_cytoband 'Cytogenetic band location of the gene for CNA events. Empty string for non-CNA events. References reference_genome_gene.cytoband.';
ALTER TABLE genomic_event_derived COMMENT COLUMN sv_event_info 'Additional information about structural variant events. Empty string for non-SV events. References structural_variant.event_info.';
ALTER TABLE genomic_event_derived COMMENT COLUMN patient_unique_id 'Globally unique patient identifier constructed as cancer_study_identifier + "_" + patient.stable_id to ensure uniqueness across all studies.';
ALTER TABLE genomic_event_derived COMMENT COLUMN off_panel 'Boolean flag indicating whether this genomic event occurred in a gene not covered by the associated gene panel (TRUE=off-panel, FALSE=on-panel). Determined by checking presence in gene_panel_to_gene_derived table.';

-- ===========================================
-- Table: clinical_data_derived
-- ===========================================
ALTER TABLE clinical_data_derived MODIFY COMMENT 'Unified clinical data table combining both patient-level and sample-level clinical attributes in a normalized key-value format. Uses FULL OUTER JOIN to ensure all defined clinical attributes appear for each patient/sample, even when no value is recorded (populated with empty string). Enables efficient querying of clinical data across different attribute types and levels.';

-- ===========================================
-- Column Comments
-- ===========================================
ALTER TABLE clinical_data_derived COMMENT COLUMN internal_id 'Internal database identifier. For sample-level data, references sample.internal_id; for patient-level data, references patient.internal_id.';
ALTER TABLE clinical_data_derived COMMENT COLUMN sample_unique_id 'Globally unique sample identifier constructed as cancer_study_identifier + "_" + sample.stable_id. Populated only for sample-level clinical data; empty string for patient-level data.';
ALTER TABLE clinical_data_derived COMMENT COLUMN patient_unique_id 'Globally unique patient identifier constructed as cancer_study_identifier + "_" + patient.stable_id. Populated for both sample-level and patient-level clinical data.';
ALTER TABLE clinical_data_derived COMMENT COLUMN attribute_name 'Name/identifier of the clinical attribute. References clinical_attribute_meta.attr_id.';
ALTER TABLE clinical_data_derived COMMENT COLUMN attribute_value 'Value of the clinical attribute for this patient/sample. Empty string when no value is recorded but attribute is defined for the study.';
ALTER TABLE clinical_data_derived COMMENT COLUMN cancer_study_identifier 'Stable string identifier for the cancer study. References cancer_study.cancer_study_identifier.';
ALTER TABLE clinical_data_derived COMMENT COLUMN type 'Level of the clinical data: "sample" for sample-level attributes, "patient" for patient-level attributes. Determined by clinical_attribute_meta.patient_attribute flag.';

-- ===========================================
-- Table: clinical_event_derived
-- ===========================================
ALTER TABLE clinical_event_derived MODIFY COMMENT 'Denormalized clinical timeline events table combining temporal clinical events with their associated key-value attributes. Each row represents a specific attribute of a clinical event (e.g., treatment, surgery, specimen collection) with start/stop dates. Flattens the normalized clinical_event and clinical_event_data relationship into a queryable format for timeline analysis.';

-- ===========================================
-- Column Comments
-- ===========================================
ALTER TABLE clinical_event_derived COMMENT COLUMN patient_unique_id 'Globally unique patient identifier constructed as cancer_study_identifier + "_" + patient.stable_id to ensure uniqueness across all studies.';
ALTER TABLE clinical_event_derived COMMENT COLUMN key 'Attribute name/key for the clinical event data. References clinical_event_data.key. Examples might include drug_name, dosage, procedure_type, etc.';
ALTER TABLE clinical_event_derived COMMENT COLUMN value 'Attribute value for the clinical event data. References clinical_event_data.value. Contains the actual data value corresponding to the key.';
ALTER TABLE clinical_event_derived COMMENT COLUMN start_date 'Start date of the clinical event in numeric format (typically epoch time or days from diagnosis). References clinical_event.start_date.';
ALTER TABLE clinical_event_derived COMMENT COLUMN stop_date 'Stop/end date of the clinical event in numeric format. Defaults to 0 when no stop date is specified (ongoing or point-in-time events). References clinical_event.stop_date.';
ALTER TABLE clinical_event_derived COMMENT COLUMN event_type 'Type/category of clinical event such as Treatment, Surgery, Specimen, Status, etc. References clinical_event.event_type.';
ALTER TABLE clinical_event_derived COMMENT COLUMN cancer_study_identifier 'Stable string identifier for the cancer study. References cancer_study.cancer_study_identifier.';

-- ===========================================
-- Table: genetic_alteration_derived
-- ===========================================
ALTER TABLE genetic_alteration_derived MODIFY COMMENT 'Denormalized genetic alteration data table that unpivots the wide-format genetic_alteration values into a long-format structure. Each row represents one gene-sample-profile combination with its alteration value. Excludes mutation data (handled separately) and generic assays, focusing on continuous/discrete data like expression, methylation, and copy number. Filters out "NA" values to reduce storage and improve query performance.';

-- ===========================================
-- Column Comments
-- ===========================================
ALTER TABLE genetic_alteration_derived COMMENT COLUMN sample_unique_id 'Globally unique sample identifier constructed as cancer_study_identifier + "_" + sample.stable_id to ensure uniqueness across all studies.';
ALTER TABLE genetic_alteration_derived COMMENT COLUMN cancer_study_identifier 'Stable string identifier for the cancer study. References cancer_study.cancer_study_identifier.';
ALTER TABLE genetic_alteration_derived COMMENT COLUMN hugo_gene_symbol 'Official HUGO gene symbol for the gene being measured. References gene.hugo_gene_symbol.';
ALTER TABLE genetic_alteration_derived COMMENT COLUMN profile_type 'Type of genetic profile with study prefix removed (e.g., "mrna_expression", "cna_discrete", "methylation"). Derived from genetic_profile.stable_id by removing the cancer_study_identifier prefix.';
ALTER TABLE genetic_alteration_derived COMMENT COLUMN alteration_value 'The actual genetic alteration measurement value (e.g., expression level, methylation beta value, copy number). NULL when no measurement available. Excludes "NA" values which are filtered out during insertion.';

-- ===========================================
-- Table: generic_assay_data_derived
-- ===========================================
ALTER TABLE generic_assay_data_derived MODIFY COMMENT 'Denormalized generic assay data table that unpivots wide-format genetic_alteration values for generic assay profiles into a long-format structure. Handles diverse assay types like treatment response, phosphosite quantification, and other non-genomic measurements. Each row represents one entity-sample combination with its measured value. Supports both sample-level and patient-level data based on profile configuration.';

-- ===========================================
-- Column Comments
-- ===========================================
ALTER TABLE generic_assay_data_derived COMMENT COLUMN sample_unique_id 'Globally unique sample identifier constructed as cancer_study_identifier + "_" + sample.stable_id to ensure uniqueness across all studies.';
ALTER TABLE generic_assay_data_derived COMMENT COLUMN patient_unique_id 'Globally unique patient identifier constructed as cancer_study_identifier + "_" + patient.stable_id to ensure uniqueness across all studies.';
ALTER TABLE generic_assay_data_derived COMMENT COLUMN genetic_entity_id 'Internal identifier for the genetic entity being measured. References genetic_entity.id. For generic assays, this represents the assay target (e.g., drug compound, phosphosite, pathway).';
ALTER TABLE generic_assay_data_derived COMMENT COLUMN value 'The measured value for this entity-sample combination. Data type and format depend on the specific assay type (e.g., IC50 values, phosphorylation levels, pathway scores).';
ALTER TABLE generic_assay_data_derived COMMENT COLUMN generic_assay_type 'Type of generic assay performed (e.g., TREATMENT_RESPONSE, PHOSPHOSITE_QUANTIFICATION, PATHWAY_SCORE). References genetic_profile.generic_assay_type.';
ALTER TABLE generic_assay_data_derived COMMENT COLUMN profile_stable_id 'Stable identifier of the genetic profile containing this assay data. References genetic_profile.stable_id.';
ALTER TABLE generic_assay_data_derived COMMENT COLUMN entity_stable_id 'Stable external identifier of the genetic entity being measured. References genetic_entity.stable_id. Examples include drug names, phosphosite identifiers, or pathway names.';
ALTER TABLE generic_assay_data_derived COMMENT COLUMN datatype 'Data format of the measurements (e.g., CONTINUOUS, DISCRETE, CATEGORICAL, LIMIT-VALUE). References genetic_profile.datatype.';
ALTER TABLE generic_assay_data_derived COMMENT COLUMN patient_level 'Flag indicating data level: 1 for patient-level data, 0 for sample-level data. References genetic_profile.patient_level.';
ALTER TABLE generic_assay_data_derived COMMENT COLUMN profile_type 'Type of assay profile with study prefix removed for cleaner categorization. Derived from profile_stable_id by removing the cancer_study_identifier prefix.';
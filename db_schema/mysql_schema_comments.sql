-- ===========================================
-- Table: type_of_cancer
-- ===========================================
ALTER TABLE `type_of_cancer` 
  COMMENT = 'Lookup table for cancer types.';

-- ===========================================
-- Table: reference_genome
-- ===========================================
ALTER TABLE `reference_genome` 
  COMMENT = 'Reference genome definitions (e.g. hg19, GRCh38).';

-- ===========================================
-- Table: cancer_study
-- ===========================================
ALTER TABLE `cancer_study` 
  COMMENT = 'Contains metadata for each cancer study in the portal. References type_of_cancer and reference_genome.';

-- ===========================================
-- Table: cancer_study_tags
-- ===========================================
ALTER TABLE `cancer_study_tags` 
  COMMENT = 'Tags associated with a cancer study. References cancer_study.';

-- ===========================================
-- Table: patient
-- ===========================================
ALTER TABLE `patient` 
  COMMENT = 'Stores patient-level identifiers of patients enrolled in a cancer study. References cancer_study.';

-- ===========================================
-- Table: sample
-- ===========================================
ALTER TABLE `sample` 
  COMMENT = 'Biological samples collected from patients. References patient.';

-- ===========================================
-- Table: sample_list
-- ===========================================
ALTER TABLE `sample_list` 
  COMMENT = 'Named collections of samples within a study. References cancer_study.';

-- ===========================================
-- Table: sample_list_list
-- ===========================================
ALTER TABLE `sample_list_list` 
  COMMENT = 'Join table linking sample lists to samples. References sample and sample_list.';

-- ===========================================
-- Table: genetic_entity
-- ===========================================
ALTER TABLE `genetic_entity` 
  COMMENT = 'Abstract entity representing a gene, gene set, or other genomic element.';

-- ===========================================
-- Table: gene
-- ===========================================
ALTER TABLE `gene` 
  COMMENT = 'Gene metadata (Entrez ID, HUGO symbol). References genetic_entity.';

-- ===========================================
-- Table: gene_alias
-- ===========================================
ALTER TABLE `gene_alias` 
  COMMENT = 'Alternative symbols/aliases for genes. References gene.';

-- ===========================================
-- Table: geneset
-- ===========================================
ALTER TABLE `geneset` 
  COMMENT = 'Collection of genes grouped into functional sets. References genetic_entity.';

-- ===========================================
-- Table: geneset_gene
-- ===========================================
ALTER TABLE `geneset_gene` 
  COMMENT = 'Join table linking genesets to genes. References geneset and gene.';

-- ===========================================
-- Table: geneset_hierarchy_node
-- ===========================================
ALTER TABLE `geneset_hierarchy_node` 
  COMMENT = 'Hierarchy node for organizing gene sets. May reference parent node within same table.';

-- ===========================================
-- Table: geneset_hierarchy_leaf
-- ===========================================
ALTER TABLE `geneset_hierarchy_leaf` 
  COMMENT = 'Mapping of hierarchy nodes to specific gene sets. References geneset_hierarchy_node and geneset.';

-- ===========================================
-- Table: genetic_profile
-- ===========================================
ALTER TABLE `genetic_profile` 
  COMMENT = 'Defines a molecular profile (e.g. mutations, CNA, mRNA expression). References cancer_study.';

-- ===========================================
-- Table: genetic_profile_link
-- ===========================================
ALTER TABLE `genetic_profile_link` 
  COMMENT = 'Links between genetic profiles. References genetic_profile (source and target).';

-- ===========================================
-- Table: genetic_alteration
-- ===========================================
ALTER TABLE `genetic_alteration` 
  COMMENT = 'Stores genetic alteration values (for many genetic alteration types. e.g. MRNA_EXPRESSION, PROTEIN_LEVEL, GENERIC_ASSAY,...). References genetic_profile and genetic_entity.';

-- ===========================================
-- Table: genetic_profile_samples
-- ===========================================
ALTER TABLE `genetic_profile_samples` 
  COMMENT = 'Stores ordered sample lists for a genetic profile (for many genetic alteration types. e.g. MRNA_EXPRESSION, PROTEIN_LEVEL, GENERIC_ASSAY,...). References genetic_profile.';

-- ===========================================
-- Table: gene_panel
-- ===========================================
ALTER TABLE `gene_panel` 
  COMMENT = 'Defines a targeted gene panel used in sequencing.';

-- ===========================================
-- Table: gene_panel_list
-- ===========================================
ALTER TABLE `gene_panel_list` 
  COMMENT = 'Join table linking gene panels to genes. References gene_panel and gene.';

-- ===========================================
-- Table: sample_profile
-- ===========================================
ALTER TABLE `sample_profile` 
  COMMENT = 'Links samples to genetic profiles, optionally via a gene panel. References sample, genetic_profile, and gene_panel.';

-- ===========================================
-- Table: structural_variant
-- ===========================================
ALTER TABLE `structural_variant` 
  COMMENT = 'Structural variant data (fusions, translocations). References genetic_profile, sample, and gene (site1/site2).';

-- ===========================================
-- Table: alteration_driver_annotation
-- ===========================================
ALTER TABLE `alteration_driver_annotation` 
  COMMENT = 'Annotations for genetic alterations classified as potential drivers. References genetic_profile and sample.';

-- ===========================================
-- Table: mutation_event
-- ===========================================
ALTER TABLE `mutation_event` 
  COMMENT = 'Defines unique mutation events (by position, gene, allele change). References gene.';

-- ===========================================
-- Table: mutation
-- ===========================================
ALTER TABLE `mutation` 
  COMMENT = 'Mutation observations in specific samples and profiles. References mutation_event, gene, genetic_profile, and sample.';

-- ===========================================
-- Table: mutation_count_by_keyword
-- ===========================================
ALTER TABLE `mutation_count_by_keyword` 
  COMMENT = 'Stores keyword-based aggregated mutation counts. References genetic_profile and gene.';

-- ===========================================
-- Table: clinical_patient
-- ===========================================
ALTER TABLE `clinical_patient` 
  COMMENT = 'Patient-level clinical attribute values. References patient.';

-- ===========================================
-- Table: clinical_sample
-- ===========================================
ALTER TABLE `clinical_sample` 
  COMMENT = 'Sample-level clinical attribute values. References sample.';

-- ===========================================
-- Table: clinical_attribute_meta
-- ===========================================
ALTER TABLE `clinical_attribute_meta` 
  COMMENT = 'Metadata describing clinical attributes. References cancer_study.';

-- ===========================================
-- Table: mut_sig
-- ===========================================
ALTER TABLE `mut_sig` 
  COMMENT = 'MutSig significance analysis results. References cancer_study and gene.';

-- ===========================================
-- Table: gistic
-- ===========================================
ALTER TABLE `gistic` 
  COMMENT = 'GISTIC-identified copy number alteration regions. References cancer_study.';

-- ===========================================
-- Table: gistic_to_gene
-- ===========================================
ALTER TABLE `gistic_to_gene` 
  COMMENT = 'Mapping of GISTIC regions to genes. References gistic and gene.';

-- ===========================================
-- Table: cna_event
-- ===========================================
ALTER TABLE `cna_event` 
  COMMENT = 'Copy number alteration event definition. References gene.';

-- ===========================================
-- Table: sample_cna_event
-- ===========================================
ALTER TABLE `sample_cna_event` 
  COMMENT = 'Observed CNA events per sample and profile. References cna_event, sample, and genetic_profile.';

-- ===========================================
-- Table: copy_number_seg
-- ===========================================
ALTER TABLE `copy_number_seg` 
  COMMENT = 'Raw segmented copy number data. References cancer_study and sample.';

-- ===========================================
-- Table: copy_number_seg_file
-- ===========================================
ALTER TABLE `copy_number_seg_file` 
  COMMENT = 'File metadata for segmented copy number input. References cancer_study.';

-- ===========================================
-- Table: cosmic_mutation
-- ===========================================
ALTER TABLE `cosmic_mutation` 
  COMMENT = 'COSMIC mutation data imported into cBioPortal. References gene.';

-- ===========================================
-- Table: clinical_event
-- ===========================================
ALTER TABLE `clinical_event` 
  COMMENT = 'Time-bound clinical events for patients. References patient.';

-- ===========================================
-- Table: clinical_event_data
-- ===========================================
ALTER TABLE `clinical_event_data` 
  COMMENT = 'Key-value attributes for clinical events. References clinical_event.';

-- ===========================================
-- Table: reference_genome_gene
-- ===========================================
ALTER TABLE `reference_genome_gene` 
  COMMENT = 'Mapping of reference genome builds to genes. References reference_genome and gene.';

-- ===========================================
-- Table: allele_specific_copy_number
-- ===========================================
ALTER TABLE `allele_specific_copy_number` 
  COMMENT = 'Allele-specific CNA data for mutations. References mutation_event, genetic_profile, and sample.';

-- ===========================================
-- Table: info
-- ===========================================
ALTER TABLE `info` 
  COMMENT = 'General schema and versioning information.';

-- ===========================================
-- Table: resource_definition
-- ===========================================
ALTER TABLE `resource_definition` 
  COMMENT = 'Definitions of external resources (study, patient, sample level). References cancer_study.';

-- ===========================================
-- Table: resource_sample
-- ===========================================
ALTER TABLE `resource_sample` 
  COMMENT = 'Links external resources to samples. References sample.';

-- ===========================================
-- Table: resource_patient
-- ===========================================
ALTER TABLE `resource_patient` 
  COMMENT = 'Links external resources to patients. References patient.';

-- ===========================================
-- Table: resource_study
-- ===========================================
ALTER TABLE `resource_study` 
  COMMENT = 'Links external resources to cancer studies. References cancer_study.';

-- ********************************************************************************************************************************
-- *************************************************** TABLE COLUMN COMMENTS ******************************************************
-- ********************************************************************************************************************************
-- NOTE: setting comments for columns only possible togather with type and contraints in mysql. So be careful
-- ===========================================
-- Table: type_of_cancer
-- ===========================================
ALTER TABLE `type_of_cancer`
  CHANGE COLUMN `TYPE_OF_CANCER_ID` `TYPE_OF_CANCER_ID` varchar(63) NOT NULL COMMENT 'Primary key. Unique identifier for the cancer type.',
  CHANGE COLUMN `NAME` `NAME` varchar(255) NOT NULL COMMENT 'Full descriptive name of the cancer type.',
  CHANGE COLUMN `DEDICATED_COLOR` `DEDICATED_COLOR` char(31) NOT NULL COMMENT 'Color code (hex or name) used for visualization.',
  CHANGE COLUMN `SHORT_NAME` `SHORT_NAME` varchar(127) COMMENT 'Abbreviated name of the cancer type.',
  CHANGE COLUMN `PARENT` `PARENT` varchar(63) COMMENT 'References type_of_cancer.TYPE_OF_CANCER_ID (hierarchical parent).';


-- ===========================================
-- Table: reference_genome
-- ===========================================
ALTER TABLE `reference_genome`
  CHANGE COLUMN `REFERENCE_GENOME_ID` `REFERENCE_GENOME_ID` int(4) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique identifier for the reference genome.',
  CHANGE COLUMN `SPECIES` `SPECIES` varchar(64) NOT NULL COMMENT 'Species name (e.g. Homo sapiens).',
  CHANGE COLUMN `NAME` `NAME` varchar(64) NOT NULL COMMENT 'Short name of the reference genome (e.g. hg19, GRCh38).',
  CHANGE COLUMN `BUILD_NAME` `BUILD_NAME` varchar(64) NOT NULL COMMENT 'Build identifier for the reference genome.',
  CHANGE COLUMN `GENOME_SIZE` `GENOME_SIZE` bigint(20) COMMENT 'Total genome size in base pairs.',
  CHANGE COLUMN `URL` `URL` varchar(256) NOT NULL COMMENT 'URL link to the genome resource or documentation.',
  CHANGE COLUMN `RELEASE_DATE` `RELEASE_DATE` datetime DEFAULT NULL COMMENT 'Date when the reference genome build was released.';


-- ===========================================
-- Table: cancer_study
-- ===========================================
ALTER TABLE `cancer_study`
  CHANGE COLUMN `CANCER_STUDY_ID` `CANCER_STUDY_ID` int(11) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique identifier for the cancer study.',
  CHANGE COLUMN `CANCER_STUDY_IDENTIFIER` `CANCER_STUDY_IDENTIFIER` varchar(255) COMMENT 'Stable string identifier for the study (used in URLs/APIs).',
  CHANGE COLUMN `TYPE_OF_CANCER_ID` `TYPE_OF_CANCER_ID` varchar(63) NOT NULL COMMENT 'References type_of_cancer.TYPE_OF_CANCER_ID.',
  CHANGE COLUMN `NAME` `NAME` varchar(255) NOT NULL COMMENT 'Full name of the cancer study.',
  CHANGE COLUMN `DESCRIPTION` `DESCRIPTION` varchar(1024) NOT NULL COMMENT 'Detailed description of the study.',
  CHANGE COLUMN `PUBLIC` `PUBLIC` BOOLEAN NOT NULL COMMENT 'Flag indicating if the study is publicly accessible.',
  CHANGE COLUMN `PMID` `PMID` varchar(1024) DEFAULT NULL COMMENT 'PubMed ID(s) associated with the study.',
  CHANGE COLUMN `CITATION` `CITATION` varchar(200) DEFAULT NULL COMMENT 'Citation string for the study.',
  CHANGE COLUMN `STATUS` `STATUS` int(1) DEFAULT NULL COMMENT 'Import status (0=pending, 1=complete).',
  CHANGE COLUMN `IMPORT_DATE` `IMPORT_DATE` datetime DEFAULT NULL COMMENT 'Date when study was imported into the portal.',
  CHANGE COLUMN `REFERENCE_GENOME_ID` `REFERENCE_GENOME_ID` int(4) DEFAULT 1 COMMENT 'References reference_genome.REFERENCE_GENOME_ID.';


-- ===========================================
-- Table: cancer_study_tags
-- ===========================================
ALTER TABLE `cancer_study_tags`
  CHANGE COLUMN `CANCER_STUDY_ID` `CANCER_STUDY_ID` int(11) NOT NULL COMMENT 'References cancer_study.CANCER_STUDY_ID.',
  CHANGE COLUMN `TAGS` `TAGS` text NOT NULL COMMENT 'Tag values describing the study.';


-- ===========================================
-- Table: patient
-- ===========================================
ALTER TABLE `patient`
  CHANGE COLUMN `INTERNAL_ID` `INTERNAL_ID` int(11) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique internal identifier for the patient.',
  CHANGE COLUMN `STABLE_ID` `STABLE_ID` varchar(50) NOT NULL COMMENT 'Stable patient identifier within the study.',
  CHANGE COLUMN `CANCER_STUDY_ID` `CANCER_STUDY_ID` int(11) NOT NULL COMMENT 'References cancer_study.CANCER_STUDY_ID.';
-- ===========================================
-- Table: sample
-- ===========================================
ALTER TABLE `sample`
  CHANGE COLUMN `INTERNAL_ID` `INTERNAL_ID` int(11) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique internal identifier for the sample.',
  CHANGE COLUMN `STABLE_ID` `STABLE_ID` varchar(63) NOT NULL COMMENT 'Stable identifier for the sample within the study.',
  CHANGE COLUMN `SAMPLE_TYPE` `SAMPLE_TYPE` varchar(255) NOT NULL COMMENT 'Type of biological sample (free text. could contain arbitrary spelling e.g. Primary, Metastatic/Metastasis, Recurrent,..).',
  CHANGE COLUMN `PATIENT_ID` `PATIENT_ID` int(11) NOT NULL COMMENT 'References patient.INTERNAL_ID.';


-- ===========================================
-- Table: sample_list
-- ===========================================
ALTER TABLE `sample_list`
  CHANGE COLUMN `LIST_ID` `LIST_ID` int(11) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique identifier for the sample list.',
  CHANGE COLUMN `CANCER_STUDY_ID` `CANCER_STUDY_ID` int(11) NOT NULL COMMENT 'References cancer_study.CANCER_STUDY_ID.',
  CHANGE COLUMN `STABLE_ID` `STABLE_ID` varchar(255) NOT NULL COMMENT 'Stable identifier for the sample list.',
  CHANGE COLUMN `NAME` `NAME` varchar(255) NOT NULL COMMENT 'Descriptive name for the sample list.',
  CHANGE COLUMN `DESCRIPTION` `DESCRIPTION` varchar(512) COMMENT 'Detailed description of the sample list.',
  CHANGE COLUMN `CATEGORY` `CATEGORY` varchar(255) NOT NULL COMMENT 'Category/type of the sample list.';


-- ===========================================
-- Table: sample_list_list
-- ===========================================
ALTER TABLE `sample_list_list`
  CHANGE COLUMN `LIST_ID` `LIST_ID` int(11) NOT NULL COMMENT 'References sample_list.LIST_ID.',
  CHANGE COLUMN `SAMPLE_ID` `SAMPLE_ID` int(11) NOT NULL COMMENT 'References sample.INTERNAL_ID.';


-- ===========================================
-- Table: genetic_entity
-- ===========================================
ALTER TABLE `genetic_entity`
  CHANGE COLUMN `ID` `ID` int(11) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique identifier for the genetic entity.',
  CHANGE COLUMN `ENTITY_TYPE` `ENTITY_TYPE` varchar(45) NOT NULL COMMENT 'Type of genetic entity (e.g. GENE, GENESET).',
  CHANGE COLUMN `STABLE_ID` `STABLE_ID` varchar(255) DEFAULT NULL COMMENT 'Stable external identifier of the genetic entity.';


-- ===========================================
-- Table: gene
-- ===========================================
ALTER TABLE `gene`
  CHANGE COLUMN `ENTREZ_GENE_ID` `ENTREZ_GENE_ID` int(11) NOT NULL COMMENT 'Primary key. Entrez Gene ID.',
  CHANGE COLUMN `HUGO_GENE_SYMBOL` `HUGO_GENE_SYMBOL` varchar(255) NOT NULL COMMENT 'Official HUGO gene symbol.',
  CHANGE COLUMN `GENETIC_ENTITY_ID` `GENETIC_ENTITY_ID` int(11) NOT NULL COMMENT 'References genetic_entity.ID.',
  CHANGE COLUMN `TYPE` `TYPE` varchar(50) COMMENT 'Gene type (e.g. protein-coding, phosphoprotein, pseudogene, ncRNA, tRNA,...).';


-- ===========================================
-- Table: gene_alias
-- ===========================================
ALTER TABLE `gene_alias`
  CHANGE COLUMN `ENTREZ_GENE_ID` `ENTREZ_GENE_ID` int(11) NOT NULL COMMENT 'References gene.ENTREZ_GENE_ID.',
  CHANGE COLUMN `GENE_ALIAS` `GENE_ALIAS` varchar(255) NOT NULL COMMENT 'Alternative symbol or alias for the gene.';


-- ===========================================
-- Table: geneset
-- ===========================================
ALTER TABLE `geneset`
  CHANGE COLUMN `ID` `ID` int(11) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique identifier for the gene set.',
  CHANGE COLUMN `GENETIC_ENTITY_ID` `GENETIC_ENTITY_ID` int(11) NOT NULL COMMENT 'References genetic_entity.ID.',
  CHANGE COLUMN `EXTERNAL_ID` `EXTERNAL_ID` varchar(200) NOT NULL COMMENT 'External identifier for the gene set (e.g. WP_SARSCOV2_AND_COVID19_PATHWAY, ZHU_SKIL_TARGETS_DN,...).',
  CHANGE COLUMN `NAME` `NAME` varchar(200) NOT NULL COMMENT 'Name of the gene set.',
  CHANGE COLUMN `DESCRIPTION` `DESCRIPTION` varchar(300) NOT NULL COMMENT 'Description of the gene set.',
  CHANGE COLUMN `REF_LINK` `REF_LINK` text COMMENT 'Optional reference link to source or publication.';


-- ===========================================
-- Table: geneset_gene
-- ===========================================
ALTER TABLE `geneset_gene`
  CHANGE COLUMN `GENESET_ID` `GENESET_ID` int(11) NOT NULL COMMENT 'References geneset.ID.',
  CHANGE COLUMN `ENTREZ_GENE_ID` `ENTREZ_GENE_ID` int(11) NOT NULL COMMENT 'References gene.ENTREZ_GENE_ID.';


-- ===========================================
-- Table: geneset_hierarchy_node
-- ===========================================
ALTER TABLE `geneset_hierarchy_node`
  CHANGE COLUMN `NODE_ID` `NODE_ID` bigint(20) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique identifier for the hierarchy node.',
  CHANGE COLUMN `NODE_NAME` `NODE_NAME` varchar(200) NOT NULL COMMENT 'Name of the hierarchy node.',
  CHANGE COLUMN `PARENT_ID` `PARENT_ID` bigint(20) DEFAULT NULL COMMENT 'References geneset_hierarchy_node.NODE_ID (parent node).';


-- ===========================================
-- Table: geneset_hierarchy_leaf
-- ===========================================
ALTER TABLE `geneset_hierarchy_leaf`
  CHANGE COLUMN `NODE_ID` `NODE_ID` bigint(20) NOT NULL COMMENT 'References geneset_hierarchy_node.NODE_ID.',
  CHANGE COLUMN `GENESET_ID` `GENESET_ID` int(11) NOT NULL COMMENT 'References geneset.ID.';

-- ===========================================
-- Table: generic_entity_properties
-- ===========================================
ALTER TABLE `generic_entity_properties`
  CHANGE COLUMN `ID` `ID` INT(11) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique identifier for this property.',
  CHANGE COLUMN `GENETIC_ENTITY_ID` `GENETIC_ENTITY_ID` INT NOT NULL COMMENT 'References genetic_entity.ID.',
  CHANGE COLUMN `NAME` `NAME` varchar(255) NOT NULL COMMENT 'Name of the property.',
  CHANGE COLUMN `VALUE` `VALUE` varchar(5000) NOT NULL COMMENT 'Value of the property.';


-- ===========================================
-- Table: genetic_profile
-- ===========================================
ALTER TABLE `genetic_profile`
  CHANGE COLUMN `GENETIC_PROFILE_ID` `GENETIC_PROFILE_ID` int(11) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique identifier for the genetic profile.',
  CHANGE COLUMN `STABLE_ID` `STABLE_ID` varchar(255) NOT NULL COMMENT 'Stable external identifier of the genetic profile.',
  CHANGE COLUMN `CANCER_STUDY_ID` `CANCER_STUDY_ID` int(11) NOT NULL COMMENT 'References cancer_study.CANCER_STUDY_ID.',
  CHANGE COLUMN `GENETIC_ALTERATION_TYPE` `GENETIC_ALTERATION_TYPE` varchar(255) NOT NULL COMMENT 'Type of genetic alteration (e.g. MUTATION_EXTENDED, COPY_NUMBER_ALTERATION, MRNA_EXPRESSION, PROTEIN_LEVEL, GENERIC_ASSAY, STRUCTURAL_VARIANT, METHYLATION).',
  CHANGE COLUMN `GENERIC_ASSAY_TYPE` `GENERIC_ASSAY_TYPE` varchar(255) DEFAULT NULL COMMENT 'Type of assay used (TREATMENT_RESPONSE, PHOSPHOSITE_QUANTIFICATION, ...;only if GENETIC_ALTERATION_TYPE=GENERIC_ASSAY).',
  CHANGE COLUMN `DATATYPE` `DATATYPE` varchar(255) NOT NULL COMMENT 'Datatype of the profile (e.g. MAF, DISCRETE, CONTINUOUS, LOG2-VALUE, Z-SCORE, LIMIT-VALUE, CATEGORICAL, SV,...). Togather with GENETIC_ALTERATION_TYPE defines a unique datatype.',
  CHANGE COLUMN `NAME` `NAME` varchar(255) NOT NULL COMMENT 'Human-readable name of the genetic profile.',
  CHANGE COLUMN `DESCRIPTION` `DESCRIPTION` mediumtext COMMENT 'Detailed description of the genetic profile.',
  CHANGE COLUMN `SHOW_PROFILE_IN_ANALYSIS_TAB` `SHOW_PROFILE_IN_ANALYSIS_TAB` tinyint(1) NOT NULL COMMENT 'Flag to indicate if this profile should be shown in analysis tab.',
  CHANGE COLUMN `PIVOT_THRESHOLD` `PIVOT_THRESHOLD` FLOAT DEFAULT NULL COMMENT 'Threshold value used for pivoting in visualization (optional).',
  CHANGE COLUMN `SORT_ORDER` `SORT_ORDER` ENUM('ASC','DESC') DEFAULT NULL COMMENT 'Sort order of values in the profile (ASC or DESC; optional).',
  CHANGE COLUMN `PATIENT_LEVEL` `PATIENT_LEVEL` boolean DEFAULT 0 COMMENT 'Indicates if profile is at patient level (1) or sample level (0).';


-- ===========================================
-- Table: genetic_profile_link
-- ===========================================
ALTER TABLE `genetic_profile_link`
  CHANGE COLUMN `REFERRING_GENETIC_PROFILE_ID` `REFERRING_GENETIC_PROFILE_ID` INT NOT NULL COMMENT 'References genetic_profile.GENETIC_PROFILE_ID (profile that refers).',
  CHANGE COLUMN `REFERRED_GENETIC_PROFILE_ID` `REFERRED_GENETIC_PROFILE_ID` INT NOT NULL COMMENT 'References genetic_profile.GENETIC_PROFILE_ID (profile being referred).',
  CHANGE COLUMN `REFERENCE_TYPE` `REFERENCE_TYPE` VARCHAR(45) DEFAULT NULL COMMENT 'Type of reference: AGGREGATION (e.g., GSVA) or STATISTIC (e.g., Z-SCORES).';


-- ===========================================
-- Table: genetic_alteration
-- ===========================================
ALTER TABLE `genetic_alteration`
  CHANGE COLUMN `GENETIC_PROFILE_ID` `GENETIC_PROFILE_ID` int(11) NOT NULL COMMENT 'References genetic_profile.GENETIC_PROFILE_ID.',
  CHANGE COLUMN `GENETIC_ENTITY_ID` `GENETIC_ENTITY_ID` int(11) NOT NULL COMMENT 'References genetic_entity.ID.',
  CHANGE COLUMN `VALUES` `VALUES` longtext NOT NULL COMMENT 'Comma-separated genetic alteration values (e.g., mutations, CNA) in longtext format. Order of values matches order of corresponding sample identifiers in genetic_profile_samples.ORDERED_SAMPLE_LIST';


-- ===========================================
-- Table: genetic_profile_samples
-- ===========================================
ALTER TABLE `genetic_profile_samples`
  CHANGE COLUMN `GENETIC_PROFILE_ID` `GENETIC_PROFILE_ID` int(11) NOT NULL COMMENT 'References genetic_profile.GENETIC_PROFILE_ID.',
  CHANGE COLUMN `ORDERED_SAMPLE_LIST` `ORDERED_SAMPLE_LIST` longtext NOT NULL COMMENT 'Comma-separated ordered list of sample IDs associated with this genetic profile.';


-- ===========================================
-- Table: gene_panel
-- ===========================================
ALTER TABLE `gene_panel`
  CHANGE COLUMN `INTERNAL_ID` `INTERNAL_ID` int(11) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique identifier for the gene panel.',
  CHANGE COLUMN `STABLE_ID` `STABLE_ID` varchar(255) NOT NULL COMMENT 'Stable external identifier for the gene panel.',
  CHANGE COLUMN `DESCRIPTION` `DESCRIPTION` mediumtext COMMENT 'Description of the gene panel contents.';


-- ===========================================
-- Table: gene_panel_list
-- ===========================================
ALTER TABLE `gene_panel_list`
  CHANGE COLUMN `INTERNAL_ID` `INTERNAL_ID` int(11) NOT NULL COMMENT 'References gene_panel.INTERNAL_ID.',
  CHANGE COLUMN `GENE_ID` `GENE_ID` int(11) NOT NULL COMMENT 'References gene.ENTREZ_GENE_ID.';

-- ===========================================
-- Table: sample_profile
-- ===========================================
ALTER TABLE `sample_profile`
  CHANGE COLUMN `SAMPLE_ID` `SAMPLE_ID` int(11) NOT NULL COMMENT 'References sample.INTERNAL_ID.',
  CHANGE COLUMN `GENETIC_PROFILE_ID` `GENETIC_PROFILE_ID` int(11) NOT NULL COMMENT 'References genetic_profile.GENETIC_PROFILE_ID.',
  CHANGE COLUMN `PANEL_ID` `PANEL_ID` int(11) DEFAULT NULL COMMENT 'References gene_panel.INTERNAL_ID. Optional.';


-- ===========================================
-- Table: structural_variant
-- ===========================================
ALTER TABLE `structural_variant`
  CHANGE COLUMN `INTERNAL_ID` `INTERNAL_ID` int(11) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique identifier for the structural variant.',
  CHANGE COLUMN `GENETIC_PROFILE_ID` `GENETIC_PROFILE_ID` int(11) NOT NULL COMMENT 'References genetic_profile.GENETIC_PROFILE_ID.',
  CHANGE COLUMN `SAMPLE_ID` `SAMPLE_ID` int(11) NOT NULL COMMENT 'References sample.INTERNAL_ID.',
  CHANGE COLUMN `SITE1_ENTREZ_GENE_ID` `SITE1_ENTREZ_GENE_ID` int(11) COMMENT 'References gene.ENTREZ_GENE_ID for site 1.',
  CHANGE COLUMN `SITE2_ENTREZ_GENE_ID` `SITE2_ENTREZ_GENE_ID` int(11) COMMENT 'References gene.ENTREZ_GENE_ID for site 2.',
  CHANGE COLUMN `SITE1_ENSEMBL_TRANSCRIPT_ID` `SITE1_ENSEMBL_TRANSCRIPT_ID` varchar(25) COMMENT 'ENSEMBL transcript ID for site 1.',
  CHANGE COLUMN `SITE1_CHROMOSOME` `SITE1_CHROMOSOME` varchar(5) COMMENT 'Chromosome for site 1.',
  CHANGE COLUMN `SITE1_REGION` `SITE1_REGION` varchar(25) COMMENT 'Region for site 1.',
  CHANGE COLUMN `SITE1_REGION_NUMBER` `SITE1_REGION_NUMBER` int(11) COMMENT 'Region number for site 1.',
  CHANGE COLUMN `SITE1_CONTIG` `SITE1_CONTIG` varchar(100) COMMENT 'Contig for site 1.',
  CHANGE COLUMN `SITE1_POSITION` `SITE1_POSITION` int(11) COMMENT 'Genomic position for site 1.',
  CHANGE COLUMN `SITE1_DESCRIPTION` `SITE1_DESCRIPTION` varchar(255) COMMENT 'Description for site 1.',
  CHANGE COLUMN `SITE2_ENSEMBL_TRANSCRIPT_ID` `SITE2_ENSEMBL_TRANSCRIPT_ID` varchar(25) COMMENT 'ENSEMBL transcript ID for site 2.',
  CHANGE COLUMN `SITE2_CHROMOSOME` `SITE2_CHROMOSOME` varchar(5) COMMENT 'Chromosome for site 2.',
  CHANGE COLUMN `SITE2_REGION` `SITE2_REGION` varchar(25) COMMENT 'Region for site 2.',
  CHANGE COLUMN `SITE2_REGION_NUMBER` `SITE2_REGION_NUMBER` int(11) COMMENT 'Region number for site 2.',
  CHANGE COLUMN `SITE2_CONTIG` `SITE2_CONTIG` varchar(100) COMMENT 'Contig for site 2.',
  CHANGE COLUMN `SITE2_POSITION` `SITE2_POSITION` int(11) COMMENT 'Genomic position for site 2.',
  CHANGE COLUMN `SITE2_DESCRIPTION` `SITE2_DESCRIPTION` varchar(255) COMMENT 'Description for site 2.',
  CHANGE COLUMN `SITE2_EFFECT_ON_FRAME` `SITE2_EFFECT_ON_FRAME` varchar(25) COMMENT 'Effect on reading frame for site 2.',
  CHANGE COLUMN `NCBI_BUILD` `NCBI_BUILD` varchar(10) COMMENT 'NCBI genome build used.',
  CHANGE COLUMN `DNA_SUPPORT` `DNA_SUPPORT` varchar(3) COMMENT 'DNA support flag.',
  CHANGE COLUMN `RNA_SUPPORT` `RNA_SUPPORT` varchar(3) COMMENT 'RNA support flag.',
  CHANGE COLUMN `NORMAL_READ_COUNT` `NORMAL_READ_COUNT` int(11) COMMENT 'Read count in normal sample.',
  CHANGE COLUMN `TUMOR_READ_COUNT` `TUMOR_READ_COUNT` int(11) COMMENT 'Read count in tumor sample.',
  CHANGE COLUMN `NORMAL_VARIANT_COUNT` `NORMAL_VARIANT_COUNT` int(11) COMMENT 'Variant count in normal sample.',
  CHANGE COLUMN `TUMOR_VARIANT_COUNT` `TUMOR_VARIANT_COUNT` int(11) COMMENT 'Variant count in tumor sample.',
  CHANGE COLUMN `NORMAL_PAIRED_END_READ_COUNT` `NORMAL_PAIRED_END_READ_COUNT` int(11) COMMENT 'Paired-end read count in normal sample.',
  CHANGE COLUMN `TUMOR_PAIRED_END_READ_COUNT` `TUMOR_PAIRED_END_READ_COUNT` int(11) COMMENT 'Paired-end read count in tumor sample.',
  CHANGE COLUMN `NORMAL_SPLIT_READ_COUNT` `NORMAL_SPLIT_READ_COUNT` int(11) COMMENT 'Split read count in normal sample.',
  CHANGE COLUMN `TUMOR_SPLIT_READ_COUNT` `TUMOR_SPLIT_READ_COUNT` int(11) COMMENT 'Split read count in tumor sample.',
  CHANGE COLUMN `ANNOTATION` `ANNOTATION` varchar(255) COMMENT 'Additional annotation.',
  CHANGE COLUMN `BREAKPOINT_TYPE` `BREAKPOINT_TYPE` varchar(25) COMMENT 'Type of genomic breakpoint.',
  CHANGE COLUMN `CONNECTION_TYPE` `CONNECTION_TYPE` varchar(25) COMMENT 'Connection type of the SV.',
  CHANGE COLUMN `EVENT_INFO` `EVENT_INFO` varchar(255) COMMENT 'Additional event info.',
  CHANGE COLUMN `CLASS` `CLASS` varchar(25) COMMENT 'Class of structural variant.',
  CHANGE COLUMN `LENGTH` `LENGTH` int(11) COMMENT 'Length of structural variant.',
  CHANGE COLUMN `COMMENTS` `COMMENTS` varchar(255) COMMENT 'Comments about the variant.',
  CHANGE COLUMN `SV_STATUS` `SV_STATUS` varchar(25) NOT NULL DEFAULT 'SOMATIC' COMMENT 'GERMLINE or SOMATIC.',
  CHANGE COLUMN `ANNOTATION_JSON` `ANNOTATION_JSON` JSON COMMENT 'JSON-formatted annotation details.';


-- ===========================================
-- Table: alteration_driver_annotation
-- ===========================================
ALTER TABLE `alteration_driver_annotation`
  CHANGE COLUMN `ALTERATION_EVENT_ID` `ALTERATION_EVENT_ID` int(255) NOT NULL COMMENT 'Identifier of the alteration event.',
  CHANGE COLUMN `GENETIC_PROFILE_ID` `GENETIC_PROFILE_ID` int(11) NOT NULL COMMENT 'References genetic_profile.GENETIC_PROFILE_ID.',
  CHANGE COLUMN `SAMPLE_ID` `SAMPLE_ID` int(11) NOT NULL COMMENT 'References sample.INTERNAL_ID.',
  CHANGE COLUMN `DRIVER_FILTER` `DRIVER_FILTER` VARCHAR(20) COMMENT 'Driver filter applied.',
  CHANGE COLUMN `DRIVER_FILTER_ANNOTATION` `DRIVER_FILTER_ANNOTATION` VARCHAR(80) COMMENT 'Annotation for driver filter.',
  CHANGE COLUMN `DRIVER_TIERS_FILTER` `DRIVER_TIERS_FILTER` VARCHAR(50) COMMENT 'Driver tiers filter applied.',
  CHANGE COLUMN `DRIVER_TIERS_FILTER_ANNOTATION` `DRIVER_TIERS_FILTER_ANNOTATION` VARCHAR(80) COMMENT 'Annotation for driver tiers filter.';


-- ===========================================
-- Table: mutation_event
-- ===========================================
ALTER TABLE `mutation_event`
  CHANGE COLUMN `MUTATION_EVENT_ID` `MUTATION_EVENT_ID` int(255) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique identifier for the mutation event.',
  CHANGE COLUMN `ENTREZ_GENE_ID` `ENTREZ_GENE_ID` int(11) NOT NULL COMMENT 'References gene.ENTREZ_GENE_ID.',
  CHANGE COLUMN `CHR` `CHR` varchar(5) COMMENT 'Chromosome where mutation occurs.',
  CHANGE COLUMN `START_POSITION` `START_POSITION` bigint(20) COMMENT 'Start genomic position.',
  CHANGE COLUMN `END_POSITION` `END_POSITION` bigint(20) COMMENT 'End genomic position.',
  CHANGE COLUMN `REFERENCE_ALLELE` `REFERENCE_ALLELE` text COMMENT 'Reference allele sequence.',
  CHANGE COLUMN `TUMOR_SEQ_ALLELE` `TUMOR_SEQ_ALLELE` text COMMENT 'Tumor allele sequence.',
  CHANGE COLUMN `PROTEIN_CHANGE` `PROTEIN_CHANGE` varchar(255) COMMENT 'Protein-level change caused by mutation.',
  CHANGE COLUMN `MUTATION_TYPE` `MUTATION_TYPE` varchar(255) COMMENT 'Type of mutation (e.g., Missense, Nonsense).',
  CHANGE COLUMN `NCBI_BUILD` `NCBI_BUILD` varchar(10) COMMENT 'NCBI genome build used.',
  CHANGE COLUMN `STRAND` `STRAND` varchar(2) COMMENT 'Strand (+/-) of the mutation.',
  CHANGE COLUMN `VARIANT_TYPE` `VARIANT_TYPE` varchar(15) COMMENT 'Variant type (e.g., SNP, INDEL).',
  CHANGE COLUMN `DB_SNP_RS` `DB_SNP_RS` varchar(25) COMMENT 'dbSNP identifier.',
  CHANGE COLUMN `DB_SNP_VAL_STATUS` `DB_SNP_VAL_STATUS` varchar(255) COMMENT 'Validation status in dbSNP.',
  CHANGE COLUMN `REFSEQ_MRNA_ID` `REFSEQ_MRNA_ID` varchar(64) COMMENT 'RefSeq mRNA ID.',
  CHANGE COLUMN `CODON_CHANGE` `CODON_CHANGE` varchar(255) COMMENT 'Codon change.',
  CHANGE COLUMN `UNIPROT_ACCESSION` `UNIPROT_ACCESSION` varchar(64) COMMENT 'UniProt accession ID.',
  CHANGE COLUMN `PROTEIN_POS_START` `PROTEIN_POS_START` int(11) COMMENT 'Start position on protein.',
  CHANGE COLUMN `PROTEIN_POS_END` `PROTEIN_POS_END` int(11) COMMENT 'End position on protein.',
  CHANGE COLUMN `CANONICAL_TRANSCRIPT` `CANONICAL_TRANSCRIPT` boolean COMMENT 'Flag for canonical transcript.',
  CHANGE COLUMN `KEYWORD` `KEYWORD` varchar(255) DEFAULT NULL COMMENT 'Keyword annotation (e.g., truncating, V200 Missense).';


-- ===========================================
-- Table: mutation
-- ===========================================
ALTER TABLE `mutation`
  CHANGE COLUMN `MUTATION_EVENT_ID` `MUTATION_EVENT_ID` int(255) NOT NULL COMMENT 'References mutation_event.MUTATION_EVENT_ID.',
  CHANGE COLUMN `GENETIC_PROFILE_ID` `GENETIC_PROFILE_ID` int(11) NOT NULL COMMENT 'References genetic_profile.GENETIC_PROFILE_ID.',
  CHANGE COLUMN `SAMPLE_ID` `SAMPLE_ID` int(11) NOT NULL COMMENT 'References sample.INTERNAL_ID.',
  CHANGE COLUMN `ENTREZ_GENE_ID` `ENTREZ_GENE_ID` int(11) NOT NULL COMMENT 'References gene.ENTREZ_GENE_ID.',
  CHANGE COLUMN `CENTER` `CENTER` varchar(100) COMMENT 'Center where sequencing was performed.',
  CHANGE COLUMN `SEQUENCER` `SEQUENCER` varchar(255) COMMENT 'Sequencing platform used.',
  CHANGE COLUMN `MUTATION_STATUS` `MUTATION_STATUS` varchar(25) COMMENT 'Mutation status: Germline, Somatic, or LOH.',
  CHANGE COLUMN `VALIDATION_STATUS` `VALIDATION_STATUS` varchar(25) COMMENT 'Validation status.',
  CHANGE COLUMN `TUMOR_SEQ_ALLELE1` `TUMOR_SEQ_ALLELE1` TEXT COMMENT 'Tumor allele 1 sequence.',
  CHANGE COLUMN `TUMOR_SEQ_ALLELE2` `TUMOR_SEQ_ALLELE2` TEXT COMMENT 'Tumor allele 2 sequence.',
  CHANGE COLUMN `MATCHED_NORM_SAMPLE_BARCODE` `MATCHED_NORM_SAMPLE_BARCODE` varchar(255) COMMENT 'Matched normal sample barcode.',
  CHANGE COLUMN `MATCH_NORM_SEQ_ALLELE1` `MATCH_NORM_SEQ_ALLELE1` TEXT COMMENT 'Matched normal allele 1 sequence.',
  CHANGE COLUMN `MATCH_NORM_SEQ_ALLELE2` `MATCH_NORM_SEQ_ALLELE2` TEXT COMMENT 'Matched normal allele 2 sequence.',
  CHANGE COLUMN `TUMOR_VALIDATION_ALLELE1` `TUMOR_VALIDATION_ALLELE1` TEXT COMMENT 'Tumor validation allele 1 sequence.',
  CHANGE COLUMN `TUMOR_VALIDATION_ALLELE2` `TUMOR_VALIDATION_ALLELE2` TEXT COMMENT 'Tumor validation allele 2 sequence.',
  CHANGE COLUMN `MATCH_NORM_VALIDATION_ALLELE1` `MATCH_NORM_VALIDATION_ALLELE1` TEXT COMMENT 'Matched normal validation allele 1.',
  CHANGE COLUMN `MATCH_NORM_VALIDATION_ALLELE2` `MATCH_NORM_VALIDATION_ALLELE2` TEXT COMMENT 'Matched normal validation allele 2.',
  CHANGE COLUMN `VERIFICATION_STATUS` `VERIFICATION_STATUS` varchar(10) COMMENT 'Verification status.',
  CHANGE COLUMN `SEQUENCING_PHASE` `SEQUENCING_PHASE` varchar(100) COMMENT 'Sequencing phase.',
  CHANGE COLUMN `SEQUENCE_SOURCE` `SEQUENCE_SOURCE` varchar(255) NOT NULL COMMENT 'Source of sequencing data.',
  CHANGE COLUMN `VALIDATION_METHOD` `VALIDATION_METHOD` varchar(255) COMMENT 'Validation method used.',
  CHANGE COLUMN `SCORE` `SCORE` varchar(100) COMMENT 'Score or quality metric.',
  CHANGE COLUMN `BAM_FILE` `BAM_FILE` varchar(255) COMMENT 'Associated BAM file.',
  CHANGE COLUMN `TUMOR_ALT_COUNT` `TUMOR_ALT_COUNT` int(11) COMMENT 'Tumor alternate allele count.',
  CHANGE COLUMN `TUMOR_REF_COUNT` `TUMOR_REF_COUNT` int(11) COMMENT 'Tumor reference allele count.',
  CHANGE COLUMN `NORMAL_ALT_COUNT` `NORMAL_ALT_COUNT` int(11) COMMENT 'Normal alternate allele count.',
  CHANGE COLUMN `NORMAL_REF_COUNT` `NORMAL_REF_COUNT` int(11) COMMENT 'Normal reference allele count.',
  CHANGE COLUMN `AMINO_ACID_CHANGE` `AMINO_ACID_CHANGE` varchar(255) COMMENT 'Amino acid change from mutation.',
  CHANGE COLUMN `ANNOTATION_JSON` `ANNOTATION_JSON` JSON COMMENT 'JSON-formatted annotations.';


-- ===========================================
-- Table: mutation_count_by_keyword
-- ===========================================
ALTER TABLE `mutation_count_by_keyword`
  CHANGE COLUMN `GENETIC_PROFILE_ID` `GENETIC_PROFILE_ID` int(11) NOT NULL COMMENT 'References genetic_profile.GENETIC_PROFILE_ID.',
  CHANGE COLUMN `KEYWORD` `KEYWORD` varchar(255) DEFAULT NULL COMMENT 'Mutation keyword annotation.',
  CHANGE COLUMN `ENTREZ_GENE_ID` `ENTREZ_GENE_ID` int(11) NOT NULL COMMENT 'References gene.ENTREZ_GENE_ID.',
  CHANGE COLUMN `KEYWORD_COUNT` `KEYWORD_COUNT` int NOT NULL COMMENT 'Number of mutations matching the keyword.',
  CHANGE COLUMN `GENE_COUNT` `GENE_COUNT` int NOT NULL COMMENT 'Number of mutations for the gene.';


-- ===========================================
-- Table: clinical_patient
-- ===========================================
ALTER TABLE `clinical_patient`
  CHANGE COLUMN `INTERNAL_ID` `INTERNAL_ID` int(11) NOT NULL COMMENT 'References patient.INTERNAL_ID.',
  CHANGE COLUMN `ATTR_ID` `ATTR_ID` varchar(255) NOT NULL COMMENT 'Attribute identifier.',
  CHANGE COLUMN `ATTR_VALUE` `ATTR_VALUE` varchar(255) NOT NULL COMMENT 'Value of the clinical attribute.';


-- ===========================================
-- Table: clinical_sample
-- ===========================================
ALTER TABLE `clinical_sample`
  CHANGE COLUMN `INTERNAL_ID` `INTERNAL_ID` int(11) NOT NULL COMMENT 'References sample.INTERNAL_ID.',
  CHANGE COLUMN `ATTR_ID` `ATTR_ID` varchar(255) NOT NULL COMMENT 'Attribute identifier.',
  CHANGE COLUMN `ATTR_VALUE` `ATTR_VALUE` varchar(255) NOT NULL COMMENT 'Value of the clinical attribute.';


-- ===========================================
-- Table: clinical_attribute_meta
-- ===========================================
ALTER TABLE `clinical_attribute_meta`
  CHANGE COLUMN `ATTR_ID` `ATTR_ID` varchar(255) NOT NULL COMMENT 'Clinical attribute identifier.',
  CHANGE COLUMN `DISPLAY_NAME` `DISPLAY_NAME` varchar(255) NOT NULL COMMENT 'Human-readable display name of the attribute.',
  CHANGE COLUMN `DESCRIPTION` `DESCRIPTION` varchar(2048) NOT NULL COMMENT 'Description of the attribute.',
  CHANGE COLUMN `DATATYPE` `DATATYPE` varchar(255) NOT NULL COMMENT 'Data type: NUMBER, BOOLEAN, or STRING.',
  CHANGE COLUMN `PATIENT_ATTRIBUTE` `PATIENT_ATTRIBUTE` BOOLEAN NOT NULL COMMENT 'Flag indicating if the attribute is for patient-level data.',
  CHANGE COLUMN `PRIORITY` `PRIORITY` varchar(255) NOT NULL COMMENT 'Priority for display or processing.',
  CHANGE COLUMN `CANCER_STUDY_ID` `CANCER_STUDY_ID` int(11) NOT NULL COMMENT 'References cancer_study.CANCER_STUDY_ID.';

-- ===========================================
-- Table: mut_sig
-- ===========================================
ALTER TABLE `mut_sig`
  CHANGE COLUMN `CANCER_STUDY_ID` `CANCER_STUDY_ID` int(11) NOT NULL COMMENT 'References cancer_study.CANCER_STUDY_ID.',
  CHANGE COLUMN `ENTREZ_GENE_ID` `ENTREZ_GENE_ID` int(11) NOT NULL COMMENT 'References gene.ENTREZ_GENE_ID.',
  CHANGE COLUMN `RANK` `RANK` int(11) NOT NULL COMMENT 'Rank of the gene in mutational significance.',
  CHANGE COLUMN `NumBasesCovered` `NumBasesCovered` int(11) NOT NULL COMMENT 'Number of bases covered in the study for this gene.',
  CHANGE COLUMN `NumMutations` `NumMutations` int(11) NOT NULL COMMENT 'Number of mutations observed in this gene.',
  CHANGE COLUMN `P_VALUE` `P_VALUE` float NOT NULL COMMENT 'P-value of mutational significance.',
  CHANGE COLUMN `Q_VALUE` `Q_VALUE` float NOT NULL COMMENT 'Q-value (FDR) of mutational significance.';


-- ===========================================
-- Table: gistic
-- ===========================================
ALTER TABLE `gistic`
  CHANGE COLUMN `GISTIC_ROI_ID` `GISTIC_ROI_ID` bigint(20) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique identifier for GISTIC region of interest.',
  CHANGE COLUMN `CANCER_STUDY_ID` `CANCER_STUDY_ID` int(11) NOT NULL COMMENT 'References cancer_study.CANCER_STUDY_ID.',
  CHANGE COLUMN `CHROMOSOME` `CHROMOSOME` int(11) NOT NULL COMMENT 'Chromosome of the ROI.',
  CHANGE COLUMN `CYTOBAND` `CYTOBAND` varchar(255) NOT NULL COMMENT 'Cytogenetic band of the ROI.',
  CHANGE COLUMN `WIDE_PEAK_START` `WIDE_PEAK_START` int(11) NOT NULL COMMENT 'Start position of the wide peak.',
  CHANGE COLUMN `WIDE_PEAK_END` `WIDE_PEAK_END` int(11) NOT NULL COMMENT 'End position of the wide peak.',
  CHANGE COLUMN `Q_VALUE` `Q_VALUE` double NOT NULL COMMENT 'Q-value of the GISTIC peak.',
  CHANGE COLUMN `AMP` `AMP` tinyint(1) NOT NULL COMMENT '1 if amplified, 0 otherwise.';


-- ===========================================
-- Table: gistic_to_gene
-- ===========================================
ALTER TABLE `gistic_to_gene`
  CHANGE COLUMN `GISTIC_ROI_ID` `GISTIC_ROI_ID` bigint(20) NOT NULL COMMENT 'References gistic.GISTIC_ROI_ID.',
  CHANGE COLUMN `ENTREZ_GENE_ID` `ENTREZ_GENE_ID` int(11) NOT NULL COMMENT 'References gene.ENTREZ_GENE_ID.';


-- ===========================================
-- Table: cna_event
-- ===========================================
ALTER TABLE `cna_event`
  CHANGE COLUMN `CNA_EVENT_ID` `CNA_EVENT_ID` int(255) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique identifier for CNA event.',
  CHANGE COLUMN `ENTREZ_GENE_ID` `ENTREZ_GENE_ID` int(11) NOT NULL COMMENT 'References gene.ENTREZ_GENE_ID.',
  CHANGE COLUMN `ALTERATION` `ALTERATION` tinyint NOT NULL COMMENT 'Type of copy number alteration (e.g., gain or loss).';


-- ===========================================
-- Table: sample_cna_event
-- ===========================================
ALTER TABLE `sample_cna_event`
  CHANGE COLUMN `CNA_EVENT_ID` `CNA_EVENT_ID` int(255) NOT NULL COMMENT 'References cna_event.CNA_EVENT_ID.',
  CHANGE COLUMN `SAMPLE_ID` `SAMPLE_ID` int(11) NOT NULL COMMENT 'References sample.INTERNAL_ID.',
  CHANGE COLUMN `GENETIC_PROFILE_ID` `GENETIC_PROFILE_ID` int(11) NOT NULL COMMENT 'References genetic_profile.GENETIC_PROFILE_ID.',
  CHANGE COLUMN `ANNOTATION_JSON` `ANNOTATION_JSON` JSON COMMENT 'JSON-formatted annotation details.';


-- ===========================================
-- Table: copy_number_seg
-- ===========================================
ALTER TABLE `copy_number_seg`
  CHANGE COLUMN `SEG_ID` `SEG_ID` bigint(20) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique segment identifier.',
  CHANGE COLUMN `CANCER_STUDY_ID` `CANCER_STUDY_ID` int(11) NOT NULL COMMENT 'References cancer_study.CANCER_STUDY_ID.',
  CHANGE COLUMN `SAMPLE_ID` `SAMPLE_ID` int(11) NOT NULL COMMENT 'References sample.INTERNAL_ID.',
  CHANGE COLUMN `CHR` `CHR` varchar(5) NOT NULL COMMENT 'Chromosome of the segment.',
  CHANGE COLUMN `START` `START` int(11) NOT NULL COMMENT 'Start position of the segment.',
  CHANGE COLUMN `END` `END` int(11) NOT NULL COMMENT 'End position of the segment.',
  CHANGE COLUMN `NUM_PROBES` `NUM_PROBES` int(11) NOT NULL COMMENT 'Number of probes used for this segment.',
  CHANGE COLUMN `SEGMENT_MEAN` `SEGMENT_MEAN` double NOT NULL COMMENT 'Segment mean copy number.';


-- ===========================================
-- Table: copy_number_seg_file
-- ===========================================
ALTER TABLE `copy_number_seg_file`
  CHANGE COLUMN `SEG_FILE_ID` `SEG_FILE_ID` int(11) NOT NULL AUTO_INCREMENT COMMENT 'Primary key. Unique segment file identifier.',
  CHANGE COLUMN `CANCER_STUDY_ID` `CANCER_STUDY_ID` int(11) NOT NULL COMMENT 'References cancer_study.CANCER_STUDY_ID.',
  CHANGE COLUMN `REFERENCE_GENOME_ID` `REFERENCE_GENOME_ID` varchar(10) NOT NULL COMMENT 'Reference genome version used.',
  CHANGE COLUMN `DESCRIPTION` `DESCRIPTION` varchar(255) NOT NULL COMMENT 'Description of the file.',
  CHANGE COLUMN `FILENAME` `FILENAME` varchar(255) NOT NULL COMMENT 'Name of the segment file.';


-- ===========================================
-- Table: cosmic_mutation
-- ===========================================
ALTER TABLE `cosmic_mutation`
  CHANGE COLUMN `COSMIC_MUTATION_ID` `COSMIC_MUTATION_ID` varchar(30) NOT NULL COMMENT 'Primary key. COSMIC mutation identifier.',
  CHANGE COLUMN `CHR` `CHR` varchar(5) COMMENT 'Chromosome where mutation occurs.',
  CHANGE COLUMN `START_POSITION` `START_POSITION` bigint(20) COMMENT 'Start genomic position of the mutation.',
  CHANGE COLUMN `REFERENCE_ALLELE` `REFERENCE_ALLELE` varchar(255) COMMENT 'Reference allele sequence.',
  CHANGE COLUMN `TUMOR_SEQ_ALLELE` `TUMOR_SEQ_ALLELE` varchar(255) COMMENT 'Tumor allele sequence.',
  CHANGE COLUMN `STRAND` `STRAND` varchar(2) COMMENT 'Strand (+/-) of the mutation.',
  CHANGE COLUMN `CODON_CHANGE` `CODON_CHANGE` varchar(255) COMMENT 'Codon change annotation.',
  CHANGE COLUMN `ENTREZ_GENE_ID` `ENTREZ_GENE_ID` int(11) NOT NULL COMMENT 'References gene.ENTREZ_GENE_ID.',
  CHANGE COLUMN `PROTEIN_CHANGE` `PROTEIN_CHANGE` varchar(255) NOT NULL COMMENT 'Protein-level change caused by mutation.',
  CHANGE COLUMN `COUNT` `COUNT` int(11) NOT NULL COMMENT 'Number of samples observed with this mutation.',
  CHANGE COLUMN `KEYWORD` `KEYWORD` varchar(50) DEFAULT NULL COMMENT 'Keyword annotation.';


-- ===========================================
-- Table: clinical_event
-- ===========================================
ALTER TABLE `clinical_event`
  CHANGE COLUMN `PATIENT_ID` `PATIENT_ID` int(11) NOT NULL COMMENT 'References patient.INTERNAL_ID.',
  CHANGE COLUMN `START_DATE` `START_DATE` int NOT NULL COMMENT 'Start date of the clinical event (epoch or numeric format).',
  CHANGE COLUMN `STOP_DATE` `STOP_DATE` int COMMENT 'Stop date of the clinical event (optional).',
  CHANGE COLUMN `EVENT_TYPE` `EVENT_TYPE` varchar(20) NOT NULL COMMENT 'Type of clinical event (e.g. Specimen, Treatment, Surgery,...).';


-- ===========================================
-- Table: clinical_event_data
-- ===========================================
ALTER TABLE `clinical_event_data`
  CHANGE COLUMN `KEY` `KEY` varchar(255) NOT NULL COMMENT 'Data key.',
  CHANGE COLUMN `VALUE` `VALUE` varchar(5000) NOT NULL COMMENT 'Value associated with the key.';


-- ===========================================
-- Table: reference_genome_gene
-- ===========================================
ALTER TABLE `reference_genome_gene`
  CHANGE COLUMN `ENTREZ_GENE_ID` `ENTREZ_GENE_ID` int(11) NOT NULL COMMENT 'References gene.ENTREZ_GENE_ID.',
  CHANGE COLUMN `REFERENCE_GENOME_ID` `REFERENCE_GENOME_ID` int(4) NOT NULL COMMENT 'References reference_genome.REFERENCE_GENOME_ID.',
  CHANGE COLUMN `CHR` `CHR` varchar(5) DEFAULT NULL COMMENT 'Chromosome of the gene (optional).',
  CHANGE COLUMN `CYTOBAND` `CYTOBAND` varchar(64) DEFAULT NULL COMMENT 'Cytoband location of the gene (optional).',
  CHANGE COLUMN `START` `START` bigint(20) DEFAULT NULL COMMENT 'Start position of the gene (optional).',
  CHANGE COLUMN `END` `END` bigint(20) DEFAULT NULL COMMENT 'End position of the gene (optional).';


-- ===========================================
-- Table: allele_specific_copy_number
-- ===========================================
ALTER TABLE `allele_specific_copy_number`
  CHANGE COLUMN `MUTATION_EVENT_ID` `MUTATION_EVENT_ID` int(255) NOT NULL COMMENT 'References mutation_event.MUTATION_EVENT_ID.',
  CHANGE COLUMN `GENETIC_PROFILE_ID` `GENETIC_PROFILE_ID` int(11) NOT NULL COMMENT 'References genetic_profile.GENETIC_PROFILE_ID.',
  CHANGE COLUMN `SAMPLE_ID` `SAMPLE_ID` int(11) NOT NULL COMMENT 'References sample.INTERNAL_ID.',
  CHANGE COLUMN `ASCN_INTEGER_COPY_NUMBER` `ASCN_INTEGER_COPY_NUMBER` int DEFAULT NULL COMMENT 'Allele-specific integer copy number (optional).',
  CHANGE COLUMN `ASCN_METHOD` `ASCN_METHOD` varchar(24) NOT NULL COMMENT 'Method used to determine ASCN.',
  CHANGE COLUMN `CCF_EXPECTED_COPIES_UPPER` `CCF_EXPECTED_COPIES_UPPER` float DEFAULT NULL COMMENT 'Expected upper bound of CCF copies.',
  CHANGE COLUMN `CCF_EXPECTED_COPIES` `CCF_EXPECTED_COPIES` float DEFAULT NULL COMMENT 'Expected copies from CCF.',
  CHANGE COLUMN `CLONAL` `CLONAL` varchar(16) DEFAULT NULL COMMENT 'Clonality annotation (optional).',
  CHANGE COLUMN `MINOR_COPY_NUMBER` `MINOR_COPY_NUMBER` int DEFAULT NULL COMMENT 'Minor allele copy number (optional).',
  CHANGE COLUMN `EXPECTED_ALT_COPIES` `EXPECTED_ALT_COPIES` int DEFAULT NULL COMMENT 'Expected alternate allele copies.',
  CHANGE COLUMN `TOTAL_COPY_NUMBER` `TOTAL_COPY_NUMBER` int DEFAULT NULL COMMENT 'Total copy number.';


-- ===========================================
-- Table: info
-- ===========================================
ALTER TABLE `info`
  CHANGE COLUMN `DB_SCHEMA_VERSION` `DB_SCHEMA_VERSION` varchar(24) COMMENT 'Version of the database schema.',
  CHANGE COLUMN `GENESET_VERSION` `GENESET_VERSION` varchar(24) COMMENT 'Version of the geneset.';

-- ===========================================
-- Table: resource_definition
-- ===========================================
ALTER TABLE `resource_definition`
  CHANGE COLUMN `RESOURCE_ID` `RESOURCE_ID` varchar(255) NOT NULL COMMENT 'Primary key. Unique identifier for the resource.',
  CHANGE COLUMN `DISPLAY_NAME` `DISPLAY_NAME` varchar(255) NOT NULL COMMENT 'Human-readable name of the resource.',
  CHANGE COLUMN `DESCRIPTION` `DESCRIPTION` varchar(2048) DEFAULT NULL COMMENT 'Description of the resource (optional).',
  CHANGE COLUMN `RESOURCE_TYPE` `RESOURCE_TYPE` ENUM('STUDY','PATIENT','SAMPLE') NOT NULL COMMENT 'Type of resource: STUDY, PATIENT, or SAMPLE.',
  CHANGE COLUMN `OPEN_BY_DEFAULT` `OPEN_BY_DEFAULT` BOOLEAN DEFAULT 0 COMMENT 'Whether the resource is open by default.',
  CHANGE COLUMN `PRIORITY` `PRIORITY` int(11) NOT NULL COMMENT 'Priority of the resource for display or access.',
  CHANGE COLUMN `CANCER_STUDY_ID` `CANCER_STUDY_ID` int(11) NOT NULL COMMENT 'References cancer_study.CANCER_STUDY_ID.',
  CHANGE COLUMN `CUSTOM_METADATA` `CUSTOM_METADATA` JSON COMMENT 'Optional JSON field for custom metadata.';


-- ===========================================
-- Table: resource_sample
-- ===========================================
ALTER TABLE `resource_sample`
  CHANGE COLUMN `INTERNAL_ID` `INTERNAL_ID` int(11) NOT NULL COMMENT 'References sample.INTERNAL_ID.',
  CHANGE COLUMN `RESOURCE_ID` `RESOURCE_ID` varchar(255) NOT NULL COMMENT 'References resource_definition.RESOURCE_ID.',
  CHANGE COLUMN `URL` `URL` varchar(255) NOT NULL COMMENT 'URL or link associated with this resource and sample.';


-- ===========================================
-- Table: resource_patient
-- ===========================================
ALTER TABLE `resource_patient`
  CHANGE COLUMN `INTERNAL_ID` `INTERNAL_ID` int(11) NOT NULL COMMENT 'References patient.INTERNAL_ID.',
  CHANGE COLUMN `RESOURCE_ID` `RESOURCE_ID` varchar(255) NOT NULL COMMENT 'References resource_definition.RESOURCE_ID.',
  CHANGE COLUMN `URL` `URL` varchar(255) NOT NULL COMMENT 'URL or link associated with this resource and patient.';


-- ===========================================
-- Table: resource_study
-- ===========================================
ALTER TABLE `resource_study`
  CHANGE COLUMN `INTERNAL_ID` `INTERNAL_ID` int(11) NOT NULL COMMENT 'References cancer_study.CANCER_STUDY_ID.',
  CHANGE COLUMN `RESOURCE_ID` `RESOURCE_ID` varchar(255) NOT NULL COMMENT 'References resource_definition.RESOURCE_ID.',
  CHANGE COLUMN `URL` `URL` varchar(255) NOT NULL COMMENT 'URL or link associated with this resource and study.';


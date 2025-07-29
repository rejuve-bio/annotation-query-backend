from enum import Enum
import os

class TaskStatus(Enum):
    PENDING = 'PENDING'
    CANCELLED = 'CANCELLED'
    COMPLETE = 'COMPLETE'
    FAILED = 'FAILED'

class Species(Enum):
    HUMAN = {
        'id': 'human',
        'name': 'Human'
    }

    FLY = {
        'id': 'fly',
        'name': 'Fly'
    }

# Define locationInputs equivalent in Python
location_inputs = [
    {
        "name": "chr",
        "label": "Chromosome",
        "inputType": "combobox",
        "options": [{"value": "X"}, {"value": "Y"}] + [{"value": str(i + 1)} for i in range(22)]
    },
    {"label": "Start", "name": "start", "inputType": "input", "type": "number"},
    {"label": "End", "name": "end", "inputType": "input", "type": "number"}
]

# Define formFields equivalent in Python
form_fields = {
    "c": location_inputs,
    "super_enhancer": location_inputs,
    "enhancer": location_inputs,
    "promoter": location_inputs,
    "tad": location_inputs,
    "tfbs": location_inputs,
    "unberon": [{"label": "Name", "name": "term_name", "inputType": "input"}],
    "clo": [{"label": "Name", "name": "term_name", "inputType": "input"}],
    "cl": [{"label": "Name", "name": "term_name", "inputType": "input"}],
    "efo": [{"label": "Name", "name": "term_name", "inputType": "input"}],
    "bto": [{"label": "Name", "name": "term_name", "inputType": "input"}],
    "motif": [{"label": "Name", "name": "tf_name", "inputType": "input"}],
    "pathway": [{"label": "Name", "name": "pathway_name", "inputType": "input"}],
    "gene": [
        {"label": "Name", "name": "gene_name", "inputType": "input"},
        {
            "label": "Type",
            "name": "gene_type",
            "inputType": "combobox",
            "options": [{"value": v} for v in [
                "lncRNA", "snRNA", "snoRNA", "processed_pseudogene", "transcribed_unprocessed_pseudogene",
                "protein_coding", "unprocessed_pseudogene", "TEC", "miRNA", "rRNA_pseudogene", "scaRNA",
                "misc_RNA", "transcribed_processed_pseudogene", "transcribed_unitary_pseudogene", "rRNA",
                "unitary_pseudogene", "pseudogene", "IG_V_pseudogene", "scRNA", "sRNA", "IG_C_gene",
                "IG_J_gene", "IG_V_gene", "translated_processed_pseudogene", "ribozyme", "vault_RNA",
                "TR_V_gene", "TR_V_pseudogene", "TR_C_gene", "TR_J_gene", "TR_D_gene", "IG_C_pseudogene",
                "TR_J_pseudogene", "IG_J_pseudogene", "IG_D_gene", "IG_pseudogene", "artifact",
                "Mt_tRNA", "Mt_rRNA"
            ]]
        },
        *location_inputs
    ],
    "protein": [{"label": "Name", "name": "protein_name", "inputType": "input"}],
    "transcript": [
        {"label": "Gene name", "name": "gene_name", "inputType": "input"},
        {"label": "Transcript name", "name": "transcript_name", "inputType": "input"},
        {
            "label": "Type",
            "name": "transcript_type",
            "inputType": "combobox",
            "options": [{"value": v} for v in [
                "processed_transcript", "lncRNA", "transcribed_unprocessed_pseudogene", "unprocessed_pseudogene",
                "miRNA", "nonsense_mediated_decay", "transcribed_unitary_pseudogene", "protein_coding",
                "protein_coding_CDS_not_defined", "retained_intron", "misc_RNA", "processed_pseudogene",
                "transcribed_processed_pseudogene", "snRNA", "snoRNA", "TEC", "rRNA_pseudogene", "scaRNA",
                "non_stop_decay", "protein_coding_LoF", "unitary_pseudogene", "pseudogene", "rRNA",
                "IG_V_pseudogene", "scRNA", "IG_V_gene", "IG_C_gene", "IG_J_gene", "sRNA", "ribozyme",
                "translated_processed_pseudogene", "vault_RNA", "TR_C_gene", "TR_J_gene", "TR_V_gene",
                "TR_V_pseudogene", "TR_D_gene", "IG_C_pseudogene", "TR_J_pseudogene", "IG_J_pseudogene",
                "IG_D_gene", "IG_pseudogene", "artifact", "Mt_tRNA", "Mt_rRNA"
            ]]
        }
    ],
    "exon": [
        {"label": "Gene ID", "name": "gene_id", "inputType": "input"},
        {"label": "Transcript ID", "name": "transcript_id", "inputType": "input"},
        {"label": "Exon number", "name": "exon_number", "inputType": "input"},
        *location_inputs
    ],
    "snp": [
        {"label": "Ref", "name": "ref", "inputType": "input"},
        {"label": "Alt", "name": "alt", "inputType": "input"},
        {"label": "Caf_ref", "name": "caf_ref", "inputType": "input"},
        {"label": "Caf_alt", "name": "caf_alt", "inputType": "input"},
        *location_inputs
    ],
    "sv": [
        {
            "label": "Variant type",
            "name": "variant_type",
            "inputType": "combobox",
            "options": [{"value": v} for v in [
                "duplication", "deletion", "loss", "gain+loss", "complex", "gain", "insertion", "inversion",
                "tandem duplication", "sva insertion", "alu insertion", "novel sequence insertion",
                "sequence alteration", "mobile element insertion", "mobile element deletion", "line1 deletion",
                "alu deletion", "line1 insertion", "sva deletion", "herv deletion", "herv insertion",
                "copy number variation"
            ]]
        },
        *location_inputs
    ],
    "non_coding_rna": [
        {
            "label": "RNA type",
            "name": "rna_type",
            "inputType": "combobox",
            "options": [{"value": v} for v in [
                "piRNA", "tRNA", "SRP_RNA", "lncRNA", "sRNA", "miRNA", "pre_miRNA", "snRNA", "misc_RNA",
                "snoRNA", "precursor_RNA", "scRNA", "antisense_RNA", "ncRNA", "Y_RNA", "circRNA", "scaRNA",
                "rRNA", "ribozyme", "other", "guide_RNA", "autocatalytically_spliced_intron", "RNase_P_RNA",
                "vault_RNA", "RNase_MRP_RNA", "hammerhead_ribozyme", "telomerase_RNA"
            ]]
        },
        *location_inputs
    ],
    "go": [
        {"label": "Term name", "name": "term_name", "inputType": "input"},
        {
            "label": "Subontology",
            "name": "subontology",
            "inputType": "combobox",
            "options": [{"value": v} for v in [
                "biological_process", "molecular_function", "cellular_component", "external", "gene_ontology"
            ]]
        }
    ]
}

# Define the absolute path to the JSON file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GRAPH_INFO_PATH = os.path.join(BASE_DIR, '../Data/count_info.json')

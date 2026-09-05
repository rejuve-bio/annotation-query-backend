from enum import Enum
import os
from dotenv import load_dotenv

load_dotenv()

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
    "promoter": [
        {"label": "Taxon ID", "name": "taxon_id", "inputType": "input"},
        *location_inputs
    ],
    "tad": location_inputs,
    "tfbs": location_inputs,
    "unberon": [{"label": "Name", "name": "term_name", "inputType": "input"}],
    "clo": [{"label": "Name", "name": "term_name", "inputType": "input"}],
    "cl": [{"label": "Name", "name": "term_name", "inputType": "input"}],
    "efo": [{"label": "Name", "name": "term_name", "inputType": "input"}],
    "bto": [{"label": "Name", "name": "term_name", "inputType": "input"}],
    "motif": [{"label": "Name", "name": "tf_name", "inputType": "input"}],
    "anatomy": [
        {"label": "Name", "name": "term_name", "inputType": "input"},
    ],
    "tissue": [
        {"label": "Name", "name": "term_name", "inputType": "input"},
    ],
    "cell_type": [
        {"label": "Name", "name": "term_name", "inputType": "input"},
    ],
    "cell_line": [
        {"label": "Name", "name": "term_name", "inputType": "input"},
    ],
    "phenotype": [
        {"label": "Name", "name": "term_name", "inputType": "input"},
    ],
    "small_molecule": [
        {"label": "Name", "name": "term_name", "inputType": "input"},
    ],
    "reaction": [
        {"label": "Name", "name": "reaction_name", "inputType": "input"},
        {"label": "Taxon ID", "name": "taxon_id", "inputType": "input"},
    ],
    "pathway": [
        {"label": "Name", "name": "pathway_name", "inputType": "input"},
        {"label": "Taxon ID", "name": "taxon_id", "inputType": "input"},
    ],
    "disease": [
        {"label": "Name", "name": "term_name", "inputType": "input"},
    ],
    "developmental_stage": [
        {"label": "Name", "name": "term_name", "inputType": "input"},
    ],
    "sequence_type": [
        {"label": "Name", "name": "term_name", "inputType": "input"},
    ],
    "allele": [
        {"label": "Symbol", "name": "allele_symbol", "inputType": "input"},
        {"label": "Taxon ID", "name": "taxon_id", "inputType": "input"},
    ],
    "genotype": [
        {"label": "Genotype symbols", "name": "genotype_symbols", "inputType": "input"},
        {"label": "Genotype IDs", "name": "genotype_ids", "inputType": "input"},
        {"label": "Taxon ID", "name": "taxon_id", "inputType": "input"},
    ],
    "gene_group": [
        {"label": "Name", "name": "group_name", "inputType": "input"},
        {"label": "Symbol", "name": "group_symbol", "inputType": "input"},
        {"label": "Taxon ID", "name": "taxon_id", "inputType": "input"},
    ],
    "signaling_pathway_gene_group": [
        {"label": "Name", "name": "group_name", "inputType": "input"},
        {"label": "Symbol", "name": "group_symbol", "inputType": "input"},
        {"label": "Taxon ID", "name": "taxon_id", "inputType": "input"},
    ],
    "metabolic_pathway_gene_group": [
        {"label": "Name", "name": "group_name", "inputType": "input"},
        {"label": "Symbol", "name": "group_symbol", "inputType": "input"},
        {"label": "Taxon ID", "name": "taxon_id", "inputType": "input"},
    ],
    "rnaseq_library": [
        {"label": "Name", "name": "name", "inputType": "input"},
        {"label": "Cell type ID", "name": "cell_type_id", "inputType": "input"},
        {"label": "Tissue info", "name": "tissue_info", "inputType": "input"},
        {"label": "Taxon ID", "name": "taxon_id", "inputType": "input"},
    ],
    "phenotype_set": [
        {"label": "Phenotype ontology ID", "name": "phenotype_ontology_id", "inputType": "input"},
        {"label": "Taxon ID", "name": "taxon_id", "inputType": "input"},
    ],
    "dmel_disease_model": [
        {"label": "Gene", "name": "gene", "inputType": "input"},
        {"label": "DO term name", "name": "do_term_name", "inputType": "input"},
        {"label": "DO term ID", "name": "do_term_id", "inputType": "input"},
        {"label": "Evidence code", "name": "evidence_code", "inputType": "input"},
        {"label": "Taxon ID", "name": "taxon_id", "inputType": "input"},
    ],
    "gene": [
        {"label": "Name", "name": "gene_name", "inputType": "input"},
        {"label": "Synonym", "name": "synonym", "inputType": "input"},
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
    "protein": [
        {"label": "Name", "name": "protein_name", "inputType": "input"},
        {"label": "Canonical accession", "name": "canonical_accession", "inputType": "input"},
        {"label": "Isoform name", "name": "isoform_name", "inputType": "input"},
        {
            "label": "Is canonical",
            "name": "is_canonical",
            "inputType": "combobox",
            "options": [{"value": "true"}, {"value": "false"}]
        },
        {
            "label": "Is isoform",
            "name": "is_isoform",
            "inputType": "combobox",
            "options": [{"value": "true"}, {"value": "false"}]
        },
    ],
    "transcript": [
        {"label": "Gene name", "name": "gene_name", "inputType": "input"},
        {"label": "Transcript name", "name": "transcript_name", "inputType": "input"},
        {"label": "Transcript ID", "name": "transcript_id", "inputType": "input"},
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
        {"label": "Exon ID", "name": "exon_id", "inputType": "input"},
        {"label": "Exon number", "name": "exon_number", "inputType": "input"},
        *location_inputs
    ],
    "snp": [
        {"label": "Ref", "name": "ref", "inputType": "input"},
        {"label": "Alt", "name": "alt", "inputType": "input"},
        {"label": "Caf_ref", "name": "caf_ref", "inputType": "input"},
        {"label": "Caf_alt", "name": "caf_alt", "inputType": "input"},
        {"label": "Raw CADD score", "name": "raw_cadd_score", "inputType": "input", "type": "number"},
        {"label": "Phred score", "name": "phred_score", "inputType": "input", "type": "number"},
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
        {"label": "Taxon ID", "name": "taxon_id", "inputType": "input"},
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
ES_URL = os.getenv('ES_URL')
ES_API_KEY = os.getenv('ES_API_KEY')

CELL_STRUCTURE = {
    "name": "Cell",
    "components": {
            "go_0005643": "Nuclear pore",
            "go_0031965": "Nuclear membrane",
            "go_0005730": "Nucleolus",
            "go_0005654": "Nucleoplasm",
            "go_0000790": "Nuclear chromatin",
            "go_0048238": "Smooth endoplasmic reticulum lumen",
            "go_0030868": "Smooth endoplasmic reticulum membrane",
            "go_0005840": "Rough endoplasmic reticulum ribosome",
            "go_0030867": "Rough endoplasmic reticulum membrane",
            "go_0048237": "Rough endoplasmic reticulum lumen",
            "go_0005798": "Golgi-associated vesicle",
            "go_0000139": "Golgi membrane",
            "go_0005796": "Golgi lumen",
            "go_0005759": "Mitochondrial matrix",
            "go_0005743": "Mitochondrial inner membrane",
            "go_0005758": "Mitochondrial intermembrane space",
            "go_0005741": "Mitochondrial outer membrane",
            "go_0030061": "Mitochondrial crista",
            "go_0015934": "Large ribosomal subunit",
            "go_0015935": "Small ribosomal subunit"
    }
}

ROLES = ['viewer', 'editor', 'owner']

QUERY_MAX_NODES = 200_000   # hard cap on nodes returned per query
BATCH_MAX_TYPE_SIZE = 500_000   # node types with more total nodes than this → per-node only
BATCH_NODE_THRESHOLD = 50       # result sets with ≥ this many nodes use batch (if type is small)
TASK_STALE_SECS = int(os.environ.get("TASK_STALE_SECS", "2400"))  # tasks older than this are dropped
MAX_BINDING_VALS = int(os.environ.get("MAX_BINDING_VALS", "1000"))  # B4: cap per-variable binding list size
MAX_COMBOS = int(os.environ.get("MAX_COMBOS", "50000"))             # B4: cap Cartesian product size

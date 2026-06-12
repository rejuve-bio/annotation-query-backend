import os
from dotenv import load_dotenv
from app.services.llm_models import OpenAIModel, GeminiModel
from app.services.graph_handler import Graph_Summarizer
import logging

logger = logging.getLogger(__name__)

load_dotenv()

class LLMHandler:
    def __init__(self):
        model_type = os.getenv('LLM_MODEL')
        
        # 1. NODE MAPPINGS (Based on your "Named Things" schema)
        # We look for these properties in order. If found, we use them as the name.
        self.NODE_NAME_PRIORITIES = {
            # Coding Elements
            'gene': ['gene_name', 'symbol', 'name', 'ensembl_id'],
            'protein': ['protein_name', 'uniprot_id', 'accessions', 'name'],
            'transcript': ['transcript_name', 'transcript_id', 'ensembl_id', 'name'],
            'exon': ['exon_id', 'exon_number'], 

            # Ontology Terms
            'go': ['term_name', 'subontology', 'id', 'name'], 
            'pathway': ['pathway_name', 'name', 'id'],
            'uberon': ['term_name', 'name', 'id'],
            'clo': ['term_name', 'name', 'id'],
            'cl': ['term_name', 'name', 'id'],
            'efo': ['term_name', 'name', 'id'],
            'bto': ['term_name', 'name', 'id'],
            'motif': ['tf_name', 'name', 'id'], # Schema says 'tf_name' is the key

            # Genomic Variants
            'snp': ['rsid', 'variant_id', 'id'],
            'structural_variant': ['variant_accession', 'variant_type', 'id'],
            'sequence_variant': ['rsid', 'id'],

            # Non-Coding / Regulatory
            'enhancer': ['enhancer_id', 'data_source', 'id'],
            'super_enhancer': ['se_id', 'id'],
            'non_coding_rna': ['rna_type', 'id'],
            'regulatory_region': ['biochemical_activity', 'id'],
            
            # Position Entities & Structures
            # Prioritizing 'chr' here as requested
            'position_entity': ['chr', 'start', 'end', 'id'], 
            'chromosome_chain': ['chain_id', 'chr', 'id'],
            'tad': ['id', 'chr'], 
        }
        # 2. VERB MAPPINGS (Based on your "Associations" schema)
        # We prioritize 'output_label' from your schema if it's good English.
        self.RELATION_VERBS = {
            # --- EXPRESSION ---
            'transcribed_to': 'is transcribed to',
            'transcribed_from': 'is transcribed from',
            'translates_to': 'translates to',
            'translation_of': 'is a translation of',
            'coexpressed_with': 'is co-expressed with',
            'interacts_with': 'interacts with (post-translational)',
            'expressed_in': 'is expressed in',

            # --- ANNOTATION ---
            'has_part': 'has part',
            'part_of': 'is part of',
            'subclass_of': 'is a subclass of',
            'cl_capable_of': 'is capable of',
            'cl_part_of': 'is part of',
            'genes_pathways': 'is involved in pathway',
            'parent_pathway_of': 'is a parent pathway of',
            'child_pathway_of': 'is a child pathway of',
            
            # Ontology Specific Subclasses
            'bto_subclass_of': 'is a subclass of',
            'efo_subclass_of': 'is a subclass of',
            'uberon_subclass_of': 'is a subclass of',
            'clo_subclass_of': 'is a subclass of',
            'cl_subclass_of': 'is a subclass of',
            'go_subclass_of': 'is a subclass of',

            # GO Annotations
            'go_gene_product': 'has GO annotation',
            'go_gene': 'belongs to GO term',
            'go_rna': 'belongs to GO term',

            # --- REGULATORY ---
            'enhancer_gene': 'is associated with enhancer',
            'promoter_gene': 'is associated with promoter',
            'super_enhancer_gene': 'is associated with super enhancer',
            'tf_gene': 'regulates',
            'regulatory_region_gene': 'regulates',
            
            # --- VARIANTS & GENETICS ---
            'gtex_variant_gene': 'is an eQTL for',
            'closest_gene': 'is the closest gene to',
            'snp_upstream_gene': 'is upstream of',
            'snp_downstream_gene': 'is downstream of',
            'snp_in_gene': 'is located in',
            'in_ld_with': 'is in linkage disequilibrium with',
            'tfbs_snp': 'occurs in binding site of',
            'gene_tfbs': 'binds to',
            
            # --- CHROMOSOME & STRUCTURE ---
            'lower_resolution': 'is a lower resolution version of',
            'located_on_chain': 'is located on chromosome chain',
            'in_tad_region': 'is located in TAD region',
            'activity_by_contact': 'regulates (ABC model)',
            'chromatin_state': 'has chromatin state in',
            'in_dnase_I_hotspot': 'is in DNase I hotspot in',
            'histone_modification': 'has histone modification in',

            # --- TRANSCRIPTS ---
            'includes': 'includes exon',
            'overlaps_with': 'overlaps with'
        }
        
        # 2. GENERIC FALLBACKS (Second Priority)
        # If specific keys fail, try these on ANY node type.
        self.GENERIC_KEYS = [
            # --- Human Readable Names (Best) ---
            'name',           
            'symbol',         
            'label',          
            'title',          
            'term_name',      
            'gene_name',      
            'protein_name',   
            'transcript_name',
            'pathway_name',   
            'tf_name',        
            
            # --- Scientific Identifiers (Okay) ---
            'rsid',           
            'accession',      
            'uniprot_id',     
            'ensembl_id',     
            'se_id',          
            'enhancer_id',
            'chain_id',       
            
            # --- Location Identifiers (Your Request) ---
            'chr',            # If a node has no name but has 'chr', use it!
            
            # --- Technical IDs (Last Resort) ---
            'id',             
            'identifier',     
            'key',            
            '_id',            
            'node_id'         
        ]

        if model_type == 'openai':
            openai_api_key = os.getenv('OPENAI_API_KEY')
            if not openai_api_key:
                self.model = None
            else:
                self.model = OpenAIModel(openai_api_key)
        elif model_type == 'gemini':
            gemini_api_key = os.getenv('GEMINI_API_KEY')
            if not gemini_api_key:
                self.model = None
            else:
                self.model = GeminiModel(gemini_api_key)
        else:
            raise ValueError("Invalid model type in configuration")

    def generate_title(self, query, request=None, node_map=None):
        try:
            if self.model is None:
                if request is None or node_map is None:
                    return "Untitled"
                else:
                    title = self.generate_title_no_llm(request, node_map)
                    return title
            prompt = f'''From this query generate approperiate title. Only give the title sentence don't add any prefix.
                         Query: {query}'''
            title = self.model.generate(prompt)
            return title
        except Exception as e:
            logger.error("Error generating title: %s", e)
            if request is None or node_map is None:
                return "Untitled"
            else:
                title = self.generate_title_no_llm(request, node_map)
                return title
            
    def _get_node_label(self, node):
        if not node: return "Unknown Entity", True

        n_type = node.get('type', 'entity').replace('_', ' ').title()
        props = node.get('properties', {})

        # Handle list nodes — return a short label with count instead of listing all values
        if isinstance(node.get('ids'), list) and len(node['ids']) > 0:
            count = len(node['ids'])
            return f"{count} {n_type}s", True

        # Handle comma-separated id field (alternative list format)
        raw_id = node.get('id', '')
        if isinstance(raw_id, str) and ',' in raw_id:
            count = len([i for i in raw_id.split(',') if i.strip()])
            return f"{count} {n_type}s", True

        # Handle comma-separated property values (another alternative list format)
        for val in props.values():
            if isinstance(val, str) and ',' in val:
                count = len([i for i in val.split(',') if i.strip()])
                return f"{count} {n_type}s", True

        def clean_val(value, key_name):
            """
            Cleans database values:
            1. Unpacks lists
            2. Removes underscores
            3. Fixes capitalization
            4. Adds context prefixes
            """
            # 1. Handle Lists (Take first item)
            if isinstance(value, list):
                if len(value) > 0:
                    value = value[0]
                else:
                    return None
            
            # 2. Basic String Cleaning
            # 'protein_coding' -> 'Protein Coding'
            val_str = str(value).replace('_', ' ').title()
            
            # 3. Context-Specific Prefixes (Based on your schema)
            # This makes generic values like "Deletion" or "Liver" look scientific.
            
            # Location
            if key_name == 'chr': return f"Chromosome {val_str}"
            if key_name == 'start': return f"Position {val_str}"
            
            # Context / Cell Types
            if key_name == 'biological_context': return f"{val_str} Context"
            if key_name == 'cell': return f"{val_str} Cell Line"
            
            # Types & Classifications
            if key_name == 'variant_type': return f"{val_str} Variant"
            if key_name == 'transcript_type': return f"{val_str} Transcript"
            if key_name == 'rna_type': return f"{val_str} RNA"
            if key_name == 'biochemical_activity': return f"{val_str} Region"
            if key_name == 'evidence_type': return f"{val_str} Evidence"
            
            # Epigenetics
            if key_name == 'state': return f"Chromatin State: {val_str}"
            if key_name == 'modification': return f"Histone Modification: {val_str}"

            return val_str

        # 1. Check Specific Keys
        type_keys = self.NODE_NAME_PRIORITIES.get(node.get('type', ''), [])
        for k in type_keys:
            if props.get(k): 
                clean = clean_val(props[k], k)
                if clean: return clean, False

        # 2. Check Generic Keys
        for k in self.GENERIC_KEYS:
            if props.get(k): 
                clean = clean_val(props[k], k)
                if clean: return clean, False

        # 3. Fallback to Type
        # Capitalize acronyms correctly
        if n_type.lower() in ['snp', 'tad', 'dna', 'rna', 'go', 'gtex']:
            return n_type.upper(), True
            
        return n_type, True

    def generate_title_no_llm(self, req, node_map):
        predicates = req.get('predicates', [])

        if not predicates:
            # List items, adding "Unnamed" if generic
            items = []
            for n in node_map.values():
                text, is_generic = self._get_node_label(n)
                items.append(f"Unnamed {text}" if is_generic else text)
            return "Selection: " + ", ".join(items)

        chains = []
        for p in predicates:
            s_node = node_map.get(p['source'])
            t_node = node_map.get(p['target'])
            if not s_node or not t_node: continue

            # Get Labels AND the "Is Generic" status
            s_text, s_generic = self._get_node_label(s_node)
            t_text, t_generic = self._get_node_label(t_node)
            
            # Get Verb
            raw_rel = p['type']
            verb = self.RELATION_VERBS.get(raw_rel, raw_rel.replace('_', ' '))

            # --- THE SMART SENTENCE BUILDER ---
            
            # Scenario 1: "Pathway child of Pathway" (Both generic, same type)
            if s_generic and t_generic and s_text == t_text:
                fragment = f"a {s_text} {verb} another {t_text}"
            
            # Scenario 2: target label repeats the verb context
            elif t_generic and t_text.lower() in verb.lower():
                fragment = f"{s_text} {verb}"
            
            # Scenario 3: "IGF1 child of Pathway" (Specific -> Generic)
            elif t_generic:
                fragment = f"{s_text} {verb} a {t_text}"
                
            # Scenario 4: "Pathway regulates IGF1" (Generic -> Specific)
            elif s_generic:
                fragment = f"a {s_text} {verb} {t_text}"

            # Scenario 5: "IGF1 regulates P53" (Specific -> Specific)
            else:
                fragment = f"{s_text} {verb} {t_text}"

            chains.append({
                "fragment": fragment,
                "s_text": s_text,
                "t_text": t_text,
                "verb": verb,
                "s_generic": s_generic,
                "t_generic": t_generic,
            })

        # --- STEP 1: Group similar fragments ---
        # Key: (verb, t_text) — fragments that share the same verb and target
        # are grouped and their source labels are merged
        from collections import OrderedDict
        grouped = OrderedDict()
        exact_fragments = []  # track final fragment strings for dedup in step 2

        for c in chains:
            group_key = (c['verb'], c['t_text'])

            if group_key not in grouped:
                grouped[group_key] = {
                    "sources": [c['s_text']],
                    "verb": c['verb'],
                    "t_text": c['t_text'],
                    "t_generic": c['t_generic'],
                    "fragment": c['fragment'],  # fallback if only one source
                }
            else:
                # Only group if source is different — avoid grouping identical fragments
                if c['s_text'] not in grouped[group_key]['sources']:
                    grouped[group_key]['sources'].append(c['s_text'])

        # Build grouped fragment strings
        result_fragments = []
        for key, g in grouped.items():
            sources = g['sources']
            verb = g['verb']
            t_text = g['t_text']
            t_generic = g['t_generic']

            if len(sources) > 1:
                # Merge sources: "15, 7 and 4 Genes transcribe to a Transcript"
                source_str = ', '.join(sources[:-1]) + f" and {sources[-1]}"
                if t_generic:
                    merged = f"{source_str} {verb} a {t_text}"
                else:
                    merged = f"{source_str} {verb} {t_text}"
                result_fragments.append(merged)
            else:
                # Single source — use original fragment
                result_fragments.append(g['fragment'])

        # --- STEP 2: Deduplicate exact repeated fragments ---
        seen = []
        deduped = []
        for f in result_fragments:
            if f not in seen:
                seen.append(f)
                deduped.append(f)

        # Final Polish
        title = ", ".join(deduped)
        return title[0].upper() + title[1:]

    def generate_summary(self, graph, request, user_query=None,graph_id=None, summary=None):
        try:
            if self.model is None:
                return "No summary available"
            summarizer = Graph_Summarizer(self.model)
            summary = summarizer.summary(graph, request, user_query, graph_id, summary)
            return summary
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return "No summary available"

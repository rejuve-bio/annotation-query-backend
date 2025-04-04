import glob
import os
from hyperon import MeTTa, SymbolAtom, ExpressionAtom, GroundedAtom
import logging
from .query_generator_interface import QueryGeneratorInterface
from .metta import Metta_Ground, metta_seralizer
# Set up logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MeTTa_Query_Generator(QueryGeneratorInterface):
    def __init__(self, dataset_path: str):
        self.metta = MeTTa()
        self.initialize_space()
        self.dataset_path = dataset_path
        self.load_dataset(self.dataset_path)
        self.initialize_grounatoms()

    def initialize_space(self):
        self.metta.run("!(bind! &space (new-space))")

    def initialize_grounatoms(self):
        Metta_Ground(self.metta)

    def load_dataset(self, path: str) -> None:
        if not os.path.exists(path):
            raise ValueError(f"Dataset path '{path}' does not exist.")
        paths = glob.glob(os.path.join(path, "**/*.metta"), recursive=True)
        if not paths:
            raise ValueError(f"No .metta files found in dataset path '{path}'.")
        for path in paths:
            logging.info(f"Start loading dataset from '{path}'...")
            try:
                self.metta.run(f'''
                    !(load-ascii &space {path})
                    ''')
            except Exception as e:
                logging.error(f"Error loading dataset from '{path}': {e}")
        logging.info(f"Finished loading {len(paths)} datasets.")

    def generate_id(self):
        import uuid
        return str(uuid.uuid4())[:8]

    def construct_node_representation(self, node, identifier):
        node_type = node['type']
        node_representation = ''
        for key, value in node['properties'].items():
            node_representation += f' ({key} ({node_type + " " + identifier}) {value})'
        return node_representation

    def query_Generator(self, requests ,node_map, limit=None, node_only=False):
        nodes = requests['nodes']
        predicate_map = {}
        
        if "predicates" in requests and len(requests["predicates"]) > 0:
            predicates = requests["predicates"]

            init_pred = predicates[0]

            if 'predicate_id' not in init_pred:
                for idx, pred in enumerate(predicates):
                    pred['predicate_id'] = f'p{idx}'
                for predicate in predicates:
                    predicate_map[predicate['predicate_id']] = predicate
            else:
                for predicate in predicates:
                    predicate_map[predicate['predicate_id']] = predicate
        else:
            predicates = None

        metta_output = '''!(match &space (,'''
        output = ''' ('''
 
        # if there is no predicate
        if not predicates:
            for node in nodes:
                node_type = node["type"]
                node_id = node["node_id"]
                node_identifier = '$' + node["node_id"]
                if node["id"]:
                    essemble_id = node["id"]
                    metta_output += f' ({node_type} {essemble_id})'
                    output += f' ({node_type} {essemble_id})'
                else:
                    if len(node["properties"]) == 0:
                        metta_output += f' ({node_type} ${node_id})'
                    else:
                        metta_output += self.construct_node_representation(node, node_identifier)
                    output += f' ({node_type} {node_identifier})'
            return metta_output

        for predicate in predicates:
            predicate_type = predicate['type'].replace(" ", "_")
            source_id = predicate['source']
            target_id = predicate['target']

            # Handle source node
            source_node = node_map[source_id]
            if not source_node['id']:
                node_identifier = "$" + source_id
                metta_output += self.construct_node_representation(source_node, node_identifier)
                source = f'({source_node["type"]} {node_identifier})'
            else:
                source = f'({str(source_node["type"])} {str(source_node["id"])})'


            # Handle target node
            target_node = node_map[target_id]
            if not target_node['id']:
                target_identifier = "$" + target_id
                metta_output += self.construct_node_representation(target_node, target_identifier)
                target = f'({target_node["type"]} {target_identifier})'
            else:
                target = f'({str(target_node["type"])} {str(target_node["id"])})'

            # Add relationship
            metta_output += f' ({predicate_type} {source} {target})'
            output += f' ({predicate_type} {source} {target})'

        metta_output += f' ){output}))'
        count = self.count_query_generator(predicates, node_map)
        return [metta_output, count[0], count[1]]

    def count_query_generator(self, predicates, node_map):
        metta_output = '''(match &space (,'''
        output = ''' ('''
 
        for predicate in predicates:
            predicate_type = predicate['type'].replace(" ", "_")
            source_id = predicate['source']
            target_id = predicate['target']

            # Handle source node
            source_node = node_map[source_id]
            if not source_node['id']:
                node_identifier = "$" + source_id
                metta_output += self.construct_node_representation(source_node, node_identifier)
                source = f'({source_node["type"]} {node_identifier})'
            else:
                source = f'({str(source_node["type"])} {str(source_node["id"])})'


            # Handle target node
            target_node = node_map[target_id]
            if not target_node['id']:
                target_identifier = "$" + target_id
                metta_output += self.construct_node_representation(target_node, target_identifier)
                target = f'({target_node["type"]} {target_identifier})'
            else:
                target = f'({str(target_node["type"])} {str(target_node["id"])})'

            # Add relationship
            metta_output += f' ({predicate_type} {source} {target})'
            output += f' ((Edge {predicate_type}) (Node {source}) (Node {target}))'
        metta_output += f' ){output}))'
        count_query = f'''(total_count (collapse {metta_output}))'''
        count_query = f'''!{count_query}'''
        lable_count_query = f'''!(label_count (collapse {metta_output}))'''
        return [count_query, lable_count_query]

        
    def run_query(self, query_code, stop_event=True):
        return self.metta.run(query_code)

    def parse_and_serialize(self, input, schema, graph_components, result_type):
        if result_type == 'graph':
            result = self.prepare_query_input(input, schema)
            result = self.parse_and_serialize_properties(result[0], graph_components, result_type)
            return result
        else:
            (_,_,_,_, meta_data) = self.process_result(input, graph_components, result_type)
            return {
                "node_count": meta_data.get('node_count', 0),
                "edge_count": meta_data.get('edge_count', 0),
                "node_count_by_label": meta_data.get('node_count_by_label', []),
                "edge_count_by_label": meta_data.get('edge_count_by_label', []),
            }
        
    def parse_and_serialize_properties(self, input, graph_components, result_type):
        (nodes, edges, _, _, meta_data) = self.process_result(input, graph_components, result_type)
        return {"nodes": nodes[0], "edges": edges[0],
                "node_count": meta_data.get('node_count', 0),
                "edge_count": meta_data.get('edge_count', 0),
                "node_count_by_label": meta_data.get('node_count_by_label', []),
                "edge_count_by_label": meta_data.get('edge_count_by_label', [])
        }

    def get_node_properties(self, results, schema):
        metta = ('''!(match &space (,''')
        output = (''' (,''') 
        nodes = set()
        for result in results:
            source = result['source']
            source_node_type = result['source'].split(' ')[0]

            if source not in nodes:
                for property, _ in schema[source_node_type]['properties'].items():
                    id = self.generate_id()
                    metta += " " + f'({property} ({source}) ${id})'
                    output += " " + f'(node {property} ({source}) ${id})'
                nodes.add(source)

            if "target" in result and "predicate" in result:
                target = result['target']
                target_node_type = result['target'].split(' ')[0]
                if target not in nodes:
                    for property, _ in schema[target_node_type]['properties'].items():
                        id = self.generate_id()
                        metta += " " + f'({property} ({target}) ${id})'
                        output += " " + f'(node {property} ({target}) ${id})'
                    nodes.add(target)

                predicate = result['predicate']
                predicate_schema = f'{source_node_type}_{predicate}_{target_node_type}'
                for property, _ in schema[predicate_schema]['properties'].items():
                    random = self.generate_id()
                    metta += " " + f'({property} ({predicate} ({source}) ({target})) ${random})'
                    output +=  " " + f'(edge {property} ({predicate} ({source}) ({target})) ${random})' 

        metta+= f" ) {output}))"
        return metta

    def convert_to_dict(self, results, schema=None):
        result = self.prepare_query_input(results, schema)
        (_, node_dict, edge_dict) = self.process_result(result[0], True)
        return (node_dict, edge_dict)

    # Won't work because of we don't try to parse node count and count by labels
    def process_result(self, results, graph_components, result_type):
        match_result = results
        node_and_edge_count = {}
        count_by_label = {}
        nodes = []
        edges = []
        node_to_dict = {}
        edge_to_dict = {}
        meta_data = {}

        if len(results) > 0:
            node_and_edge_count = results[0]

        if len(results) > 1:
            count_by_label = results[1]

        if result_type == 'graph':
            nodes, edges, node_to_dict, edge_to_dict = self.process_result_graph(
                match_result, graph_components)

        if result_type == 'count':
            meta_data = self.process_result_count(
                node_and_edge_count, count_by_label, graph_components)

        return (nodes, edges, node_to_dict, edge_to_dict, meta_data)
        
    def process_result_graph(self, results, graph_components):
        nodes = {}
        relationships_dict = {}
        node_result = []
        edge_result = []
        node_to_dict = {}
        edge_to_dict = {}
        node_type = set()
        edge_type = set()
        tuples = metta_seralizer(results)
        named_types = ['gene_name', 'transcript_name', 'protein_name',
                       'pathway_name', 'term_name']
        
        for match in tuples:
            graph_attribute = match[0]
            match = match[1:]

            if graph_attribute == "node":
                if len(match) > 4:
                    predicate = match[0]
                    src_type = match[1]
                    src_value = match[2]
                    tgt = list(match[3:])
                else:
                    predicate, src_type, src_value, tgt = match
                if (src_type, src_value) not in nodes:
                    nodes[(src_type, src_value)] = {
                        "id": f"{src_type} {src_value}",
                        "type": src_type,
                    }
                
                if graph_components['properties']:
                     nodes[(src_type, src_value)][predicate] = tgt
                else:
                    if predicate in named_types:
                        nodes[(src_type, src_value)]['name'] = tgt

                if 'synonyms' in nodes[(src_type, src_value)]:
                    del nodes[(src_type, src_value)]['synonyms']
                if src_type not in node_type:
                    node_type.add(src_type)
                    node_to_dict[src_type] = []
                node_data = {}
                node_data["data"] = nodes[(src_type, src_value)]
                node_to_dict[src_type].append(node_data)
            elif graph_attribute == "edge":
                property_name, predicate, source, source_id, target, target_id = match[:6]
                value = ' '.join(match[6:])

                key = (predicate, source, source_id, target, target_id)
                if key not in relationships_dict:
                    relationships_dict[key] = {
                        "edge_id": f'{source}_{predicate}_{target}',
                        "label": predicate,
                        "source": f"{source} {source_id}",
                        "target": f"{target} {target_id}",
                    }
                
                if property_name == "source":
                    relationships_dict[key]["source_data"] = value
                else:
                    relationships_dict[key][property_name] = value
                
                if predicate not in edge_type:
                    edge_type.add(predicate)
                    edge_to_dict[predicate] = []
                edge_data = {}
                edge_data['data'] = relationships_dict[key]
                edge_to_dict[predicate].append(edge_data)
        node_list = [{"data": node} for node in nodes.values()]
        relationship_list = [{"data": relationship} for relationship in relationships_dict.values()]

        node_result.append(node_list)
        edge_result.append(relationship_list)
        return (node_result, edge_result, node_to_dict, edge_to_dict)
    
    def process_result_count(self, node_and_edge_count, count_by_label, graph_components):
        if len(node_and_edge_count) != 0:
            node_and_edge_count = node_and_edge_count[0].get_object().value
        node_count_by_label = []
        edge_count_by_label = []
        
        if len(count_by_label) != 0:
            count_by_label = count_by_label[0].get_object().value
            node_label_count = count_by_label['node_label_count']
            edge_label_count = count_by_label['edge_label_count']

            # update the way node count by label and edge count by label are represented
            for key, value in node_label_count.items():
                node_count_by_label.append(
                    {'label': key, 'count': value['count']}) 
            for key, value in edge_label_count.items():
                edge_count_by_label.append(
                    {'label': key, 'count': value['count']})
            
        meta_data = {
            "node_count": node_and_edge_count.get('total_nodes', 0),
            "edge_count": node_and_edge_count.get('total_edges', 0),
            "node_count_by_label": node_count_by_label if node_count_by_label else [],
            "edge_count_by_label": edge_count_by_label if edge_count_by_label else []
        }
        
        return meta_data

    def prepare_query_input(self, input, schema):
        result = []

        tuples = metta_seralizer(input[0])
        for tuple in tuples:
            if len(tuple) == 2:
                src_type, src_id = tuple
                result.append({
                    "source": f"{src_type} {src_id}"
                })
            else:
                predicate, src_type, src_id, tgt_type, tgt_id = tuple
                result.append({
                "predicate": predicate,
                "source": f"{src_type} {src_id}",
                "target": f"{tgt_type} {tgt_id}"
                })
        query = self.get_node_properties(result, schema)
        result = self.run_query(query)
        return result

    def parse_id(self, request):
        nodes = request["nodes"]
        named_types = {"gene": "gene_name", "transcript": "transcript_name"}
        prefixes = ["ENSG", "ENST"]

        for node in nodes:
            is_named_type = node['type'] in named_types
            is_name_as_id = all(not node["id"].startswith(prefix) for prefix in prefixes)
            no_id = node["id"] != ''
            if is_named_type and is_name_as_id and no_id:
                node_type = named_types[node['type']]
                node['properties'][node_type] = node["id"]
                node['id'] = ''
        return request

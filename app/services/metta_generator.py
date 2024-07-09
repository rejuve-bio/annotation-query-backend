import glob
import os
from hyperon import MeTTa
import re
import json
import uuid
from .query_generator_interface import QueryGeneratorInterface
# from app.services.util import generate_id

class MeTTa_Query_Generator(QueryGeneratorInterface):
    def __init__(self, dataset_path: str):
        self.metta = MeTTa()
        self.initialize_space()
        self.dataset_path = dataset_path
        self.load_dataset(self.dataset_path)

    def initialize_space(self):
        self.metta.run("!(bind! &space (new-space))")

    def load_dataset(self, path: str) -> None:
        if not os.path.exists(path):
            raise ValueError(f"Dataset path '{path}' does not exist.")
        paths = glob.glob(os.path.join(path, "**/*.metta"), recursive=True)
        if not paths:
            raise ValueError(f"No .metta files found in dataset path '{path}'.")
        for path in paths:
            print(f"Start loading dataset from '{path}'...")
            try:
                self.metta.run(f'''
                    !(load-ascii &space {path})
                    ''')
            except Exception as e:
                print(f"Error loading dataset from '{path}': {e}")
        print(f"Finished loading {len(paths)} datasets.")

    def generate_id(self):
        import uuid
        return str(uuid.uuid4())[:8]

    def construct_node_representation(self, node, identifier):
        node_type = node['type']
        node_representation = ''
        for key, value in node['properties'].items():
            node_representation += f' ({key} ({node_type + " " + identifier}) {value})'
        return node_representation

    def query_Generator(self, data):
        nodes = data['nodes']
        predicates = data['predicates']

        # Create a mapping from node_id to node
        node_map = {node['node_id']: node for node in nodes}
        print("node_map",node_map)

        metta_output = '''!(match &space (,'''
        output = ''' (,'''

        for predicate in predicates:
            predicate_type = predicate['type'].replace(" ", "_")
            source_id = predicate['source']
            print("source_id", source_id)
            target_id = predicate['target']
            print("target_id", target_id)

            # Handle source node
            source_node = node_map[source_id]
            print("source_node", source_node)
            if not source_node['id']:
                node_identifier = "$" + source_id
                metta_output += self.construct_node_representation(source_node, node_identifier)
                source = f'({source_node["type"]} {node_identifier})'
            else:
                source = f'({str(source_node["id"])})'

            # Handle target node
            target_node = node_map[target_id]
            if not target_node['id']:
                target_identifier = "$" + target_id
                metta_output += self.construct_node_representation(target_node, target_identifier)
                target = f'({target_node["type"]} {target_identifier})'
            else:
                target = f'({str(target_node["id"])})'

            # Add relationship
            metta_output += f' ({predicate_type} {source} {target})'
            output += f' ({predicate_type} {source} {target})'

        metta_output += f' ){output}))'
        print("metta_output:", metta_output)
        return metta_output


    def run_query(self, query_code):
        return self.metta.run(query_code)
    
    def parse_and_serialize(self, input_string):
        cleaned_string = re.sub(r"[,\[\]]", "", input_string)
        tuples = re.findall(r"(\w+)\s+\((\w+)\s+(\w+)\)\s+\((\w+)\s+(\w+)\)", cleaned_string)
        result = []
        for tuple in tuples:
            predicate, src_type, src_id, tgt_type, tgt_id = tuple
            result.append({
                "id": str(uuid.uuid4()),
                "predicate": predicate,
                "source": f"{src_type} {src_id}",
                "target": f"{tgt_type} {tgt_id}"
            })
        return json.dumps(result, indent=2)
    # def parse_metta(self, input_string):
    #     parsed_metta = self.metta.parse_all(input_string)
    #     print("parsed_metta",parsed_metta)

    def parse_and_serialize_properties(self, input_string):
        pattern = r"\(\((\w+) \((\w+) (\w+)\) ([^)]+)\)\)"
        tuples = re.findall(pattern, input_string)
        nodes = {}
        for match in tuples:
            predicate, src_type, src_value, tgt = match
            if (src_type, src_value) not in nodes:
                nodes[(src_type, src_value)] = {
                    "node": f"{src_type} {src_value}",
                    "type": src_type,
                    "properties": {}
                }
            nodes[(src_type, src_value)]["properties"][predicate] = tgt
        node_list = list(nodes.values())
        return json.dumps(node_list, indent=2)

    def get_node_properties(self, node, schema):
        property_list = []
        node_type = node[0].split()[0]
        if node_type in schema:
            pred_schema = schema[node_type]
            if pred_schema['represented_as'] == 'node':
                property_dic = pred_schema.get('properties', {})
                property_key_list = list(property_dic.keys())
                for key in property_key_list:
                    queryed_result = self.metta.run(f'''!(match &space
                        (,  
                            ({key} ({node[0]}) $value)
                            )
                        ( ({key} ({node[0]}) $value) ))''')
                    property_list.append(queryed_result)
                    # print("queryed_result", queryed_result)
        # print("property_list", property_list)
        return property_list

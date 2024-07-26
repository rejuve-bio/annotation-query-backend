import glob
import os
from hyperon import MeTTa, SymbolAtom, ExpressionAtom, GroundedAtom
import re
import json
import uuid
from .query_generator_interface import QueryGeneratorInterface

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

    def query_Generator(self, data,node_map):

        if node_map is None:
            raise Exception('error')

        nodes = data['nodes']

        metta_output = '''!(match &space (,'''
        output = ''' (,'''
 
        node_without_predicate = None
        predicates = None
        if "predicates" not in data:
            node_without_predicate = nodes
        else:
             predicates = data['predicates']
             node_with_predicate = set()
             for predicate in predicates:
                node_with_predicate.add(predicate["source"])
                node_with_predicate.add(predicate["target"])
             node_without_predicate = [node for node in nodes if node["node_id"] not in node_with_predicate]

        # if there is no predicate
        if "predicates" not in data or (node_without_predicate is not None and len(node_without_predicate) != 0):
            for node in node_without_predicate:
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
        
        if predicates is None:
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
        # print("metta_output:", metta_output)
        return metta_output


    def run_query(self, query_code):
        return self.metta.run(query_code)

    def parse_and_serialize(self, input, schema):
        result = []

        tuples = self.metta_seralizer(input[0])
        for tuple in tuples:
            if len(tuple) == 2:
                src_type, src_id = tuple
                result.append({
                    "id": str(uuid.uuid4()),
                    "source": f"{src_type} {src_id}"
                })
            else:
                predicate, src_type, src_id, tgt_type, tgt_id = tuple
                result.append({
                "id": str(uuid.uuid4()),
                "predicate": predicate,
                "source": f"{src_type} {src_id}",
                "target": f"{tgt_type} {tgt_id}"
                })
        
        query = self.get_node_properties(result, schema)
        result = self.run_query(query)
        result = self.parse_and_serialize_properties(result[0])

        return result
        
    def parse_and_serialize_properties(self, input):
        nodes = {}
        relationships_dict = {}
        result = []
        tuples = self.metta_seralizer(input)
        # print("result", tuples)

        for match in tuples:
            graph_attribute = match[0]
            match = match[1:]

            if graph_attribute == "node":
                if len(match) > 4:
                    predicate = match[0]
                    src_type = match[1]
                    src_value = match[2]
                    tgt = ' '.join(match[3:])
                else:
                    predicate, src_type, src_value, tgt = match
                if (src_type, src_value) not in nodes:
                    nodes[(src_type, src_value)] = {
                        "id": f"{src_type} {src_value}",
                        "type": src_type,
                    }
                nodes[(src_type, src_value)][predicate] = tgt
            elif graph_attribute == "edge":
                property_name, predicate, source, source_id, target, target_id = match[:6]
                value = ' '.join(match[6:])

                key = (predicate, source, source_id, target, target_id)
                if key not in relationships_dict:
                    relationships_dict[key] = {
                        "label": predicate,
                        "source_node": f"{source} {source_id}",
                        "target_node": f"{target} {target_id}",
                    }
                relationships_dict[key][property_name] = value

        node_list = [{"data": node} for node in nodes.values()]
        relationship_list = [{"data": relationship} for relationship in relationships_dict.values()]

        result.append(node_list)
        result.append(relationship_list)
        return result

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
                predicate_schema = ' '.join(predicate.split('_'))
                for property, _ in schema[predicate_schema]['properties'].items():
                    random = self.generate_id()
                    metta += " " + f'({property} ({predicate} ({source}) ({target})) ${random})'
                    output +=  " " + f'(edge {property} ({predicate} ({source}) ({target})) ${random})' 

        metta+= f" ) {output}))"

        return metta

    def recurssive_seralize(self, metta_expression, result):
        for node in metta_expression:
            if isinstance(node, SymbolAtom):
             result.append(node.get_name())
            elif isinstance(node, GroundedAtom):
                result.append(str(node))
            else:
                self.recurssive_seralize(node.get_children(), result)
        return result

    def metta_seralizer(self, metta_result):
        result = []

        for node in metta_result:
            node = node.get_children()
            for metta_symbol in node:
                if isinstance(metta_symbol, SymbolAtom) and  metta_symbol.get_name() == ",":
                    continue
                if isinstance(metta_symbol, ExpressionAtom):
                    res = self.recurssive_seralize(metta_symbol.get_children(), [])
                    result.append(tuple(res))
        return result

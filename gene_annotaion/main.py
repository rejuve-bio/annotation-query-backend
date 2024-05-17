from flask import Flask, request, jsonify
from biocypher import BioCypher
from metta_generator import generate_metta
from hyperon import MeTTa
import logging
import json
import glob
import os
import re
import uuid
# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
metta = MeTTa()
metta.run("!(bind! &space (new-space))")  # Initialize a new space at application start

bcy = BioCypher(schema_config_path='./config/schema_config.yaml', biocypher_config_path='./config/biocypher_config.yaml')
schema = bcy._get_ontology_mapping()._extend_schema()
parent_nodes = ["position entity", "coding element", "non coding element", "genomic variant", "epigenomic feature", "3d genome structure", "ontology term", "chromosome chain"]
parent_edges = ["expression", "annotation", "regulatory association"]

def load_dataset(path: str) -> None:
    if not os.path.exists(path):
        raise ValueError(f"Dataset path '{path}' does not exist.")

    paths = glob.glob(os.path.join(path, "**/*.metta"), recursive=True)
    if not paths:
        raise ValueError(f"No .metta files found in dataset path '{path}'.")

    for path in paths:
        print(f"Start loading dataset from '{path}'...")

        try:
            metta.run(f'''
                !(load-ascii &space {path})
                ''')
        except Exception as e:
            print(f"Error loading dataset from '{path}': {e}")

    print(f"Finished loading {len(paths)} datasets.")


load_dataset("./Data")


def parse_and_serialize(input_string):
    # Remove the outermost brackets and any unwanted characters
    cleaned_string = re.sub(r"[,\[\]]", "", input_string)

    # Find all tuples using regex
    tuples = re.findall(r"(\w+)\s+\((\w+)\s+(\w+)\)\s+\((\w+)\s+(\w+)\)", cleaned_string)
    # logging.debug(f"Generated tuples Code: {tuples}")
    # Convert tuples to JSON format
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

def parse_and_serialize_properties(input_string):
    # Remove the outermost brackets and any unwanted characters
    cleaned_string = re.sub(r"[,\[\]]", "", input_string)
    pattern = r"\(\((\w+) \((\w+) (\w+)\) (\w+)\)\)"
    tuples = re.findall(pattern, input_string)
    # Initialize a dictionary to store nodes and their properties
    nodes = {}
    # Iterate over the matches and format the output
    for match in tuples:
        predicate, src_type, src_value, tgt = match
        if (src_type, src_value) not in nodes:
            nodes[(src_type, src_value)] = {
                "node": f"{src_type} {src_value}",
                "type": src_type,
                "properties": {}
            }
        nodes[(src_type, src_value)]["properties"][predicate] = tgt
    # Convert the dictionary of nodes to a list of dictionaries
    node_list = list(nodes.values())
    node_string = json.dumps(node_list, indent=2)
    return node_string

def get_nodes():
    nodes = []
    for key, value in schema.items():
        if value['represented_as'] == 'node':
            if key in parent_nodes:
                continue
            nodes.append({
                'type': key,
                'label': value['input_label'],
                'properties': value.get('properties', {})
            })
    
    return nodes

def get_edges():
    edges = []
    for key, value in schema.items():
        if value['represented_as'] == 'edge':
            if key in parent_edges:
                continue
            label = value.get('output_lable', value['input_label'])
            edge = {
                'type': key,
                'label': label,
                'source': value.get('source', ''),
                'target': value.get('target', '')
            }
            edges.append(edge)
    
    return edges


def get_relations_for_node(node):
    relations = []
    node_label = node.replace('_', ' ')
    for key, value in schema.items():
        if value['represented_as'] == 'edge':
            if 'source' in value and 'target' in value:
                if value['source'] == node_label or value['target'] == node_label:
                    label = value.get('output_lable', value['input_label'])
                    relation = {
                        'type': key,
                        'label': label,
                        'source': value.get('source', ''),
                        'target': value.get('target', '')
                    }
                    relations.append(relation)
    
    return relations

def get_node_properties(node):
    property_list= []
    # node_info = node[0]
    node_type = node[0].split()[0]
    if node_type in schema: 
        pred_schema = schema[node_type]
        if pred_schema['represented_as'] == 'node':
            property_dic= pred_schema.get('properties', {})
            property_key_list = list(property_dic.keys())
            for key in property_key_list:
                queryed_result = metta.run(f'''!(match &space
                    (,  
                        ({key} ({node[0]}) $b)
                        )
                    ( ({key} ({node[0]}) $b) ))''')
                property_list.append(queryed_result)
    return property_list

@app.route('/nodes', methods=['GET'])
def get_nodes_endpoint():
    return jsonify(get_nodes())

@app.route('/edges', methods=['GET'])
def get_edges_endpoint():
    return jsonify(get_edges())

@app.route('/relations/<node_label>', methods=['GET'])
def get_relations_for_node_endpoint(node_label):
    return jsonify(get_relations_for_node(node_label))

@app.route('/query', methods=['POST'])
def process_query():
    data = request.get_json()
    if not data or 'requests' not in data:
        return jsonify({"error": "Missing requests data"}), 400
    try:
        requests = data['requests']
        query_code = generate_metta(requests, schema)
        result = metta.run(query_code)
        parsed_result = parse_and_serialize(str(result))
        parsed_result_list = json.loads(parsed_result)
        unique_nodes = set()
        for item in parsed_result_list:
            source, target = item["source"], item["target"]
            unique_nodes.add(source) 
            unique_nodes.add(target)
        properties =[]
        for node in unique_nodes:
             properties.append(get_node_properties([node]))
        parsed_properties=parse_and_serialize_properties(str(properties))
        # Return the serialized result
        return jsonify({"Generated query": query_code,"Result": json.loads(parsed_result), "Properties": json.loads(parsed_properties)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)


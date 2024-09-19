from flask import Flask, request, jsonify, Response
import logging
import json
import yaml
import os
from app import app, databases, schema_manager
from app.lib import validate_request
from flask_cors import CORS

CORS(app)

# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'config.yaml')
    try:
        with open(config_path, 'r') as file:
            config = yaml.safe_load(file)
        logging.info("Configuration loaded successfully.")
        return config
    except FileNotFoundError:
        logging.error(f"Config file not found at: {config_path}")
        raise
    except yaml.YAMLError as e:
        logging.error(f"Error parsing YAML file: {e}")
        raise

config = load_config()

@app.route('/nodes', methods=['GET'])
def get_nodes_endpoint():
    nodes = json.dumps(schema_manager.get_nodes(), indent=4)
    return Response(nodes, mimetype='application/json')

@app.route('/edges', methods=['GET'])
def get_edges_endpoint():
    edges = json.dumps(schema_manager.get_edges(), indent=4)
    return Response(edges, mimetype='application/json')

@app.route('/relations/<node_label>', methods=['GET'])
def get_relations_for_node_endpoint(node_label):
    relations = json.dumps(schema_manager.get_relations_for_node(node_label), indent=4)
    return Response(relations, mimetype='application/json')

@app.route('/query', methods=['POST'])
def process_query():
    data = request.get_json()
    if not data or 'requests' not in data:
        return jsonify({"error": "Missing requests data"}), 400

    try:
        requests = data['requests']
        
        # Validate the request data before processing
        node_map = validate_request(requests, schema_manager.schema)
        if node_map is None:
            return jsonify({"error": "Invalid node_map returned by validate_request"}), 400
        
        database_type = config['database']['type']
        db_instance = databases[database_type]
        
        # Generate the query code
        query_code = db_instance.query_Generator(requests, node_map)
        
        # Run the query and parse the results
        result = db_instance.run_query(query_code)
        parsed_result = db_instance.parse_and_serialize(result, schema_manager.schema)
        
        response_data = {
            "nodes": parsed_result[0],
            "edges": parsed_result[1]
        }
        
        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error processing query: {e}")
        return jsonify({"error": str(e)}), 500



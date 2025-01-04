from flask import copy_current_request_context, request, jsonify, Response
import logging
import json
import yaml
import os
import threading
from app import app, databases, schema_manager
from app.lib import validate_request
from flask_cors import CORS
from app.lib import limit_graph
from app.lib.email import init_mail, send_email
from dotenv import load_dotenv
from distutils.util import strtobool
import math

# Load environmental variables
load_dotenv()

# Flask-Mail configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER') 
app.config['MAIL_PORT'] = os.getenv('MAIL_PORT')
app.config['MAIL_USE_TLS'] = bool(strtobool(os.getenv('MAIL_USE_TLS')))
app.config['MAIL_USE_SSL'] = bool(strtobool(os.getenv('MAIL_USE_SSL')))
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

# Initialize Flask-Mail
init_mail(app)

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
    
    limit = request.args.get('limit')
    take = request.args.get('take', default=10)
    page = request.args.get('page', default=1)

    properties = request.args.get('properties')
    
    if properties:
        properties = bool(strtobool(properties))
    else:
        properties = False

    if limit:
        try:
            limit = int(limit)
        except ValueError:
            return jsonify({"error": "Invalid limit value. It should be an integer."}), 400
    else:
        limit = None
    try:
        requests = data['requests']
        # Validate the request data before processing
        node_map = validate_request(requests, schema_manager.schema)
        if node_map is None:
            return jsonify({"error": "Invalid node_map returned by validate_request"}), 400

        database_type = config['database']['type']
        db_instance = databases[database_type]

        #convert id to appropriate format
        requests = db_instance.parse_id(requests)

        # Generate the query code
        query_code = db_instance.query_Generator(requests, node_map,take, page)

        # Run the query and parse the results
        result = db_instance.run_query(query_code)

        response_data = db_instance.parse_and_serialize(result, schema_manager.schema, properties)

        total_nodes = response_data["meta_data"]["node_count"]
        response_data["meta_data"]["page"] = int(page)
        response_data["meta_data"]["items_per_page"] = int(take)
        response_data["meta_data"]["max_page"] = math.ceil(total_nodes / int(take))
        
        #if limit:
            #response_data = limit_graph(response_data, limit)

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error processing query: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/email-query', methods=['POST'])
def process_email_query():
    data = request.get_json()
    if not data or 'requests' not in data:
        return jsonify({"error": "Missing requests data"}), 400
    if 'email' not in data:
        return jsonify({"error": "Email missing"}), 400
    @copy_current_request_context
    def send_full_data():
        try:
            requests = data['requests']
            email = data['email']
        
            # Validate the request data before processing
            node_map = validate_request(requests, schema_manager.schema)
            if node_map is None:
                return jsonify({"error": "Invalid node_map returned by validate_request"}), 400
        
            database_type = config['database']['type']
            db_instance = databases[database_type]
            
            requests = db_instance.parse_id(requests)

            # Generate the query code
            query_code = db_instance.query_Generator(requests, node_map)
        
            # Run the query and parse the results
            result = db_instance.run_query(query_code)
            parsed_result = db_instance.convert_to_dict(result, schema_manager.schema)
            
            subject = 'Full Data'
            body = f'Hello {email} here is the full data you requested'

            send_email(subject, [email], body, parsed_result)
        except Exception as e:
            logging.error(f"Error processing query: {e}")

    sender = threading.Thread(name='main_sender', target=send_full_data)
    sender.start() 
    return jsonify({'message': 'Email sent successfully'}), 200

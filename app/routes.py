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

# Load environmental variables
load_dotenv()

# Flask-Mail configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER') 
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = False
app.config['mAIL_USE_SSL'] = False
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
 
        response_data = limit_graph(response_data, config['graph']['limit'])

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
        return jsonify({"error": "Email missing"})
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

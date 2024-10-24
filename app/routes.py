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
from app.lib.auth import token_required
from app.lib.email import init_mail, send_email
from dotenv import load_dotenv
from distutils.util import strtobool
from app.services.llm_handler import LLMHandler
from app.persistence.storage_service import StorageService

# Load environmental variables
load_dotenv()

# set mongo loggin
logging.getLogger('pymongo').setLevel(logging.CRITICAL)

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
@token_required
def get_nodes_endpoint(current_user_id):
    nodes = json.dumps(schema_manager.get_nodes(), indent=4)
    return Response(nodes, mimetype='application/json')

@app.route('/edges', methods=['GET'])
@token_required
def get_edges_endpoint(current_user_id):
    edges = json.dumps(schema_manager.get_edges(), indent=4)
    return Response(edges, mimetype='application/json')

@app.route('/relations/<node_label>', methods=['GET'])
@token_required
def get_relations_for_node_endpoint(current_user_id, node_label):
    relations = json.dumps(schema_manager.get_relations_for_node(node_label), indent=4)
    return Response(relations, mimetype='application/json')

@app.route('/query', methods=['POST'])
@token_required
def process_query(current_user_id):
    data = request.get_json()
    if not data or 'requests' not in data:
        return jsonify({"error": "Missing requests data"}), 400
    
    limit = request.args.get('limit')
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
        query_code = db_instance.query_Generator(requests, node_map)
        
        # Run the query and parse the results
        result = db_instance.run_query(query_code)
        parsed_result = db_instance.parse_and_serialize(result, schema_manager.schema, properties)
        
        response_data = {
            "nodes": parsed_result[0],
            "edges": parsed_result[1]
        }

        llm = LLMHandler()
        title = llm.generate_title(query_code)
        summary = llm.generate_summary(response_data)
        
        storage_service = StorageService()

        if isinstance(query_code, list):
            query_code = query_code[0]

        storage_service.save(str(current_user_id), query_code, title, summary)

        if limit:
            response_data = limit_graph(response_data, limit)

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error processing query: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/email-query', methods=['POST'])
@token_required
def process_email_query(current_user_id):
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

@app.route('/history', methods=['GET'])
@token_required
def process_user_history(current_user_id):
    page_number = request.args.get('page_number')
    if page_number is not None:
        page_number = int(page_number)
    else:
        page_number = 1
    return_value = []
    storage_service = StorageService()
    cursor = storage_service.get_all(str(current_user_id), page_number)

    if cursor is None:
        return jsonify('No value Found'), 200

    for document in cursor:
        return_value.append({
            'id': str(document['_id']),
            'title': document['title'],
            'summary': document['summary']
        })
    return Response(json.dumps(return_value, indent=4), mimetype='application/json')

@app.route('/history/<id>', methods=['GET'])
@token_required
def process_user_history_by_id(current_user_id, id):
    storage_service = StorageService()

    cursor = storage_service.get_by_id(id)

    print(type(cursor))

    if cursor is None:
        return jsonify('No value Found'), 200
    
    query = cursor.query

    limit = request.args.get('limit')
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
        database_type = config['database']['type']
        db_instance = databases[database_type]
        
        # Run the query and parse the results
        result = db_instance.run_query(query)
        parsed_result = db_instance.parse_and_serialize(result, schema_manager.schema, properties)
        
        response_data = {
            "nodes": parsed_result[0],
            "edges": parsed_result[1]
        }

        if limit:
            response_data = limit_graph(response_data, limit)

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error processing query: {e}")
        return jsonify({"error": str(e)}), 500
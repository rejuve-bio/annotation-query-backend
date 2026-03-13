from flask import copy_current_request_context, request, jsonify, \
    Response, send_from_directory, send_file, after_this_request
import logging
import json
import os
import threading
import jwt
from pathlib import Path
from app import app, schema_manager, db_instance, socketio, redis_client
from app.lib import validate_request
from flask_cors import CORS
from flask_socketio import disconnect, join_room, send
# from app.lib import limit_graph
from app.lib.auth import token_required, socket_token_required
from app.lib.email import init_mail, send_email
from app.lib.utils import convert_to_csv
from dotenv import load_dotenv
from distutils.util import strtobool
import datetime
from app.lib import Graph, heuristic_sort
from app.annotation_controller import handle_client_request, process_full_data, requery
from app.constants import TaskStatus, Species, form_fields, ROLES
from app.workers.task_handler import get_annotation_redis
from app.persistence import AnnotationStorageService, UserStorageService, SharedAnnotationStorageService
from nanoid import generate
from app.lib.utils import convert_to_tsv
import traceback
from app.lib import convert_to_excel
from pathlib import Path
from app.workers.celery_app import redis_state
from app.events import RedisStopEvent

# Load environmental variables
load_dotenv()

# set mongo logging
logging.getLogger('pymongo').setLevel(logging.CRITICAL)

# set redis logging
logging.getLogger('flask_redis').setLevel(logging.CRITICAL)

# Flask-Mail configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = os.getenv('MAIL_PORT')
app.config['MAIL_USE_TLS'] = bool(
    strtobool(os.getenv('MAIL_USE_TLS', 'false')))
app.config['MAIL_USE_SSL'] = bool(
    strtobool(os.getenv('MAIL_USE_SSL', 'false')))
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

llm = app.config['llm_handler']
EXP = os.getenv('REDIS_EXPIRATION', 3600) # expiration time of redis cache

# Initialize Flask-Mail
init_mail(app)

CORS(app)

@app.route('/kg-info', methods=['GET'])
@token_required
def get_graph_info(current_user_id):
    graph_info = json.dumps(schema_manager.graph_info, indent=4)
    return Response(graph_info, mimetype='application/json')

@app.route('/nodes', methods=['GET'])
@token_required
def get_nodes_endpoint(current_user_id):
    user = UserStorageService.get(current_user_id)
    species = user.species if user else 'human'
    nodes = schema_manager.get_nodes()
    nodes = nodes[species]
    nodes = json.dumps(nodes, indent=4)
    return Response(nodes, mimetype='application/json')

@app.route('/edges', methods=['GET'])
@token_required
def get_edges_endpoint(current_user_id):
    user = UserStorageService.get(current_user_id)
    species = user.species if user else 'human'
    edges = schema_manager.get_edges()
    edges = edges[species]
    edges = json.dumps(edges, indent=4)
    return Response(edges, mimetype='application/json')

@app.route('/relations/<node_label>', methods=['GET'])
@token_required
def get_relations_for_node_endpoint(current_user_id, node_label):
    user = UserStorageService.get(current_user_id)
    species = user.species if user else 'human'
    relations = json.dumps(
        schema_manager.get_relations_for_node(node_label, species), indent=4)
    return Response(relations, mimetype='application/json')

def get_schema_list():
    schema_list = schema_manager.schema_list
    response = schema_list

    return response

def schema_by_source(species, query_string):
    try:
        response = {'schema': {'nodes': [], 'edges': []}}

        if species == 'human':
            schema = schema_manager.schmea_representation
        else:
            schema = schema_manager.fly_schema_represetnation
        if query_string == 'all' and species == 'fly':
            for key, value in schema['nodes'].items():
                response['schema']['nodes'].append({
                    'data': {
                    'name': value['label'],
                    'properites':[property for property in value['properties'].keys()]
                    }
                })

            for key, value in schema['edges'].items():
                is_new = True
                for ed in response['schema']['edges']:
                    if value['source'] == ed['data']['source'] and value['target'] == ed['data']['target']:
                        is_new = False
                        ed['data']['possible_connection'].append( value.get('output_lable') or value.get('input_label') or 'unknown')
                if is_new:
                    response['schema']['edges'].extend(flatten_edges(value))
            return response

        for schema_type in query_string:
            source = schema_type.upper()
            sub_schema = schema.get(source, None)

            if sub_schema is None:
                continue

            for _, values in sub_schema['edges'].items():
                edge_key = values.get('output_label') or values.get('input_label')
                edge = sub_schema['edges'][edge_key]
                edge_data = { 'data': {
                    "possible_connection": [edge.get('output_label') or edge.get('input_label')],
                    "source": edge.get('source'),
                    "target": edge.get('target')
                }}
                response['schema']['edges'].append(edge_data)
                node_to_add_src = schema[source]['nodes'][edge['source']]
                node_label_src = node_to_add_src['label']
                if not node_exists(response, node_label_src):
                    response['schema']['nodes'].append({
                        'data': {
                            'name': node_to_add_src['label'],
                            'properites':[property for property in node_to_add_src['properties'].keys()]
                        }
                    })

                node_to_add_trgt = schema[source]['nodes'][edge['target']]
                node_label_trgt = node_to_add_trgt['label']
                if not node_exists(response, node_label_trgt):
                    response['schema']['nodes'].append({
                                    'data': {
                                        'name': node_to_add_trgt['label'],
                                        'properites':[property for property in node_to_add_trgt['properties'].keys()]
                                    }
                                })

            if len(response['schema']['edges']) == 0:
                for node in sub_schema['nodes']:
                    response['schema']['nodes'].append({
                        'data': {
                            'name': schema[source]['nodes'][node]['label'],
                            'properties': [property for property in schema[source]['nodes'][node]['properties'].keys()]
                        }
                    })
                    response['schema']['nodes'].append(schema[source]['nodes'][node])

        return response
    except Exception as e:
        logging.error(f"Error fetching schema: {e}", exc_info=True)
        return []

def node_exists(response, name):
    name = name.strip().lower()
    return any(n['data']['name'].strip().lower() == name for n in response['schema']['nodes'])

def flatten_edges(value):
    sources = value['source'] if isinstance(value['source'], list) else [value['source']]
    targets = value['target'] if isinstance(value['target'], list) else [value['target']]
    label = value.get('output_label') or value.get('input_label') or 'unknown'

    return [
        {'data': {
            'source': src,
            'target': tgt,
            'possible_connection': [label]
            }
        for src in sources
        for tgt in targets
        }
    ]

@app.route('/preference-option', methods=['GET'])
@token_required
def get_preference_option(current_user_id):
    try:
        response = {
            'species': [specie.value for specie in Species ],
            'sources': {
                'human': [],
                'fly': []
            }
        }

        schema_list = get_schema_list()

        for source in schema_list:
            if source['id'] not in ['polyphen-2', 'bgee']:
                sch = schema_by_source('human', [source['name']])
                data = {
                    'id': source['id'],
                    'name': source['name'],
                    'url': source['url'],
                    'schema': sch['schema']
                }
                response['sources']['human'].append(data)
        schema_fly = schema_by_source('fly', 'all')
        data = {
            'id': 'flyall',
            'name': 'all',
            'schema': schema_fly
        }
        response['sources']['fly'].append(data)
        logging.info(json.dumps({
            "status": "success", "method": "GET",
            "timestamp": datetime.datetime.now().isoformat(),
        }))
        return Response(json.dumps(response, indent=4), mimetype='application/json')
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/preference-option",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }
        return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)

@app.route('/schema', methods=['GET'])
def get_schema_by_data_source():
    try:
        species = request.args.get('species', 'human')
        data_source =request.args.getlist('data_source')

        if len(data_source) == 1 and data_source[0] == 'flyall':
            data_source = 'all'

        print(data_source)
        schemas = schema_by_source(species, data_source)

        response = {'nodes': [], 'edges': []}

        nodes = schemas['schema']['nodes']
        edges = schemas['schema']['edges']

        for node in nodes:
            label = node['data']['name']

            if label in form_fields:
                node_data = form_fields[label]
            else:
                node_data = []

            response['nodes'].append({
                'id': label,
                'name': label,
                'inputs': node_data
            })

        for edge in edges:
            source = edge['data']['source']
            target = edge['data']['target']
            possible_connections = edge['data']['possible_connection']
            for possible_connection in possible_connections:
                response['edges'].append({
                    'id': generate(),
                    'source': source,
                    'target': target,
                    'label': possible_connection
                })
        
        logging.info(json.dumps({"status": "success", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/schema"}))
        return Response(json.dumps(response, indent=4), mimetype='application/json')
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/schema",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }
    return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)

@socketio.on('connect')
# @socket_token_required
def on_connect(current_user_id,  *args, **kwargs):
    logging.info(f"User connected with ID: {current_user_id}")
    send('User is connected')

@socketio.on('disconnect')
def on_disconnect():
    logging.info("user disconnected")
    send("User Disconnected")
    disconnect()

@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)
    logging.info(f"user join a room with {room}")
        # send(f'connected to {room}', to=room)
    cache = get_annotation_redis(room)
    if cache != None:
        status = cache['status']
        graph = cache['graph']
        graph_status = True if graph is not None else False

        if status == TaskStatus.COMPLETE.value:
            socketio.emit('update', {'status': status, 'update': {'graph': graph_status}},
                  to=str(room))
        else:
            socketio.emit('update', {'status': status, 'update': {'graph': graph_status}}, to=str(room))

@app.route('/query', methods=['POST'])  # type: ignore
@token_required
def process_query(current_user_id):
    data = request.get_json()
    if not data or 'requests' not in data:
        return jsonify({"error": "Missing requests data"}), 400


    limit = request.args.get('limit')
    properties = request.args.get('properties')
    # can be either hypothesis or ai_assistant
    source = request.args.get('source')

    if properties:
        properties = bool(strtobool(properties))
    else:
        properties = True

    if limit:
        try:
            limit = int(limit)
        except ValueError:
            return jsonify(
                {"error": "Invalid limit value. It should be an integer."}
            ), 400
    else:
        limit = None
    try:
        requests = data['requests']
        question = requests.get('question', None)
        answer = None
        
        # check if the user has access to modify the query
        annotation_id = requests.get('annotation_id', None)
        
        if annotation_id:
            # get who created the annoation
            existing_annotation = AnnotationStorageService.get_by_id(annotation_id)
            
            owner_id = existing_annotation.user_id
            
            # check if its shared 
            shared_annotation = SharedAnnotationStorageService.get({
                'user_id': owner_id,
                'annotation_id': annotation_id
            })

            if shared_annotation is None:
                # if its not shared check if the one requesting an edit and who created the annoation is the same
                if str(owner_id) != str(current_user_id):
                    return jsonify(
                       {"error": "Unautorized"}
                    ), 401
            else:
                recipient_user_id = shared_annotation.recipient_user_id
                role = shared_annotation.role
                share_type = shared_annotation.share_type

                if share_type == "public":
                    if role not in ["editor", "owner"]:
                        return jsonify({"error": "Unautorized"}), 401
                elif share_type == "private":
                    if role not in ["editor", "owner"]:
                        return jsonify({"error": "Unautorized"}), 401
                    if recipient_user_id != current_user_id:
                        return jsonify({"error": "Unautorized"}), 401

                current_user_id = owner_id
                
        # Validate the request data before processing
        user = UserStorageService.get(current_user_id)
        data_source = user.data_source if user else 'all'
        species = user.species if user else 'human'
        node_map = validate_request(requests, schema_manager.schema[species], source)
        if node_map is None:
            return jsonify(
                {"error": "Invalid node_map returned by validate_request"}
            ), 400

        # convert id to appropriate format
        requests = db_instance.parse_id(requests)

        # sort the predicate based on the the edge count
        requests = heuristic_sort(requests, node_map)

        node_only = True if source == 'hypothesis' else False

        # Generate the query code
        query = db_instance.query_Generator(
            requests, node_map, limit, node_only)

        result_query = query[0]
        total_count_query = query[1]
        count_by_label_query = query[2]

        # Extract node types
        nodes = requests['nodes']
        node_types = set()

        for node in nodes:
            node_types.add(node["type"])

        node_types = list(node_types)

        if source is None:
            return handle_client_request(query, requests,
                                         current_user_id, node_types, species, data_source, node_map)
        result = db_instance.run_query(result_query)

        graph_components = {
            "nodes": requests['nodes'], "predicates": requests['predicates'],
            'properties': properties}

        result_graph = db_instance.parse_and_serialize(
            result, schema_manager.full_schema_representation,
            graph_components, result_type='graph')

        if source == 'hypothesis':
            response = {"nodes": result_graph['nodes']}
            formatted_response = json.dumps(response, indent=4)
            return Response(formatted_response, mimetype='application/json')

        total_count = db_instance.run_query(total_count_query)
        count_by_label = db_instance.run_query(count_by_label_query)

        count_result = [total_count[0], count_by_label[0]]

        meta_data = db_instance.parse_and_serialize(
            count_result, schema_manager.full_schema_representation,
            graph_components, result_type='count')

        title = llm.generate_title(result_query, request, node_map)

        summary = llm.generate_summary(
            result_graph, requests) or 'Graph too big, could not summarize'

        answer = llm.generate_summary(result_graph, requests, question, False, summary)

        graph = Graph()
        if len(result_graph['edges']) == 0:
            response = graph.group_node_only(result_graph, requests)
        else:
            response = graph.group_graph(result_graph)
        response['node_count'] = meta_data['node_count']
        response['edge_count'] = meta_data['edge_count']
        response['node_count_by_label'] = meta_data['node_count_by_label']
        response['edge_count_by_label'] = meta_data['edge_count_by_label']

        annotation = {"current_user_id": str(current_user_id),
                      "request": requests,
                      "query": result_query,
                      "title": title,
                      "summary": summary,
                      "node_count": response['node_count'],
                      "edge_count": response['edge_count'],
                      "node_types": node_types,
                      "node_count_by_label": response['node_count_by_label'],
                      "edge_count_by_label": response['edge_count_by_label'],
                      "answer": answer, "question": question,
                      "status": TaskStatus.COMPLETE.value
                      }

        annotation_id = AnnotationStorageService.save(annotation)
        redis_client.setex(str(annotation_id), EXP, json.dumps({'task': 4,
                                'graph': {'nodes': response['nodes'], 'edges': response['edges']}}))
        response = {"annotation_id": str(
            annotation_id), "question": question, "answer": answer}
        formatted_response = json.dumps(response, indent=4)
        
        logging.info(json.dumps({"status": "success", "method": "POST",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/query"}))
    
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "POST",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/query",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)


@app.route('/email-query/<id>', methods=['POST'])
@token_required
def process_email_query(current_user_id, id):
    data = request.get_json()
    if 'email' not in data:
        return jsonify({"error": "Email missing"}), 400


    @copy_current_request_context
    def send_full_data():
        try:
            email = data['email']

            link = process_full_data(
                current_user_id=current_user_id, annotation_id=id)

            subject = 'Full Data'
            body = f'Hello {email}. click this link {link}\
            to download the full data you requested.'

            send_email(subject, [email], body)
        except Exception as e:
            logging.error(f"Error processing query: {e}", exc_info=True)

    sender = threading.Thread(name='main_sender', target=send_full_data)
    sender.start()
    return jsonify({'message': 'Email sent successfully'}), 200

@app.route('/history', methods=['GET'])
@token_required
def process_user_history(current_user_id):
    try:
        page_number = request.args.get('page_number')
        if page_number is not None:
            page_number = int(page_number)
        else:
            page_number = 1
        return_value = []

        cursor = UserStorageService.get(current_user_id)
        cursor = AnnotationStorageService.get_all(str(current_user_id), page_number)


        if cursor is None:
            return jsonify('No value Found'), 200

        for document in cursor:
            source = document.get('data_source', 'all')
            if document.get('species', 'human') == 'fly':
                source = ['flyall']
            if document.get('species', 'human') == 'human' and document.get('data_source', 'all') == 'all':
                source = ['all']
            return_value.append({
                'annotation_id': str(document['_id']),
                "request": document['request'],
                'title': document['title'],
                'node_count': document['node_count'],
                'edge_count': document['edge_count'],
                'node_types': document['node_types'],
                'status': document['status'],
                'species': document.get('species', 'human'),
                'source': source, 
                "created_at": document['created_at'].isoformat(),
                "updated_at": document["updated_at"].isoformat()
            })
        
        logging.info(json.dumps({"status": "success", "method": "GET",
                          "timestamp":  datetime.datetime.now().isoformat(),
                          "endpoint": "/history"}))
                
        return Response(json.dumps(return_value, indent=4),
                        mimetype='application/json')
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/history",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)

@app.route('/annotation/<id>', methods=['GET'])
@token_required
def get_by_id(current_user_id, id):
    token = request.args.get('token', None)
    try:
        if token:
            SHARED_TOKEN_SECRET = os.getenv('SHARED_TOKEN_SECRET')
            data = jwt.decode(token, SHARED_TOKEN_SECRET, algorithms=['HS256'])
            current_user_id = data['user_id']

            shared_resource = SharedAnnotationStorageService.get({
                'user_id': current_user_id,
                'annotation_id': id
            })

            if shared_resource is None:
                return jsonify({'error': 'unauthorized'}), 401
    except Exception as e:
        return jsonify({'error': 'unauthorized'}), 401
    
    existing_annotation = AnnotationStorageService.get_by_id(id)
    
    owner_id = existing_annotation.user_id
    
    # check if its shared 
    shared_annotation = SharedAnnotationStorageService.get({
        'user_id': owner_id,
        'annotation_id': id
    })
    
    if shared_annotation is None:
        if str(owner_id) != str(current_user_id):
            return jsonify({'error': 'unauthorized'}), 401
    else:
        share_type = shared_annotation.share_type
        recipient_user_id = shared_annotation.recipient_user_id
        
        if share_type != 'public':
            if str(recipient_user_id) != str(current_user_id):
                return jsonify({'error': 'unauthorized'}), 401
            
        current_user_id = owner_id


    response_data = {}
    cursor = AnnotationStorageService.get_user_annotation(id, current_user_id)

    if cursor is None:
        return jsonify('No value Found'), 404

    limit = request.args.get('limit')
    properties = request.args.get('properties')

    # can be either hypothesis or ai_assistant
    source = request.args.get('source')

    if properties:
        properties = bool(strtobool(properties))
    else:
        properties = False

    if limit:
        try:
            limit = int(limit)
        except ValueError:
            return jsonify(
                {"error": "Invalid limit value. It should be an integer."}
            ), 400

    json_request = cursor.request
    query = cursor.query
    title = cursor.title
    summary = cursor.summary
    annotation_id = cursor.id
    question = cursor.question
    answer = cursor.answer
    node_count = cursor.node_count
    edge_count = cursor.edge_count
    node_count_by_label = cursor.node_count_by_label
    edge_count_by_label = cursor.edge_count_by_label
    status = cursor.status
    file_path = cursor.path_url
    species = cursor.species
    source = cursor.data_source
    files = cursor.files

    # Extract node types
    nodes = json_request['nodes']
    node_types = set()
    for node in nodes:
        node_types.add(node["type"])
    node_types = list(node_types)

    try:
        if question:
            response_data["question"] = question

        if answer:
            response_data["answer"] = answer

        if source == 'ai-assistant':
            response = {"annotation_id": str(
                annotation_id), "question": question, "answer": answer}
            formatted_response = json.dumps(response, indent=4)
            return Response(formatted_response, mimetype='application/json')

        response_data["annotation_id"] = str(annotation_id)
        response_data["request"] = json_request
        response_data["title"] = title
        response_data["query"] = query
        response_data["files"] = files
        
        if species == 'fly':
            source = ['flyall']
        if species == 'human' and source=='all':
            source = ['all']
        response_data['source'] = source
        response_data['species'] = species

        if summary is not None:
            response_data["summary"] = summary
        if node_count is not None:
            response_data["node_count"] = node_count
            response_data["edge_count"] = edge_count
        if node_count_by_label is not None:
            response_data["node_count_by_label"] = node_count_by_label
            response_data["edge_count_by_label"] = edge_count_by_label
        response_data["status"] = status

        cache = redis_client.get(str(annotation_id))

        if cache is not None:
            cache = json.loads(cache)
            graph = cache['graph']
            if graph is not None:
                response_data['nodes'] = graph['nodes']
                response_data['edges'] = graph['edges']

            return Response(json.dumps(response_data, indent=4), mimetype='application/json')

        if status in [TaskStatus.PENDING.value, TaskStatus.COMPLETE.value]:
            if status == TaskStatus.COMPLETE.value:
                if os.path.exists(file_path):
                    # open the file and read the graph
                    with open(file_path, 'r') as file:
                        graph = json.load(file)

                    response_data['nodes'] = graph['nodes']
                    response_data['edges'] = graph['edges']
                else:
                    response_data['status'] = TaskStatus.PENDING.value
                    requery(annotation_id, query, json_request)
            formatted_response = json.dumps(response_data, indent=4)
            return Response(formatted_response, mimetype='application/json')

        # Run the query and parse the results
        result = db_instance.run_query(query)
        graph_components = {"properties": properties}
        response_data = db_instance.parse_and_serialize(
            result, schema_manager.full_schema_representation,
            graph_components, result_type='graph')
        graph = Graph()
        if (len(response_data['edges']) == 0):
            grouped_graph = graph.group_node_only(response_data, json_request)
        else:
            grouped_graph = graph.group_graph(response_data)
        response_data['nodes'] = grouped_graph['nodes']
        response_data['edges'] = grouped_graph['edges']

        if source == 'hypothesis':
            response = {
                "nodes": response_data['nodes'],
                "edges": response_data['edges']
            }
            formatted_response = json.dumps(response, indent=4)
            return Response(formatted_response, mimetype='application/json')
        # if limit:
        # response_data = limit_graph(response_data, limit)

        logging.info(json.dumps({"status": "success", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>"}))
        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)

@app.route('/annotation/<id>', methods=['POST'])
@token_required
def process_by_id(current_user_id, id):
    data = request.get_json()
    if not data or 'requests' not in data:
        return jsonify({"error": "Missing requests data"}), 400

    if 'question' not in data["requests"]:
        return jsonify({"error": "Missing question data"}), 400

    question = data['requests']['question']
    response_data = {}
    cursor = AnnotationStorageService.get_user_annotation(id, current_user_id)

    limit = request.args.get('limit')
    properties = request.args.get('properties')
    # can be either hypothesis or ai_assistant
    source = request.args.get('source')

    if properties:
        properties = bool(strtobool(properties))
    else:
        properties = False

    if limit:
        try:
            limit = int(limit)
        except ValueError:
            return jsonify(
                {"error": "Invalid limit value. It should be an integer."}
            ), 400

    if cursor is None:
        return jsonify('No value Found'), 200

    query = cursor.query
    summary = cursor.summary
    json_request = cursor.request
    node_count_by_label = cursor.node_count_by_label
    edge_count_by_label = cursor.edge_count_by_label

    try:
        if question:
            response_data["question"] = question

        cache = redis_client.get(str(id))

        if cache is not None:
            cache = json.loads(cache)
            graph = cache['graph']
            if graph is not None:
                response_data['nodes'] = graph['nodes']
                response_data['edges'] = graph['edges']
        else:
            # Run the query and parse the results
            result = db_instance.run_query(query)
            graph_components = {"properties": properties}
            response_data = db_instance.parse_and_serialize(
                result, schema_manager.full_schema_representation, graph_components, result_type='graph')

        response_data['node_count_by_label'] = node_count_by_label
        response_data['edge_count_by_label'] = edge_count_by_label

        answer = llm.generate_summary(
            response_data, json_request, question, False, summary) if question else None

        AnnotationStorageService.update(
            id, {"answer": answer, "updated_at": datetime.datetime.now()})

        response = {"annotation_id": str(
            id), "question": question, "answer": answer}

        logging.info(json.dumps({"status": "success", "method": "POST",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>"}))

        formatted_response = json.dumps(response, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "POST",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)

@app.route('/annotation/<id>/full', methods=['GET'])
@token_required
def process_full_annotation(current_user_id, id):
    try:
        link = process_full_data(
            current_user_id=current_user_id, annotation_id=id)
        if link is None:
            return jsonify('No value Found'), 200

        response_data = {
            'link': link
        }

        logging.info(json.dumps({"status": "success", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>/full",
                                  }))

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>/full",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)

@app.route('/public/<file_name>')
def serve_file(file_name):
    public_folder = os.path.join(os.getcwd(), 'public')
    return send_from_directory(public_folder, file_name)

@app.route('/annotation/<id>', methods=['DELETE'])
@token_required
def delete_by_id(current_user_id, id):
    try:
        # check if the user have access to delete the resource
        annotation = AnnotationStorageService.get_user_annotation(id, current_user_id)

        if annotation is None:
            return jsonify('No value Found'), 404
        stop_event = RedisStopEvent(id, redis_state)
        status = stop_event.get_status()
        
        # first check if there is any running running annoation
        if status is not None:
            stop_event.set_event()
            
            response_data = {
                    'message': f'Annotation {id} has been cancelled.'
                }

        # else delete the annotation from the db
        existing_record = AnnotationStorageService.get_by_id(id)

        if existing_record is None:
            return jsonify('No value Found'), 404

        deleted_record = AnnotationStorageService.delete(id)

        if deleted_record is None:
            return jsonify('Failed to delete the annotation'), 500


        response_data = {
            'message': 'Annotation deleted successfully'
        }
        
        logging.info(json.dumps({"status": "success", "method": "DELETE",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>",
                                 }))

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "DELETE",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)


@app.route('/annotation/<id>/title', methods=['PUT'])
@token_required
def update_title(current_user_id, id):
    data = request.get_json()

    if 'title' not in data:
        return jsonify({"error": "Title is required"}), 400

    title = data['title']

    try:
        existing_record = AnnotationStorageService.get_by_id(id)

        if existing_record is None:
            return jsonify('No value Found'), 404

        AnnotationStorageService.update(id, {'title': title})

        response_data = {
            'message': 'title updated successfully',
            'title': title,
        }

        logging.info(json.dumps({"status": "success", "method": "PUT",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>/title",
                                  "exception": str(e)}), exc_info=True)
    
        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "PUT",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>/title",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)

@app.route('/annotation/delete', methods=['POST'])
@token_required
def delete_many(current_user_id):
    data = request.data.decode('utf-8').strip()  # Decode and strip the string of any extra spaces or quotes

    # Ensure that data is not empty or just quotes
    if not data or data.startswith("'") and data.endswith("'"):
        data = data[1:-1]  # Remove surrounding quotes

    try:
        data = json.loads(data)  # Now parse the cleaned string
    except json.JSONDecodeError:
        return {"error": "Invalid JSON"}, 400  # Return 400 if the JSON is invalid

    if 'annotation_ids' not in data:
        return jsonify({"error": "Missing annotation ids"}), 400

    annotation_ids = data['annotation_ids']

    #check if user have access to delete the resource
    for annotation_id in annotation_ids:
        annotation = AnnotationStorageService.get_user_annotation(annotation_id, current_user_id)
        if annotation is None:
            return jsonify('No value Found'), 404

    if not isinstance(annotation_ids, list):
        return jsonify({"error": "Annotation ids must be a list"}), 400

    if len(annotation_ids) == 0:
        return jsonify({"error": "Annotation ids must not be empty"}), 400

    try:
        delete_count = AnnotationStorageService.delete_many_by_id(annotation_ids)

        response_data = {
            'message': f'Out of {len(annotation_ids)}, {delete_count} were successfully deleted.'
        }
        
        logging.info(json.dumps({"status": "success", "method": "POST",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/delete"}))

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "POST",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/delete",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)

@app.route('/save-preference', methods=['POST'])
@token_required
def update_settings(current_user_id):
    data = request.get_json()

    data_source = data.get('sources', None)
    species = data.get('species', None)

    if data_source is None:
        return jsonify({"error": "Missing data source"}), 400

    if species is None:
        species = 'human'
    
    if species == "fly":
        data_source = 'all'

    if isinstance(data_source, str):
        if data_source.lower() == 'all' or data_source.lower() == "flyall":
            UserStorageService.upsert_by_user_id(current_user_id,
                                             {'data_source': 'all', 'species': species})

            if species == 'fly':
                response_data = {
                    'message': 'Data source updated successfully',
                    'data_source': ['flyall']
                }
            else:
                response_data = {
                    'message': 'Data source updated successfully',
                    'data_source': ['all']
                }
            formatted_response = json.dumps(response_data, indent=4)
            return Response(formatted_response, mimetype='application/json')
        else:
            return jsonify({"error": "Invalid data source format"}), 400

    schema_list = get_schema_list()
    ids = []

    if species == "fly" and data_source != "flyall":
        return jsonify({"error": "Invalid data source for species fly"}), 400

    for schema in schema_list:
        ids.append(schema['id'].lower())

    # check if the data source is valid
    for ds in data_source:
        if ds.lower() not in ids:
            return jsonify({"error": f"Invalid data source: {ds}"}), 400

    try:
        UserStorageService.upsert_by_user_id(current_user_id,
                                         {'data_source': data_source, 'species': species})

        response_data = {
            'message': 'Data source updated successfully',
            'data_source': data_source
        }
        
        logging.info(json.dumps({"status": "success", "method": "POST",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/save-preference"}))

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "POST",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/save-preference",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)
        logging.error(f"Error updating data source: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/saved-preference', methods=['GET'])
@token_required
def get_saved_preferences(current_user_id):
    try:
        preferences = UserStorageService.get(current_user_id)
        if preferences:
            data_source = preferences.data_source
            species = preferences.species
        else:
            data_source = ['GWAS']
            species = 'human'
        
        if species == 'fly':
            data_source = ['flyall']

        response_data = {
            'species': species,
            'source': data_source
        }
        
        logging.info(json.dumps({"status": "success", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/saved-preference"}))

        return Response(json.dumps(response_data, indent=4), mimetype='application/json')
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/saved-preference",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)

@app.route("/share", methods=["POST"])
@token_required
def share_annotation(current_user_id):
    try:
        data = request.get_json()

        annotation_id = data.get('annotation_id', None)
        share_type = data.get('share_type', 'public')   # default is public
        recipient_user_id = data.get('recipient_user_id')  # only required for private
        role = data.get('role')
        
        if role not in ROLES:
            return jsonify({"error": "Role should be viewer, owner or editor"})
            

        if not annotation_id:
            return jsonify({"error": "Missing annotation ID"}), 400

        annotation = AnnotationStorageService.get_by_id(annotation_id)

        if not annotation:
            return jsonify({"error": "Annotation not found"}), 404

        # If private, recipient_user_id must be given
        if share_type == "private" and not recipient_user_id:
            return jsonify({"error": "Missing recipient user ID for private share"}), 400

        # Check if already shared
        shared_resource = SharedAnnotationStorageService.get({
            'user_id': current_user_id,
            'annotation_id': annotation_id,
        })

        if shared_resource:
            new_shared_resouce = SharedAnnotationStorageService.update(shared_resource.id, {
                'annotation_id': annotation_id,
                'share_type': share_type,
                'recipient_user_id': recipient_user_id,
                'token': shared_resource.token,
                'role': role
            })
            response = {
                'user_id': current_user_id,
                'annotation_id': annotation_id,
                'share_type': share_type,
                'recipient_user_id': recipient_user_id,
                'token': shared_resource.token,
                'role': role
            }

            return Response(json.dumps(response, indent=4), mimetype='application/json')

        # JWT Secret Key
        SHARED_TOKEN_SECRET = os.getenv("SHARED_TOKEN_SECRET")
        
        if not SHARED_TOKEN_SECRET:
            raise Exception("SHARED_TOKEN_SECRET is not configured")

        payload = {
            'user_id': current_user_id,
            'annotation_id': annotation_id,
            'share_type': share_type,
            'recipient_user_id': recipient_user_id
        }

        # generate a unique sharable token
        token = jwt.encode(payload, SHARED_TOKEN_SECRET, algorithm="HS256")

        # Save share entry
        shared_annotation = SharedAnnotationStorageService.save({
            'current_user_id': current_user_id,
            'annotation_id': annotation_id,
            'token': token,
            'share_type': share_type,
            'recipient_user_id': recipient_user_id,
            'role': role
        })

        if not shared_annotation:
            return jsonify({"error": "Failed to save shared annotation"}), 500

        response = {
            'user_id': current_user_id,
            'annotation_id': annotation_id,
            'share_type': share_type,
            'recipient_user_id': recipient_user_id,
            'token': token,
            'role': role
        }

        return Response(json.dumps(response, indent=4), mimetype='application/json')
    except Exception as e:
        logging.error(f"Error sharing annotation: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/share/<id>", methods=["DELETE"])
@token_required
def revoke_shared_annotation(current_user_id, id):
    try:
        # Get the annotation
        annotation = AnnotationStorageService.get_by_id(id)
        if annotation is None:
            return jsonify({'error': 'No annotation found'}), 404

        # Only owner can revoke
        if annotation.user_id != current_user_id:
            return jsonify({'error': 'Unauthorized'}), 401

        # Get the shared record
        shared_resource = SharedAnnotationStorageService.get({
            'user_id': current_user_id,
            'annotation_id': id,
        })

        if shared_resource is None:
            return jsonify({'error': 'No shared record found'}), 404

        # Delete the shared record
        SharedAnnotationStorageService.delete(shared_resource.id)

        return jsonify({'message': 'Annotation revoked successfully'}), 200

    except Exception as e:
        logging.error(f"Error revoking shared annotation: {e}")
        return jsonify({"error": str(e)}), 500
 
@app.route("/localized-graph", methods=["GET"])
@token_required
def cell_component(current_user_id):
    # get annotation id and get go term id
    annotation_id = request.args.get('id')
    locations = request.args.get('locations')

    # parse the location
    locations = locations.split(',')

    proteins = []

    try:
        # get the graph and filter out the protein
        file_name = f'{annotation_id}.json'
        path = Path(__file__).parent /".."/ "public" / "graph" / f"{file_name}"

        with open(path, 'r') as f:
            graph = json.load(f)

        nodes = graph['nodes']
        edges = graph['edges']


        # filter out the parents
        parent_edges = {}

        for node in nodes:
            if node['data']['type'] == 'parent':
                parent_edges[node['data']['id']] = []

        for node in nodes:
            if 'parent' in node['data'] and node['data']['type'] == 'protein':
                parent_edges[node['data']['parent']].append(node['data']['id'])

        new_edge = []

        for i, edge in enumerate(edges):
            if edge['data']['source'] in parent_edges:
                for child in parent_edges[edge['data']['source']]:
                    new_edge.append({
                        "data": {
                            "source": child,
                            "target": edge['data']['target'],
                            "label": edge['data']['label'],
                            "edge_id": edge['data']['edge_id'],
                            "id": generate()
                        }
                    })
            elif edge['data']['target'] in parent_edges:
                for child in parent_edges[edge['data']['target']]:
                    new_edge.append({
                        "data": {
                            "source": edge['data']['source'],
                            "target": child,
                            "label": edge['data']['label'],
                            "edge_id": edge['data']['edge_id'],
                            "id": generate()
                        }
                    })
            else:
               new_edge.append({
                   "data": {
                       "source": edge['data']['source'],
                       "target": edge['data']['target'],
                       "label": edge['data']['label'],
                       "edge_id": edge['data']['edge_id'],
                       "id": generate()
                   }
               })

        node_to_edge_relationship = {}

        inital_node_map = {}

        for node in nodes:
            if node['data']['type'] == 'protein':
                if node['data']['id'] not in inital_node_map:
                    inital_node_map[node['data']['id']] = node

        for edge in new_edge:
            source = edge['data']['source']
            target = edge['data']['target']
            label = edge['data']['label']

            if source in inital_node_map and target in inital_node_map:
                source_nodes = []
                target_nodes = []

                if inital_node_map[source]['data']['type'] != 'parent':
                    for single_node in inital_node_map[source]['data']['nodes']:
                        source_nodes.append(single_node['id'])

                if inital_node_map[target]['data']['type'] != 'parent':
                    for single_node in inital_node_map[target]['data']['nodes']:
                        target_nodes.append(single_node['id'])

                for source_node in source_nodes:
                    for target_node in target_nodes:
                        key = f"{source_node}_{label}_{target_node}"
                        node_to_edge_relationship[key] = {
                            'source': source_node,
                            'label': label,
                            'target': target_node
                        }

        response = {"nodes": [], "edges": []}

        for key, value in node_to_edge_relationship.items():
            edge_id_arr = key.split(' ')
            middle_arr = edge_id_arr[1].split('_')
            middle = '_'.join(middle_arr[1:len(middle_arr)])
            edge_id = f'{edge_id_arr[0]}_{middle}'
            response['edges'].append({
                'data': {
                    'id': generate(),
                    'source': value['source'],
                    'target': value['target'],
                    'label': value['label'],
                    'edge_id': edge_id
                }
            })


        go_ids = []
        protein_node_map = {}

        for node in nodes:
            if node['data']['type'] == 'protein':
                for single_node in node['data']['nodes']:
                    id = single_node['id'].split(' ')[1]
                    proteins.append(id)
                    if id not in protein_node_map:
                        protein_node_map[id] = {}
                    protein_node_map[id]["data"] = { **single_node, "location": "" }

        go_subcomponents = {
            "type": "go",
            "id": "",
            "properties": {
                "subontology": "cellular_component"
            }
        }

        go_parent = {
            "type": "go",
            "id": "",
            "properties": {}
        }

        for location in locations:
            go_id = location.lower()
            go_id = go_id.replace(':', '_')
            go_ids.append(go_id)

        query = db_instance.list_query_generator_source_target(go_subcomponents, go_parent, go_ids, "subclass_of")
        result = db_instance.run_query(query)
        parsed_result_go = db_instance.parse_list_query(result)
        
        if not parsed_result_go:
            # Return proteins with empty location
            response = {"nodes": [], "edges": []}
        
            for node in nodes:
                if node["data"]["type"] == "protein":
                    for single_node in node["data"]["nodes"]:
                        id = single_node["id"].split(" ")[1]
        
                        response["nodes"].append({
                            "data": {
                                **single_node,
                                "location": ""
                            }
                        })
        
            logging.info(json.dumps({
                "status": "success",
                "method": "GET",
                "timestamp": datetime.datetime.now().isoformat(),
                "endpoint": "/localized-graph"
            }))
        
            return Response(json.dumps(response, indent=4), mimetype='application/json')
        
            
        go_ids = []

        for key in parsed_result_go.keys():
            go_ids.append(key)
            go_ids.extend(parsed_result_go[key]['node_ids'])

        source = {
            "type": "go",
            "id": "",
            "properties": {}
        }

        target = {
            "type": "protein",
            "id": "",
            "properties": {}
        }
        query = db_instance.list_query_generator_both(source, target, go_ids, proteins, "go_gene_product")
        result = db_instance.run_query(query)
        parsed_result = db_instance.parse_list_query(result)

        for key in parsed_result.keys():
            normalized_id = []
            location = parsed_result[key]['node_ids']
            for i, _ in enumerate(location):
                for parent_id in parsed_result_go.keys():
                    if location[i] == parent_id or location[i] in parsed_result_go[parent_id]['node_ids']:
                        normalized_id.append(parent_id.replace('_', ':').upper())
            protein_node_map[key]['data']['location'] =  ','.join(normalized_id)

        for values in protein_node_map.values():
            response["nodes"].append(values)


        logging.info(json.dumps({"status": "success", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/localized-graph"}))

        return Response(json.dumps(response, indent=4), mimetype='application/json')
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/localized-graph",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)

@app.route('/annotation/<id>/download-tsv', methods=['GET'])
@token_required
def download_csv(current_user_id, id):
    cursor = cursor = storage_service.get_by_id(id)
    
    if cursor is None:
        return jsonify('No value Found'), 404

    file_path = cursor.path_url
    
    try:
        graph = json.load(open(file_path))
        
        g = Graph()
        new_graph = g.break_grouping(graph)
        
        file_obj = convert_to_tsv(new_graph)
        
        if file_obj:
            logging.error(json.dumps({"status": "success", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>/download-tsv"}))
            return send_file(
                file_obj,
                mimetype='application/zip',
                as_attachment=True,
                download_name='graph_export.zip'
            )
        else:
            logging.error(json.dumps({"status": "error", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>/download-tsv",
                                  "exception": "Error generating the file"}))
            return jsonify('Error generating the file'), 500
        
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>/download-tsv",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return Response(json.dumps(error_response, indent=4),
                    mimetype='application/json',
                    status=500)

@app.route('/public/vcf/<filename>', methods=['GET'])
def download_vcf_file(filename):
    public_folder = os.path.join(os.getcwd(), 'public')
    file_path = os.path.join(public_folder, "vcf", filename)
    return send_file(file_path, as_attachment=True)

@app.route('/autofill', methods=['GET'])
@token_required
def autofill(current_user_id):
    node_type = request.args.get('type')
    annotation_id = request.args.get('id')
    species = request.args.get('species') or 'human'
    
    request_json = {
        "nodes": [
        {
            "node_id": "n1",
            "id": annotation_id,
            "type": node_type,
            "properties": {}
        }
        ],
        "predicates": []
    }
    
    
    node_map = {}
    for node in request_json['nodes']:
        if node['node_id'] not in node_map:
            node_map[node['node_id']] = node
        else:
            raise Exception('Repeated Node_id')
    
    query = db_instance.query_Generator(request_json, node_map)
    result = db_instance.run_query(query[0], stop_event=None, species=species)
    graph_components = {
    "nodes": request_json['nodes'], "predicates": request_json['predicates'],
    'properties': True}
    result =  db_instance.parse_and_serialize(
            result, schema_manager.full_schema_representation,
            graph_components, result_type='graph')

    
    data = result["nodes"][0]
    
    return Response(json.dumps(data, indent=4), mimetype='application/json')

@app.route('/health', methods=['GET'])
def health():
    return Response(json.dumps({"status": "ok"}), mimetype='application/json')
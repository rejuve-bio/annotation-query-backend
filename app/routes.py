from flask import copy_current_request_context, request, jsonify, \
    Response, send_from_directory
import logging
import json
import os
import threading
import time
from app import app, schema_manager, db_instance, socketio, redis_client
from app.lib import validate_request
from flask_cors import CORS
from flask_socketio import disconnect, join_room, send
# from app.lib import limit_graph
from app.lib.auth import token_required, socket_token_required
from app.lib.email import init_mail, send_email
from dotenv import load_dotenv
from distutils.util import strtobool
import datetime
from app.lib import convert_to_csv, generate_file_path, \
    adjust_file_path, Graph

# Load environmental variables
load_dotenv()

# set mongo logging
logging.getLogger('pymongo').setLevel(logging.CRITICAL)

# set redis logging
logging.getLogger('flask_redis').setLevel(logging.CRITICAL)

# Flask-Mail configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
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
storage_service = app.config['storage_service']
EXP = os.getenv('REDIS_EXPIRATION', 3600) # expiration time of redis cache

# Initialize Flask-Mail
init_mail(app)

CORS(app)

# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

@app.route('/kg-info', methods=['GET'])
@token_required
def get_graph_info(current_user_id):
    graph_info = json.dumps(schema_manager.graph_info, indent=4)
    return Response(graph_info, mimetype='application/json')

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
    relations = json.dumps(
        schema_manager.get_relations_for_node(node_label), indent=4)
    relations = json.dumps(
        schema_manager.get_relations_for_node(node_label), indent=4)
    return Response(relations, mimetype='application/json')


@socket_token_required
@socketio.on('connect')
def on_connect(current_user_id):
    logging.info("User connected")
    send('User is conncted')

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
    send(f'connected to {room}', to=room)
    
def update_task(annotation_id, graph=None):
    status = 'PENDING'
    
    # Get the cached data (Handle case where cache is None)
    cache = redis_client.get(str(annotation_id))
    cache = json.loads(cache) if cache else {'graph': None, 'status': status}
    
    # Merge graph updates
    graph = graph if graph else cache['graph']
    
    # Increment task count atomically and get the new count
    task_num = redis_client.incr(f"{annotation_id}_tasks")
    
    if cache['status'] == 'FAILED':
        status = 'FAILED'
    elif task_num >= 4 and cache['status'] != 'FAILED':
        status = 'COMPLETE'
    else:
        status = 'PENDING'
        
        
    if status in ['FAILED', 'COMPLETE'] and task_num >= 4:
        redis_client.setex(str(annotation_id), EXP, json.dumps({
            'graph': graph, 'status': status
        }))
        storage_service.update(annotation_id, {'status': status})
        redis_client.delete(f"{annotation_id}_tasks")
    else:
        redis_client.set(str(annotation_id), json.dumps({
            'graph': graph, 'status': status
        }))
    
    return status


def get_status(annotation_id):
    cache = redis_client.get(str(annotation_id))
    if cache is not None:
        cache = json.loads(cache)
        status = cache['status']
        return status
    else:
        return 'PENDING'
    
def set_status(annotation_id, status):
    cache = redis_client.get(str(annotation_id))
    if cache is not None:
        cache = json.loads(cache)
        cache['status'] = status
        redis_client.set(str(annotation_id), json.dumps(cache))
    else:
        redis_client.set(str(annotation_id), json.dumps({'graph': None, 'status': status}))

def reset_status(annotation_id):
    redis_client.delete(f"{annotation_id}_tasks")
    set_status(annotation_id, 'PENDING')

def reset_task(annotation_id):
    redis_client.delete(f"{annotation_id}_tasks")
    redis_client.delete(str(annotation_id))

def generate_summary(annotation_id, request, all_status, summary=None):
    result_done, total_count_done, label_count_done = all_status.values()
    # wait for all threads to finish
    result_done.wait()
    total_count_done.wait()
    label_count_done.wait()

    if get_status(annotation_id) == 'FAILED':
        summary = 'Failed to generate summary'
        status = 'FAILED'
        status = update_task(annotation_id)
        socketio.emit('update', {'status': status, 'update': {'summary': summary}},
                  to=str(annotation_id))
        
        return 

    if summary is not None:
        status = update_task(annotation_id)
        socketio.emit('update', {'status': status, 'update': {'summary': summary}},
                  to=str(annotation_id))

        return
    
    meta_data = storage_service.get_by_id(annotation_id)
    cache = redis_client.get(str(annotation_id))

    if cache is not None:
        cache = json.loads(cache)
        graph = cache['graph']
        if graph is not None:
            response = {'nodes': graph['nodes'], 'edges': graph['edges']}
        else:
            response = {'nodes': [], 'edges': []}

    response['node_count'] = meta_data.node_count
    response['edge_count'] = meta_data.edge_count
    response['node_count_by_label'] = meta_data.node_count_by_label
    response['edge_count_by_label'] = meta_data.edge_count_by_label

    try:
        if len(response['nodes']) == 0:
            summary = 'No summary for this graph because the graph is empty'
        else:
            summary = llm.generate_summary(response, request) 
            summary = summary if summary else 'Graph too big, could not summarize'
        storage_service.update(annotation_id, {"summary": summary})

        status = update_task(annotation_id)
        socketio.emit('update', {'status': status, 'update': {'summary': summary}},
                  to=str(annotation_id))
    except Exception as e:
        logging.error(e)
        status = update_task(annotation_id)
        socketio.emit('update', {'status': status, 
                        'update': {'summary': 'Graph too big, could not summarize'}},
                      to=str(annotation_id))


def generate_result(query_code, annotation_id, requests, result_status):
    try:
        response_data = db_instance.run_query(query_code)
        graph_components = {"nodes": requests['nodes'], "predicates":
                            requests['predicates'], "properties": True}
        response = db_instance.parse_and_serialize(
            response_data, schema_manager.schema, graph_components, 'graph')
        
        graph = Graph()
        grouped_graph = graph.group_graph(response)
        
        status = update_task(annotation_id, {
            'nodes': grouped_graph['nodes'],
            'edges': grouped_graph['edges']
        })
        socketio.emit('update', {'status': status,
                                 'update': {'graph': True}
                                 },
                      to=str(annotation_id))
        
        result_status.set()

        return grouped_graph
    except Exception as e:
        set_status(annotation_id, 'FAILED')
        socketio.emit('update', {'status': 'FAILED', 'update': {'graph': False}})
        result_status.set()
        logging.error(e)


def generate_total_count(count_query, annotation_id, requests, total_count_status, meta_data=None):
    if get_status(annotation_id) == 'FAILED':
        socketio.emit('update', {'status': 'FAILED', 'update': {'node_count': 0, 'edge_count': 0}})
        status = update_task(annotation_id)
        total_count_status.set()
        
        return 
        
    if meta_data:
        status = update_task(annotation_id)
        socketio.emit('update', {
            'status': status,
            'update': {'node_count': meta_data['node_count'],
                       'edge_count': meta_data['edge_count']
                       }},
                      to=str(annotation_id))
        total_count_status.set()
        return
        
    try:

        total_count = db_instance.run_query(count_query)
        
        if len(total_count) == 0:
            status = update_task(annotation_id)
            storage_service.update(annotation_id, {'status': status, 'node_count': 0, 'edge_count': 0})
            socketio.emit('update', {'status': status, 'update': {'node_count': 0, 'edge_count': 0}})
            total_count_status.set()
            return

        count_result = [total_count[0], {}]
        graph_components = {"nodes": requests['nodes'],
                            "predicates": requests['predicates'],
                            "properties": False}
        response = db_instance.parse_and_serialize(
            count_result, schema_manager.schema, graph_components, 'count')

        status = update_task(annotation_id)

        storage_service.update(annotation_id,
                               {'node_count': response['node_count'],
                                'edge_count': response['edge_count'],
                                'status': status
                                })

        socketio.emit('update', {
            'status': status,
            'update': {'node_count': response['node_count'],
                       'edge_count': response['edge_count']
                       }},
                      to=str(annotation_id))
        total_count_status.set()
    except Exception as e:
        status = update_task(annotation_id)
        storage_service.update(annotation_id, {'status': status, 'node_count': 0, 'edge_count': 0})
        socketio.emit('update', {'status': status, 'update': {'node_count': 0, 'edge_count': 0}})
        total_count_status.set()
        logging.error(e)

def generate_empty_lable_count(requests):
    update = {'node_count_by_label': [], 'edge_count_by_label': []}
    node_count_by_label = {}
    edge_count_by_label = {}

    for node in requests['nodes']:
        node_count_by_label[node['type']] = 0

    for edges in requests['predicates']:
        edge_count_by_label[edges['type']] = 0
    
    for key, value in node_count_by_label.items():
        update['node_count_by_label'].append({key: value})

    for key, value in edge_count_by_label.items():
        update['edge_count_by_label'].append({key: value})

    return update

def generate_label_count(count_query, annotation_id, requests, count_label_status, meta_data=None):
    if get_status(annotation_id) == 'FAILED':
        update = generate_empty_lable_count(requests)
        status = update_task(annotation_id)
        socketio.emit('update', {'status': status, 'update': update})
        count_label_status.set()
        return

    try:
        if meta_data:
            status = update_task(annotation_id)
            socketio.emit('update', {
                'status': status,
                'update': {'node_count_by_label': meta_data['node_count_by_label'],
                           'edge_count_by_label': meta_data['edge_count_by_label']
                           }},
                          to=str(annotation_id))
            count_label_status.set()
            return

        label_count = db_instance.run_query(count_query)

        count_result = [{}, label_count[0]]
        graph_components = {"nodes": requests['nodes'],
                            "predicates": requests['predicates'],
                            "properties": False}
        response = db_instance.parse_and_serialize(
            count_result, schema_manager.schema, graph_components, 'count')
        

        storage_service.update(annotation_id,
                               {'node_count_by_label': response['node_count_by_label'],
                                'edge_count_by_label': response['edge_count_by_label'],
                                })
        
        status = update_task(annotation_id)

        socketio.emit('update', {
            'status': status,
            'update': {'node_count_by_label': response['node_count_by_label'],
                       'edge_count_by_label': response['edge_count_by_label']
                       }},
                      to=str(annotation_id))
        count_label_status.set()
    except Exception as e:
        status = update_task(annotation_id)

        update = generate_empty_lable_count()
        
        socketio.emit('update', {'status': status, 'update': update})
        count_label_status.set()
        logging.error(e)

def start_thread(annotation_id, args):
    all_status = args['all_status']
    find_query = args['query'][0]
    total_count_query = args['query'][1]
    label_count_query = args['query'][2]
    request = args['request']
    summary = args['summary']
    meta_data = args['meta_data']

    def send_annotation():
        time.sleep(0.1)
        try:
            generate_result(find_query, annotation_id, request, all_status['result_done'])
        except Exception as e:
                logging.error("Error processing request", e)
      
    def send_summary():
        time.sleep(0.1)
        try:
            generate_summary(annotation_id, request, all_status, summary)
        except Exception as e:
            logging.error("Error processing request", e)
    
    
    def send_total_count():
        time.sleep(0.1)
        try:
            generate_total_count(
                total_count_query, annotation_id, request, all_status['total_count_done'], meta_data)
        except Exception as e:
            logging.error("Error processing request", e)
    def send_label_count():
        time.sleep(0.1)
        try:
            generate_label_count(label_count_query, annotation_id, request, all_status['label_count_done'], meta_data)
        except Exception as e:
            logging.error("Error processing request", e)

    result_generator = threading.Thread(
        name='result_generator', target=send_annotation)
    result_generator.start()
    total_count_generator = threading.Thread(
        name='total_count_generator', target=send_total_count)
    total_count_generator.start()
    label_count_generator = threading.Thread(
        name='label_count_generator', target=send_label_count)
    label_count_generator.start()
    
    summary_generator = threading.Thread(
        name='summmary_generator', target=send_summary)
    summary_generator.start()
    
def handle_client_request(query, request, current_user_id, node_types):
    annotation_id = request.get('annotation_id', None)
    # check if annotation exist

    if annotation_id:
        existing_query = storage_service.get_user_query(
            annotation_id, str(current_user_id), query[0])
    else:
        existing_query = None
        
    #Event to track tasks
    result_done = threading.Event()
    total_count_done = threading.Event()
    label_count_done = threading.Event()

    if existing_query:
        title = existing_query.title
        summary = existing_query.summary
        annotation_id = existing_query.id
        meta_data = {
            "node_count": existing_query.node_count,
            "edge_count": existing_query.edge_count,
            "node_count_by_label": existing_query.node_count_by_label,
            "edge_count_by_label": existing_query.edge_count_by_label,
        }
        storage_service.update(
            annotation_id, {"statu": "PENDING", "updated_at": datetime.datetime.now()})
        reset_status(annotation_id)
        
        args = {'all_status': {'result_done': result_done, 'total_count_done': total_count_done,
                               'label_count_done': label_count_done}, 'query': query, 'request': request,
                'summary': summary, 'meta_data': meta_data}
        
        start_thread(annotation_id, args)
        return Response(
            json.dumps({"annotation_id": str(annotation_id)}),
            mimetype='application/json')
    elif annotation_id is None:
        title = llm.generate_title(query[0])
        annotation = {"current_user_id": str(current_user_id),
                      "query": query[0], "request": request,
                      "title": title, "node_types": node_types,
                      "status": "PENDING"}

        annotation_id = storage_service.save(annotation)

        args = {'all_status': {'result_done': result_done, 'total_count_done': total_count_done,
                               'label_count_done': label_count_done}, 'query': query, 'request': request,
                'summary': None, 'meta_data': None}
        start_thread(annotation_id, args)

        return Response(
            json.dumps({"annotation_id": str(annotation_id)}),
            mimetype='application/json')
    else:
        title = llm.generate_title(query[0])
        del request['annotation_id']
        # save the query and return the annotation
        annotation = {"query": query[0], "request": request,
                      "title": title, "node_types": node_types,
                      'status': 'PENDING', 'node_count': None, 
                      'edge_count': None, 'node_count_by_label': None,
                      'edge_count_by_label': None}

        storage_service.update(annotation_id, annotation)
        reset_task(annotation_id)

        args = {'all_status': {'result_done': result_done, 'total_count_done': total_count_done,
                               'label_count_done': label_count_done}, 'query': query, 'request': request,
                'summary': None, 'meta_data': None}
        
        start_thread(annotation_id, args)

        return Response(
            json.dumps({'annotation_id': str(annotation_id)}),
            mimetype='application/json'
        )


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
        # Validate the request data before processing
        node_map = validate_request(requests, schema_manager.schema, source)
        if node_map is None:
            return jsonify(
                {"error": "Invalid node_map returned by validate_request"}
            ), 400

        # convert id to appropriate format
        # convert id to appropriate format
        requests = db_instance.parse_id(requests)

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
                                         current_user_id, node_types)
        result = db_instance.run_query(result_query)

        graph_components = {
            "nodes": requests['nodes'], "predicates": requests['predicates'],
            'properties': properties}

        result_graph = db_instance.parse_and_serialize(
            result, schema_manager.schema,
            graph_components, result_type='graph')

        if source == 'hypothesis':
            response = {"nodes": result_graph['nodes']}
            formatted_response = json.dumps(response, indent=4)
            return Response(formatted_response, mimetype='application/json')

        total_count = db_instance.run_query(total_count_query)
        count_by_label = db_instance.run_query(count_by_label_query)

        count_result = [total_count[0], count_by_label[0]]

        meta_data = db_instance.parse_and_serialize(
            count_result, schema_manager.schema,
            graph_components, result_type='count')

        title = llm.generate_title(result_query)

        summary = llm.generate_summary(
            result_graph, requests) or 'Graph too big, could not summarize'

        answer = llm.generate_summary(result_graph, requests, question, False, summary)

        response = result_graph
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
                      "status": "COMPLETE"
                      }

        annotation_id = storage_service.save(annotation)
        redis_client.setex(str(annotation_id), EXP, json.dumps({'task': 4, 
                                'graph': {'nodes': response['nodes'], 'edges': response['edges']}}))
        response = {"annotation_id": str(
            annotation_id), "question": question, "answer": answer}
        formatted_response = json.dumps(response, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error processing query: {e}")
        return jsonify({"error": str(e)}), 500



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


            link = process_full_data(
                current_user_id=current_user_id, annotation_id=id)

            subject = 'Full Data'
            body = f'Hello {email}. click this link {link}\
            to download the full data you requested.'

            send_email(subject, [email], body)
        except Exception as e:
            logging.error(f"Error processing query: {e}")

    sender = threading.Thread(name='main_sender', target=send_full_data)
    sender.start()
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
    cursor = storage_service.get_all(str(current_user_id), page_number)

    if cursor is None:
        return jsonify('No value Found'), 200

    for document in cursor:
        return_value.append({
            'annotation_id': str(document['_id']),
            "request": document['request'],
            'title': document['title'],
            'node_count': document['node_count'],
            'edge_count': document['edge_count'],
            'node_types': document['node_types'],
            'status': document['status'],
            "created_at": document['created_at'].isoformat(),
            "updated_at": document["updated_at"].isoformat()
        })
    return Response(json.dumps(return_value, indent=4),
                    mimetype='application/json')


@app.route('/annotation/<id>', methods=['GET'])
@token_required
def get_by_id(current_user_id, id):
    response_data = {}
    cursor = storage_service.get_by_id(id)

    limit = request.args.get('limit')
    properties = request.args.get('properties')
    # can be either hypothesis or ai_assistant
    source = request.args.get('source')

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
            return jsonify(
                {"error": "Invalid limit value. It should be an integer."}
            ), 400
    else:
        limit = None

    try:
        if question:
            response_data["question"] = question

        if answer:
            response_data["answer"] = answer
            response_data["answer"] = answer

        if source == 'ai-assistant':
            response = {"annotation_id": str(
                annotation_id), "question": question, "answer": answer}
        if source == 'ai-assistant':
            response = {"annotation_id": str(
                annotation_id), "question": question, "answer": answer}
            formatted_response = json.dumps(response, indent=4)
            return Response(formatted_response, mimetype='application/json')
        
        
        cache = redis_client.get(str(annotation_id))

        if cache is not None:
            cache = json.loads(cache)
            graph = cache['graph']
            if graph is not None:
                response_data['nodes'] = graph['nodes']
                response_data['edges'] = graph['edges']
        if cache is None and status == 'COMPLETE':
            # Run the query and parse the results
            result = db_instance.run_query(query)
            graph_components = {"properties": properties}
            response_data = db_instance.parse_and_serialize(
                result, schema_manager.schema,
                graph_components, result_type='graph')
            graph = Graph()
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
        
        if len(response_data['nodes']) == 0:
            response = jsonify({"error": "No data found for the query"})
            response = Response(response.response, status=404)
            response.status = "404 No matching results for the query"
            return response


        response_data["annotation_id"] = str(annotation_id)
        response_data["request"] = json_request
        response_data["title"] = title
        
        if summary is not None:
            response_data["summary"] = summary
        if node_count is not None:
            response_data["node_count"] = node_count
            response_data["edge_count"] = edge_count
        if node_count_by_label is not None:
            response_data["node_count_by_label"] = node_count_by_label
            response_data["edge_count_by_label"] = edge_count_by_label
        response_data["status"] = status
        # if limit:
        # response_data = limit_graph(response_data, limit)

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error processing query: {e}")
        return jsonify({"error": str(e)}), 500



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
    cursor = storage_service.get_by_id(id)

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
            return jsonify(
                {"error": "Invalid limit value. It should be an integer."}
            ), 400
    else:
        limit = None

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
                result, schema_manager.schema, graph_components, result_type='graph')

        answer = llm.generate_summary(
            response_data, json_request, question, False, summary) if question else None

        storage_service.update(
            id, {"answer": answer, "updated_at": datetime.datetime.now()})


        response = {"annotation_id": str(
            id), "question": question, "answer": answer}

        formatted_response = json.dumps(response, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error processing query: {e}")
        return jsonify({"error": str(e)}), 500



@app.route('/annotation/<id>/full', methods=['GET'])
@token_required
def process_full_annotation(current_user_id, id):
    try:
        link = process_full_data(
            current_user_id=current_user_id, annotation_id=id)
        link = process_full_data(
            current_user_id=current_user_id, annotation_id=id)
        if link is None:
            return jsonify('No value Found'), 200

        response_data = {
            'link': link
        }

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error processing query: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/public/<file_name>')
def serve_file(file_name):
    public_folder = os.path.join(os.getcwd(), 'public')
    return send_from_directory(public_folder, file_name)



def process_full_data(current_user_id, annotation_id):
    cursor = storage_service.get_by_id(annotation_id)

    if cursor is None:
        return None


    query, title = cursor.query, cursor.title


    try:
        file_path = generate_file_path(
            file_name=title, user_id=current_user_id, extension='xls')
        file_path = generate_file_path(
            file_name=title, user_id=current_user_id, extension='xls')
        exists = os.path.exists(file_path)

        if exists:
            file_path = adjust_file_path(file_path)
            link = f'{request.host_url}{file_path}'

            return link


        # Run the query and parse the results
        result = db_instance.run_query(query)
        parsed_result = db_instance.convert_to_dict(
            result, schema_manager.schema)
        parsed_result = db_instance.convert_to_dict(
            result, schema_manager.schema)

        file_path = convert_to_csv(
            parsed_result, user_id=current_user_id, file_name=title)
        file_path = convert_to_csv(
            parsed_result, user_id=current_user_id, file_name=title)
        file_path = adjust_file_path(file_path)

        link = f'{request.host_url}{file_path}'
        return link

    except Exception as e:
        raise e
        raise e



@app.route('/annotation/<id>', methods=['DELETE'])
@token_required
def delete_by_id(current_user_id, id):
    try:
        existing_record = storage_service.get_by_id(id)

        if existing_record is None:
            return jsonify('No value Found'), 404


        deleted_record = storage_service.delete(id)

        if deleted_record is None:
            return jsonify('Failed to delete the annotation'), 500


        response_data = {
            'message': 'Annotation deleted successfully'
        }

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error deleting annotation: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/annotation/<id>/title', methods=['PUT'])
@token_required
def update_title(current_user_id, id):
    data = request.get_json()

    if 'title' not in data:
        return jsonify({"error": "Title is required"}), 400

    title = data['title']

    try:
        existing_record = storage_service.get_by_id(id)

        if existing_record is None:
            return jsonify('No value Found'), 404

        storage_service.update(id, {'title': title})

        response_data = {
            'message': 'title updated successfully',
            'title': title,
        }

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error updating title: {e}")
        return jsonify({"error": str(e)}), 500


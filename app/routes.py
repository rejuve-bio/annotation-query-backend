from flask import copy_current_request_context, request, jsonify, \
    Response, send_from_directory, send_file
import logging
import json
import os
import threading
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
from app.lib import Graph, heuristic_sort
from app.annotation_controller import handle_client_request, process_full_data, requery
from app.constants import TaskStatus
from app.workers.task_handler import get_annotation_redis
from app.persistence import AnnotationStorageService, UserStorageService
from app.lib import convert_to_excel

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
    return Response(relations, mimetype='application/json')

@app.route('/schema-list', methods=['GET'])
@token_required
def get_schema_list(current_user_id):
    schema_list = schema_manager.schema_list
    response = {
        "schemas": schema_list,
    }
    return Response(json.dumps(response, indent=4), mimetype='application/json')

@app.route('/schema', methods=['GET'])
@token_required
def get_schema_by_source(current_user_id):
    try:
        schema = schema_manager.schmea_representation

        response = {'nodes': [], 'edges': []}

        query_string = request.args.getlist("source")

        user = UserStorageService.get(current_user_id)


        if not user:
            query_string = 'all'
        else:
            query_string = user.data_source

        if query_string == 'all':
            response['nodes'] = schema['nodes']
            response['edges'] = schema['edges']

            return Response(json.dumps(response, indent=4), mimetype='application/json')

        for schema_type in query_string:
            source = schema_type.upper()
            sub_schema = schema.get(source, None)

            if sub_schema is None:
                return jsonify({"error": "Invalid schema source"}), 400

            for key, _ in sub_schema['edges'].items():
                edge = sub_schema['edges'][key]
                edge_data = {
                    "label": schema['edges'][key]['output_label'],
                    **edge
                }
                response['edges'].append(edge_data)
                response['nodes'].append(schema['nodes'][edge['source']])
                response['nodes'].append(schema['nodes'][edge['target']])

            if len(response['edges']) == 0:
                for node in sub_schema['nodes']:
                    response['nodes'].append(schema['nodes'][node])

        return Response(json.dumps(response, indent=4), mimetype='application/json')
    except Exception as e:
        logging.error(f"Error fetching schema: {e}")
        return jsonify({"error": str(e)}), 500

@socketio.on('connect')
@socket_token_required
def on_connect(current_user_id, args):
    logging.info("User connected")
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
        # Validate the request data before processing
        node_map = validate_request(requests, schema_manager.schema, source)
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

        graph = Graph()
        if len(result_graph['edges']) == 0:
            response = graph.group_node_only(result_graph)
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
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error processing query: {e}")
        return jsonify({"error": (e)}), 500


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
    cursor = AnnotationStorageService.get_all(str(current_user_id), page_number)

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

        if summary is not None:
            response_data["summary"] = summary
        if node_count is not None:
            response_data["node_count"] = node_count
            response_data["edge_count"] = edge_count
        if node_count_by_label is not None:
            response_data["node_count_by_label"] = node_count_by_label
            response_data["edge_count_by_label"] = edge_count_by_label
        response_data["status"] = status

        graph = Graph()

        cache = redis_client.get(str(annotation_id))

        if cache is not None:
            cache = json.loads(cache)
            graph_data = cache['graph']
            if graph_data is not None:
                nx_graph = graph.build_graph_nx(graph_data)

                graph_result = []

                sub_graph = graph.build_subgraph_nx(nx_graph)

                for single_graph in sub_graph:
                    graph_result.append(graph.convert_to_graph_json(single_graph))

                response_data["graph"] = graph_result

            return Response(json.dumps(response_data, indent=4), mimetype='application/json')

        if status in [TaskStatus.PENDING.value, TaskStatus.COMPLETE.value] and source is None:
            if status == TaskStatus.COMPLETE.value:
                if os.path.exists(file_path):
                    # open the file and read the graph
                    with open(file_path, 'r') as file:
                        graph = json.load(file)

                    response_data['graph'] = graph
                else:
                    response_data['status'] = TaskStatus.PENDING.value
                    requery(annotation_id, query, json_request)
            formatted_response = json.dumps(response_data, indent=4)
            return Response(formatted_response, mimetype='application/json')

        # Run the query and parse the results
        result = db_instance.run_query(query)
        graph_components = {"properties": properties}
        response_data = db_instance.parse_and_serialize(
            result, schema_manager.schema,
            graph_components, result_type='graph')
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

        if 'nodes' in response_data and len(response_data['nodes']) == 0:
            response = jsonify({"error": "No data found for the query"})
            response = Response(response.response, status=404)
            response.status = "404 No matching results for the query"
            return response

        graph_data = {}
        graph_data['nodes'] = response_data['nodes']
        graph_data['edges'] = response_data['edges']
        nx_graph = graph.build_graph_nx(graph_data)

        graph_result = []

        sub_graph = graph.build_subgraph_nx(nx_graph)

        for single_graph in sub_graph:
            graph_result.append(graph.convert_to_graph_json(single_graph))

        del response_data['nodes']
        del response_data['edges']
        response_data["graph"] = graph_result
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
                result, schema_manager.schema, graph_components, result_type='graph')

        response_data['node_count_by_label'] = node_count_by_label
        response_data['edge_count_by_label'] = edge_count_by_label

        answer = llm.generate_summary(
            response_data, json_request, question, False, summary) if question else None

        AnnotationStorageService.update(
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

@app.route('/annotation/<id>', methods=['DELETE'])
@token_required
def delete_by_id(current_user_id, id):
    try:
        # check if the user have access to delete the resource
        annotation = AnnotationStorageService.get_user_annotation(id, current_user_id)

        if annotation is None:
            return jsonify('No value Found'), 404

        # first check if there is any running running annoation
        with app.config['annotation_lock']:
            thread_event = app.config['annotation_threads']
            stop_event = thread_event.get(id, None)

            # if there is stop the running annoation
            if stop_event is not None:
                stop_event.set()

                response_data = {
                    'message': f'Annotation {id} has been cancelled.'
                }

                formatted_response = json.dumps(response_data, indent=4)
                return Response(formatted_response, mimetype='application/json')

        # else delete the annotation from the db
        existing_record = AnnotationStorageService.get_by_id(id)

        if existing_record is None:
            return jsonify('No value Found'), 404

        # deleted the stored file
        graph_file_path = existing_record.path_url
        os.remove(graph_file_path)

        deleted_record = AnnotationStorageService.delete(id)

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
        existing_record = AnnotationStorageService.get_by_id(id)

        if existing_record is None:
            return jsonify('No value Found'), 404

        AnnotationStorageService.update(id, {'title': title})

        response_data = {
            'message': 'title updated successfully',
            'title': title,
        }

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error updating title: {e}")
        return jsonify({"error": str(e)}), 500

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
        for annotation_id in annotation_ids:
            annotation = AnnotationStorageService.get_by_id(annotation_id)
            os.remove(annotation.path_url)

        delete_count = AnnotationStorageService.delete_many_by_id(annotation_ids)

        response_data = {
            'message': f'Out of {len(annotation_ids)}, {delete_count} were successfully deleted.'
        }

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error deleting annotations: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/settings/data-source', methods=['POST'])
@token_required
def update_settings(current_user_id):
    data = request.get_json()

    data_source = data.get('data_source', None)

    if data_source is None:
        return jsonify({"error": "Missing data source"}), 400

    if isinstance(data_source, str):
        if data_source.lower() == 'all':
            UserStorageService.upsert_by_user_id(current_user_id,
                                             {'data_source': 'all'})

            response_data = {
                'message': 'Data source updated successfully',
                'data_source': 'all'
            }
            formatted_response = json.dumps(response_data, indent=4)
            return Response(formatted_response, mimetype='application/json')
        else:
            return jsonify({"error": "Invalid data source format"}), 400

    # check if the data source is valid
    for ds in data_source:
        if ds.upper() not in schema_manager.schmea_representation:
            return jsonify({"error": f"Invalid data source: {ds}"}), 400

    try:
        UserStorageService.upsert_by_user_id(current_user_id,
                                         {'data_source': data_source})

        response_data = {
            'message': 'Data source updated successfully',
            'data_source': data_source
        }

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error updating data source: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/search", methods=["POST"])
@token_required
def search(current_user_id):
    data = request.get_json()

    node_type = data.get('node_type', None)
    search_text = data.get('search_text', None)

    if not node_type or not search_text:
        return jsonify({"error": "Missing node type or search text"}), 400

    try:
        node_property, property_value = next(iter(search_text.items()))

        search_payload = {
            'suggest': {
                'text-suggest': {
                    'prefix': property_value,
                    'completion': {
                        'field': node_property
                    }
                }
            }
        }

        es_client = app.config['es_db']

        response = es_client.search(index=node_type, body=search_payload)

        suggested_response = []

        suggestions = response.get('suggest', {}).get('text-suggest', [])[0]

        for suggestion in suggestions.get('options', []):
            suggested_response.append(suggestion['text'])

        return Response(json.dumps(suggested_response, indent=4), mimetype='application/json')
    except Exception as e:
        logging.error(f"Error processing search: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/annotation/<id>/download', methods=['GET'])
@token_required
def download_annotation(current_user_id, id):
    # response_data = {'nodes': [], 'edges': []}
    # get the query string from the request
    group_id = request.args.get('node_group_id')

    cursor = AnnotationStorageService.get_user_annotation(id, current_user_id)

    if cursor is None:
        return jsonify('No value Found'), 404

    file_path = cursor.path_url


    try:
        graphs = json.load(open(file_path))

        # add this after the subgraph data extraction have been merged
        response_data = {'nodes': [], 'edges': []}
        for graph in graphs:
            response_data['nodes'].extend(graph['nodes'])
            response_data['edges'].extend(graph['edges'])

        if group_id:
            nodes = response_data['nodes']

            for node in nodes:
                if node['data']['id'] == group_id:
                    response_data = {'nodes': [], 'edges': []}
                    nodes_data = node['data']['nodes']

                    for node_data in nodes_data:
                        data = {
                            'data': {
                                **node_data
                            }
                        }

                        response_data['nodes'].append(data)

        file_obj = convert_to_excel(response_data)

        if file_obj:
            return send_file(
                file_obj,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name='graph_export.xlsx'
            )
        else:
            return jsonify('Error generating the file'), 500
    except Exception as e:
        logging.error(f"Error processing query: {e}")
        return jsonify({"error": str(e)}), 500

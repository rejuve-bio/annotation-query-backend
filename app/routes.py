from flask import copy_current_request_context, request, jsonify, Response, send_from_directory
import neo4j 
import traceback
import asyncio
import re
import logging
import json
import yaml
import os
import threading
from app import app, databases, schema_manager, db_instance 
from app.lib import validate_request
from flask_cors import CORS
from app.lib import limit_graph
from app.lib.auth import token_required
from app.lib.email import init_mail, send_email
from dotenv import load_dotenv
from distutils.util import strtobool
import datetime
from app.lib import convert_to_csv
from app.lib import generate_file_path
from app.lib import adjust_file_path
from flask_socketio import join_room, leave_room,emit,send
import redis
from app.services.cypher_generator import CypherQueryGenerator
 
redis_client=redis.Redis(host='localhost',port=6379,db=0,decode_responses=True)
# Load environmental variables
load_dotenv()
# Set the allowed origin for WebSocket connections
 
def handle_message(auth):
    emit('my responce',{'data':"Connected"})
 
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

llm = app.config['llm_handler']
storage_service = app.config['storage_service']
annotation={}
# Initialize Flask-Mail
init_mail(app)

 

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
    relations = json.dumps(schema_manager.get_relations_for_node(node_label), indent=4)
    return Response(relations, mimetype='application/json')
 
# @socketio.on('join')
# def on_join(data):
#     username = data['username']
#     room = data['room']
#     join_room(room)  # Correctly join the room

# @socketio.on('leave')
# def on_leave(data):
#     username = data['username']
#     room = data['room']
#     leave_room(room)
@app.route('/query', methods=['POST'])
@token_required
def process_query(current_user_id):
    async def _process_query():
        try:
            data = request.get_json()
            if not data or 'requests' not in data:
                return jsonify({"error": "Missing requests data"}), 400
            
            requests = data['requests']
            annotation_id = requests.get('annotation_id', None)

            if annotation_id and annotation_id in redis_client:
                return jsonify(json.loads(redis_client[annotation_id])), 200

            limit = request.args.get('limit')
            properties = request.args.get('properties')
            source = request.args.get('source')

            properties = bool(strtobool(properties)) if properties else False
            limit = int(limit) if limit else None

            question = requests.get('question', None)
            node_map = validate_request(requests, schema_manager.schema)
            if node_map is None:
                return jsonify({"error": "Invalid node_map returned by validate_request"}), 400

            requests = db_instance.parse_id(requests)
            query_code = db_instance.query_Generator(requests, node_map, limit)
            result = db_instance.run_query(query_code, source)
            node_types = {node["type"] for node in requests.get('nodes', [])}

            if annotation_id:
                title = ''
            else:
                title = await llm.generate_title(query_code)
                annotation = {
                    "current_user_id": str(current_user_id),
                    "requests": requests,
                    "query": query_code,
                    "question": question,
                    "title": title,
                    "answer": "",
                    "summary": "",
                    "node_count": 0,
                    "edge_count": 0,
                    "node_count_by_label": 0,
                    "edge_count_by_label": 0,
                    "node_types": list(node_types)
                }
                annotation_id = "mock_annotation_id"  # Mock save operation

            await process_query_tasks(result, annotation_id, properties, question)
            return jsonify({"requests": requests, "annotation_id": str(annotation_id), "title": title})

        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # Run the async function and return the result
    return asyncio.run(_process_query())

async def process_query_tasks(result, annotation_id, properties, question):
    room = annotation_id
    count_by_label_value = result[2] if len(result) > 2 else []
    node_and_edge_count = result[1] if len(result) > 1 else []
    print("result",len(result))
    print("countand edges",count_by_label_value)
    print("node_and_edge_count",node_and_edge_count)
    matched_result=result[0]
    tasks = [
        asyncio.create_task(generate_graph(matched_result, properties)),
        asyncio.create_task(count_by_label(count_by_label_value, properties,  annotation_id)),
        asyncio.create_task(count_nodes_and_edges(node_and_edge_count, annotation_id))
    ]

    for task in asyncio.as_completed(tasks):
        result = await task
        print(f"Task completed with result {result}")

async def count_nodes_and_edges(node_and_edge_count, annotation_id):
    print("node and edge count ",node_and_edge_count)
    node_count, edge_count = CypherQueryGenerator.count_node_edges(node_and_edge_count)
    update_annotation = {"$set": {
        "node_count": node_count,
        "edge_count": edge_count,
        "updated_at": datetime.datetime.now()
    }}
    await storage_service.update(annotation_id, update_annotation)
    return node_count, edge_count

async def count_by_label(count_by_label_value, properties, annotation_id):
    node_count_by_label, edge_count_by_label = CypherQueryGenerator.count_by_label(count_by_label_value, properties)
    update_annotation = {"$set": {
        "node_count_by_label": node_count_by_label,
        "edge_count_by_label": edge_count_by_label,
        "updated_at": datetime.datetime.now()
    }}
    await storage_service.update(annotation_id, update_annotation)
    return node_count_by_label, edge_count_by_label

async def generate_graph(requests, properties):
    request_data = CypherQueryGenerator.graph_result_nodes(requests, properties)
    return request_data
     
 
 



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
            'title': document['title'],
            'node_count': document['node_count'],
            'edge_count': document['edge_count'],
            'node_types': document['node_types'],
            "created_at": document['created_at'].isoformat(),
            "updated_at": document["updated_at"].isoformat()
        })
    return Response(json.dumps(return_value, indent=4), mimetype='application/json')

@app.route('/annotation/<id>', methods=['GET'])
@token_required
def process_by_id(current_user_id, id):
    cursor = storage_service.get_by_id(id)

    if cursor is None:
        return jsonify('No value Found'), 200
    query = cursor.query
    title = cursor.title
    summary = cursor.summary
    annotation_id = cursor.id
    question = cursor.question
    answer = cursor.answer
    node_count = cursor.node_count
    edge_count = cursor.edge_count

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
       
        query=query.replace("{PLACEHOLDER}",str(limit)) 
       
        # Run the query and parse the results
        result = db_instance.run_query(query)
      
        response_data = db_instance.parse_and_serialize(result, schema_manager.schema, properties)
        
        response_data["annotation_id"] = str(annotation_id)
        response_data["title"] = title
        response_data["summary"] = summary
        response_data["node_count"] = node_count
        response_data["edge_count"] = edge_count

        if question:
            response_data["question"] = question

        if answer:
            response_data["answer"] = answer

        # if limit:
            # response_data = limit_graph(response_data, limit)

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error processing query: {e}")
        return jsonify({"error": str(e)}), 500
    




@app.route('/annotation/<id>/full', methods=['GET'])
@token_required
def process_full_annotation(current_user_id, id):
    try:
        link = process_full_data(current_user_id=current_user_id, annotation_id=id)
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
    #remove the limit 
    import re
    if "LIMIT" in query:
        query = re.sub(r'\s+LIMIT\s+\d+', '', query)
     

     
    
    try:
        file_path = generate_file_path(file_name=title, user_id=current_user_id, extension='xls')
        exists = os.path.exists(file_path)

        if exists:
            file_path = adjust_file_path(file_path)
            link = f'{request.host_url}{file_path}'

            return link
        
        # Run the query and parse the results
        # query code inputs 2 value so source=None
        result = db_instance.run_query(query,source=None)
        print("step2 ")
        parsed_result = db_instance.convert_to_dict(result, schema_manager.schema)

        file_path = convert_to_csv(parsed_result, user_id= current_user_id, file_name=title)
        file_path = adjust_file_path(file_path)


        link = f'{request.host_url}{file_path}'
        return link

    except Exception as e:
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

        updated_data = storage_service.update(id,{'title': title})
        
        response_data = {
            'message': 'title updated successfully',
            'title': title,
        }

        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        logging.error(f"Error updating title: {e}")
        return jsonify({"error": str(e)}), 500
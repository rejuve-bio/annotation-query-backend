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
from app import app, databases, schema_manager, db_instance,socketio
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
from flask_socketio import send,emit,join_room,leave_room
import redis
from app.services.cypher_generator import CypherQueryGenerator
 
redis_client=redis.Redis(host='localhost',port=6379,db=0,decode_responses=True)
# Load environmental variables
load_dotenv()
# Set the allowed origin for WebSocket connections
@socketio.on('connect')
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
    relations = json.dumps(schema_manager.get_relations_for_node(node_label), indent=4)
    return Response(relations, mimetype='application/json')
 
@socketio.on('join')
def on_join(data):
    room=data['room']
    join_room(room)
    
     


@socketio.on('leave')
def on_leave(data):
    username = data['username']
    room = data['room']
    leave_room(room)
    send(f"{username} has left the room.", to=room)
@app.route('/query', methods=['POST'])
@token_required
def process_query(current_user_id):
    try:
        # Get request data safely
        data = request.get_json()
        if not data or 'requests' not in data:
            return jsonify({"error": "Missing requests data"}), 400
        
        requests = data['requests']
        annotation_id = requests.get('annotation_id', None)

        # Try fetching cached data from Redis
        if annotation_id:
            cached_data = redis_client.get(annotation_id)
            if cached_data:
                return jsonify(json.loads(cached_data)), 200
        
        print("Checkpoint: Passed Redis Cache Check")

        # Extract query parameters
        limit = request.args.get('limit')
        properties = request.args.get('properties')
        source = request.args.get('source')  # Either 'hypothesis' or 'ai_assistant'

        properties = bool(strtobool(properties)) if properties else False

        if limit:
            try:
                limit = int(limit)
            except ValueError:
                return jsonify({"error": "Invalid limit value. It should be an integer."}), 400
        else:
            limit = None

        print("Checkpoint: Extracted Parameters Successfully")

        # Extract required fields
        question = requests.get('question', None)

        # Validate the request data before processing
        node_map = validate_request(requests, schema_manager.schema)
        if node_map is None:
            return jsonify({"error": "Invalid node_map returned by validate_request"}), 400
        
        print("Checkpoint: Request Validation Successful")

        # Convert ID formats
        requests = db_instance.parse_id(requests)

        # Generate the query code
        query_code = db_instance.query_Generator(requests, node_map, limit)

        print("Checkpoint: Query Code Generated Successfully")

        # Extract node types
        node_types = {node["type"] for node in requests.get('nodes', [])}
        node_types = list(node_types)

        print("Checkpoint: Extracted Node Types Successfully")

        if isinstance(query_code, list):
            query_code = query_code[0]

        # Handling annotation storage
        if annotation_id:
            print(f"Using existing annotation_id: {annotation_id}")
            existing_query = storage_service.get_user_query(annotation_id, str(current_user_id), query_code)
        else:
            title = llm.generate_title(query_code)
            annotation = {
                "current_user_id": str(current_user_id),
                "requests": requests,
                "query": query_code,
                "question": question,
                "title": title,
                "answer":"",
                "summary": "",
                "node_count": 0,
                "edge_count": 0,
                "node_count_by_label": 0,
                "edge_count_by_label": 0,
                "node_types":""
            }
            annotation_id = storage_service.save(annotation)
        
        print("Checkpoint: Annotation Handling Completed")

        # Run async processing correctly
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(process_query(requests, annotation_id, properties, question, annotation))

        result = {"message": "Query processed successfully"}
        return jsonify(result)

    except Exception as e:
        print("Error occurred in process_query:")
        traceback.print_exc()  # Prints the full error traceback

        return jsonify({"error": str(e)}), 500
        
 
 
 

async def process_query(requests, annotation_id, properties, question, annotation):
    print("Processing query...")

    room = annotation_id 
     
     

    try:
        print("outside________")
        count_by_label = requests[2] if len(requests) > 1 else []
        node_and_edge_count = requests[1] if len(requests) > 2 else []
        print("outside_______________")

        # Run graph and count_by_label concurrently with error handling
        try:
            print("grpah ______________________")
            graph_task = generate_graph(requests[0], properties, annotation_id, annotation,room)
            print("grpah ______________________")
            count_task_label = count_by_label(count_by_label, properties, annotation, annotation_id,room)
            print("______________")
            count_nodes = count_nodes_and_edges(node_and_edge_count, annotation, annotation_id,room)
            print("______________")
            graph_result, count_result, count_nodes_result = await asyncio.gather(
                graph_task, count_task_label, count_nodes, return_exceptions=True
            )

            if isinstance(graph_result, Exception):
                print(f"Error in generate_graph: {graph_result}")
                graph_result = "Graph generation failed."

            if isinstance(count_result, Exception):
                print(f"Error in count_by_label: {count_result}")
                count_result = "Label counting failed."

            if isinstance(count_nodes_result, Exception):
                print(f"Error in count_nodes_and_edges: {count_nodes_result}")
                count_nodes_result = "Node and edge counting failed."

        except Exception as e:
            print(f"Error during concurrent execution: {e}")
            socketio.emit("error_event", {"message": "Error processing query"}, room=room)
            return  # Stop execution if core tasks fail

        print("Processed query successfully.")

        # Send results to client
        socketio.emit("update_event", {"message": graph_result}, room=room)
        socketio.emit("update_event", {"message": count_result}, room=room)
        socketio.emit("update_event", {"message": count_nodes_result}, room=room)

        # Run summary after the previous tasks finish
        try:
            summary_result = await generate_summary(annotation, question, graph_task, count_task_label, request,room)
            socketio.emit("update_event", {"message": summary_result}, room=room)
        except Exception as e:
            print(f"Error in generate_summary: {e}")
            socketio.emit("error_event", {"message": "Error generating summary"}, room=room)

        print("Processing query completed.")

    except Exception as e:
        print(f"Unexpected error in process_query: {e}")
        socketio.emit("error_event", {"message": "An unexpected error occurred"}, room=room)

    finally:
        # Ensure socket room is cleaned up
        leave_room(room)
        socketio.emit("close_socket", {"message": "All tasks completed"}, room=room)
  



async def count_nodes_and_edges(node_and_edge_count, annotation,annotation_id,room):
        
        node_count,edge_count=CypherQueryGenerator.count_node_edges( node_and_edge_count)
        update_annotation = {
            "node_count": node_count,
            "edge_count": edge_count,
            "updated_at": datetime.datetime.now()
        }

        await storage_service.update(annotation["_id"], update_annotation)
        socketio.emit("summary_update", {"status": "pending", "summary": update_annotation},to=room)

     
 

 


async def count_by_label(count_by_label, properties, annotation,annotation_id,room):
        node_count_by_label, edge_count_by_label=CypherQueryGenerator.count_by_label( count_by_label,properties)
        update_annotation = {
            "node_count_by_label": node_count_by_label,
            "edge_count_by_label": edge_count_by_label,
            "updated_at": datetime.datetime.now()
        }

        await storage_service.update(annotation["_id"], update_annotation)
        socketio.emit("update-event", {"status": "pending", "summary": update_annotation},to=room)

     


 

async def generate_graph(requests, properties, annotation_id,annotation,room):
    request_data=CypherQueryGenerator.graph_result_nodes(requests[0], properties)
    # await redis_client.setex(annotation_id, 3600, json.dumps(responce_data, indent=4))
    socketio.emit("update-event", {"status": "pending", "graph": True})
    
     
 
async def generate_summary(annotation, question,graph_task,count_task_label,request,room):
    """Generates a summary asynchronously."""
    if not graph_task.get('nodes') and not graph_task.get('edges'):
                summary = 'No data found for the query'
    else:
        summary = await llm.generate_summary(graph_task,request) or "Graph too big to summarize"
    answer = await llm.generate_summary(graph_task, request, question, False, summary) if question else None

    update_annotation = {"summary": summary, "updated_at": datetime.datetime.now()}
    await storage_service.update(annotation["_id"], update_annotation)

    # Emit WebSocket update
    socketio.emit("update_event", {"status": "pending", "summary": summary},to=room)
    return answer


 



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
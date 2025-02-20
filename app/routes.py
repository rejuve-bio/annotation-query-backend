from flask import copy_current_request_context, request, jsonify, Response, send_from_directory
import neo4j 
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
from flask_socketio import SocketIO
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
    username = data['username']
    room = data['room']
    join_room(room)
    send(f"{username} has joined the room.", to=room)


@socketio.on('leave')
def on_leave(data):
    username = data['username']
    room = data['room']
    leave_room(room)
    send(f"{username} has left the room.", to=room)
@app.route('/query', methods=['POST'])
@token_required
def process_query(current_user_id):
    data = request.get_json()
    requests = data['requests']
    if 'annotation_id' in requests:
            annotation_id = requests['annotation_id'] 
    cached_data=redis_client.get(annotation_id)
     
    if cached_data:
        return jsonify(json.loads(cached_data)),200
    if not data or 'requests' not in data:
        return jsonify({"error": "Missing requests data"}), 400
    
    limit = request.args.get('limit')
    properties = request.args.get('properties')
    source = request.args.get('source') # can be either hypotehesis or ai_assistant
    
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
        annotation_id = None
        question = None
        answer = None

        
        if 'annotation_id' in requests:
            annotation_id = requests['annotation_id'] 
        
        if 'question' in requests:
            question = requests['question']

        # Validate the request data before processing
        node_map = validate_request(requests, schema_manager.schema)
        if node_map is None:
            return jsonify({"error": "Invalid node_map returned by validate_request"}), 400

        #convert id to appropriate format
        requests = db_instance.parse_id(requests)

        # Generate the query code
        query_code = db_instance.query_Generator(requests, node_map, limit)
        
        # Run the query and parse the results
        result = db_instance.run_query(query_code, source)
        response_data = db_instance.parse_and_serialize(result, schema_manager.schema, properties)

        # Extract node types
        nodes = requests['nodes']
        node_types = set()

        for node in nodes:
            node_types.add(node["type"])

        node_types = list(node_types)

        if isinstance(query_code, list):
            query_code = query_code[0]

        if source == 'hypotehesis':
            response = {"nodes": response_data['nodes'], "edges": response_data['edges']}
            formatted_response = json.dumps(response, indent=4)
            return Response(formatted_response, mimetype='application/json')

        if annotation_id:
            existing_query = storage_service.get_user_query(annotation_id, str(current_user_id), query_code)
        else:
            existing_query = None

        if existing_query is None:
            
            title = llm.generate_title(query_code)
            annotation = {"current_user_id": str(current_user_id), "requests": requests, "query": query_code,
                      "question": question, "title": title, "summary": "", "node_count": "",
                      "edge_count": "", "node_count_by_label": "", "edge_count_by_label": ""}
            annotation_id=storage_service.save(annotation)


             
             
        
        
       
        socketio.start_background_task(run_async_tasks,annotation_id,annotation,question)

        

         
    

    
async def run_async_tasks(annotation_id,annotation,question):
    try:
        result=await asyncio.gather(
            generate_graph(results, graph_components, annotation_id,annotation,question,request),
            count_nodes_and_edges(annotation),
            count_by_label(annotation),
            generate_summary(annotation,question)
        )
        socketio.emit("summary_update", {"status": "complete", "annotation_id": annotation_id})

    except Exception as e:
        socketio.emit("summary_update", {"status": "error", "error": str(e)})
async def count_nodes_and_edges(results, annotation):
    node_count = 0
    edge_count = 0

    if len(results) > 1:
        node_and_edge_count = results[1]
        for count_record in node_and_edge_count:
            node_count += count_record.get('total_nodes', 0)
            edge_count += count_record.get('total_edges', 0)

        update_annotation = {
            "node_count": node_count,
            "edge_count": edge_count,
            "updated_at": datetime.datetime.now()
        }

        await storage_service.update(annotation["_id"], update_annotation)
        socketio.emit("summary_update", {"status": "pending", "summary": update_annotation})

    return {"node_count": node_count, "edge_count": edge_count}

 


##############


async def count_by_label(results, graph_components, annotation):
    node_count_by_label = []
    edge_count_by_label = []

    if len(results) > 2:
        count_by_label = results[2]

        node_count_aggregate = {node['type']: {'count': 0} for node in graph_components['nodes']}
        edge_count_aggregate = {predicate['type'].replace(" ", "_").lower(): {'count': 0} for predicate in graph_components['predicates']}

        for count_record in count_by_label:
            for key, value in count_record.items():
                node_type_key = '_'.join(key.split('_')[1:])
                if node_type_key in node_count_aggregate:
                    node_count_aggregate[node_type_key]['count'] += value

            for key, value in count_record.items():
                edge_type_key = '_'.join(key.split('_')[1:])
                if edge_type_key in edge_count_aggregate:
                    edge_count_aggregate[edge_type_key]['count'] += value

        node_count_by_label = [{'label': key, 'count': value['count']} for key, value in node_count_aggregate.items()]
        edge_count_by_label = [{'label': key, 'count': value['count']} for key, value in edge_count_aggregate.items()]

        update_annotation = {
            "node_count_by_label": node_count_by_label,
            "edge_count_by_label": edge_count_by_label,
            "updated_at": datetime.datetime.now()
        }

        await storage_service.update(annotation["_id"], update_annotation)
        socketio.emit("summary_update", {"status": "pending", "summary": update_annotation})

    return {"node_count_by_label": node_count_by_label, "edge_count_by_label": edge_count_by_label}


 

async def generate_graph(results, graph_components, annotation_id,annotation,question,request):
    match_result = results[0]
    nodes = []
    edges = []
    node_dict = {}
    node_to_dict = {}
    edge_to_dict = {}
    node_type = set()
    edge_type = set()
    visited_relations = set()
    named_types = ['gene_name', 'transcript_name', 'protein_name', 'pathway_name', 'term_name']

    for record in match_result:
        for item in record.values():
            if isinstance(item, neo4j.graph.Node):
                node_id = f"{list(item.labels)[0]} {item['id']}"
                if node_id not in node_dict:
                    node_data = {
                        "data": {
                            "id": node_id,
                            "type": list(item.labels)[0],
                        }
                    }

                    for key, value in item.items():
                        if graph_components['properties']:
                            if key != "id" and key != "synonyms":
                                node_data["data"][key] = value
                        else:
                            if key in named_types:
                                node_data["data"]["name"] = value
                    if "name" not in node_data["data"]:
                        node_data["data"]["name"] = node_id

                    nodes.append(node_data)
                    node_type.add(node_data["data"]["type"])
                    node_to_dict.setdefault(node_data["data"]["type"], []).append(node_data)
                    node_dict[node_id] = node_data

            elif isinstance(item, neo4j.graph.Relationship):
                source_label = list(item.start_node.labels)[0]
                target_label = list(item.end_node.labels)[0]
                source_id = f"{source_label} {item.start_node['id']}"
                target_id = f"{target_label} {item.end_node['id']}"
                edge_data = {
                    "data": {
                        "edge_id": f"{source_label}_{item.type}_{target_label}",
                        "label": item.type,
                        "source": source_id,
                        "target": target_id,
                    }
                }
                temp_relation_id = f"{source_id} - {item.type} - {target_id}"
                if temp_relation_id in visited_relations:
                    continue
                visited_relations.add(temp_relation_id)

                for key, value in item.items():
                    if key == 'source':
                        edge_data["data"]["source_data"] = value
                    else:
                        edge_data["data"][key] = value

                edges.append(edge_data)
                edge_type.add(edge_data["data"]["label"])
                edge_to_dict.setdefault(edge_data["data"]["label"], []).append(edge_data)
    responce_data={"nodes": nodes, "edges": edges}
    await redis_client.setex(annotation_id, 3600, json.dumps(responce_data, indent=4))
    socketio.emit("graph_update", {"status": "pending", "graph": True})
    generate_summary(annotation, question,responce_data,request)
    return nodes, edges 
 
async def generate_summary(annotation, question,response_data,request):
    """Generates a summary asynchronously."""
    if not response_data.get('nodes') and not response_data.get('edges'):
                summary = 'No data found for the query'
    else:
        summary = await llm.generate_summary(response_data,request) or "Graph too big to summarize"
    answer = await llm.generate_summary(response_data, request, question, False, summary) if question else None

    update_annotation = {"summary": summary, "updated_at": datetime.datetime.now()}
    await storage_service.update(annotation["_id"], update_annotation)

    # Emit WebSocket update
    socketio.emit("summary_update", {"status": "pending", "summary": summary})
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
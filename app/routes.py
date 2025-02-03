from flask import copy_current_request_context, request, jsonify, Response, send_from_directory
from collections import defaultdict
import uuid
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
import json
 
# Load environmental variables
load_dotenv()
# Set the allowed origin for WebSocket connections

 
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
    @socketio.on('connect')
    def handle_message(auth):
        emit('my responce',{'data':"Connected"})
    logging.info(f"\n\nWebSocket connected for query\n\n")
    data = request.get_json()
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

            if not response_data.get('nodes') and not response_data.get('edges'):
                summary = 'No data found for the query'
            else:
                def summarizer_thread():
                    room = requests.get('room')
                    message = data.get('message')
                    
                        # Broadcast message to the specific room
                    socketio.emit('message', f"{data.get('username')}: {message}", to=room)

                        # Example summarization logic (assuming response_data contains the text for summarization)
                 
                    summary = llm.generate_summary(response_data,data) or 'Graph too big, could not summarize'
                        
                    print("******************************* Summary Generated **********************************************")
                        
                        # Send the summary to the room
             
                    socketio.emit('summary', {'summary': summary})
                    print("******************************* Summary Sent to Room *********************************************")
                                    
                sender = threading.Thread(name="summarizer_thread", target=summarizer_thread)
                sender.start()
            answer = llm.generate_summary(response_data, question, True, summary) if question else None
            node_count = response_data['node_count']
            edge_count = response_data['edge_count'] if "edge_count" in response_data else 0
            node_count_by_label = response_data['node_count_by_label']
            edge_count_by_label = response_data['edge_count_by_label'] if "edge_count_by_label" in response_data else []
            if annotation_id is not None:
                annotation = {"query": query_code, "summary": summary, "node_count": node_count, 
                              "edge_count": edge_count, "node_types": node_types, "node_count_by_label": node_count_by_label,
                              "edge_count_by_label": edge_count_by_label, "updated_at": datetime.datetime.now()}
                storage_service.update(annotation_id, annotation)
            else:
                annotation = {"current_user_id": str(current_user_id), "query": query_code,
                              "question": question, "answer": answer,
                              "title": title, "summary": "", "node_count": node_count,
                              "edge_count": edge_count, "node_types": node_types, 
                              "node_count_by_label": node_count_by_label, "edge_count_by_label": edge_count_by_label}
                annotation_id = storage_service.save(annotation)
        else:
            title, summary, annotation_id = '', '', ''

        if existing_query:
            title = existing_query.title
            summary = existing_query.summary
            annotation_id = existing_query.id
            storage_service.update(annotation_id, {"updated_at": datetime.datetime.now()})

        
        updated_data = storage_service.get_by_id(annotation_id)

        response_data["title"] = title
        
        response_data["annotation_id"] = str(annotation_id)
        response_data["created_at"] = updated_data.created_at.isoformat()
        response_data["updated_at"] = updated_data.updated_at.isoformat()

        if question:
            response_data["question"] = question

        if answer:
            response_data["answer"] = answer

        if source=='ai-assistant':
            response = {"annotation_id": str(annotation_id), "question": question, "answer": answer}
            formatted_response = json.dumps(response, indent=4)
             
            return Response(formatted_response, mimetype='application/json')

        # if limit:
        #     response_data = limit_graph(response_data, limit)
        requesut=request.get_json()
        formatted_response = json.dumps(response_data, indent=4)
        final_graph=group_graph(formatted_response,requesut)
        final_graph=json.dumps(final_graph)
        response = {
        "final_graph": json.loads(final_graph),  # Optionally, parse back to ensure correct structure
        
        "title":title,
        
        "annotation_id" :str(annotation_id),
        "created_at":updated_data.created_at.isoformat(),
        "updated_at":updated_data.updated_at.isoformat()
    }   
     
        logging.info(f"\n\n============== Query ==============\n\n{query_code}")
        return jsonify(response), 200
        
         
 
    except Exception as e:
        logging.error(f"Error processing query: {e}")
        return jsonify({"error": str(e)}), 500
def group_graph(result_graph, request):
    
    MINIMUM_EDGES_TO_COLLAPSE = 2
     
    result_graph=json.loads(result_graph)
     
    Edge=result_graph['edges']
     
    # Get all unique edge types
    edge_types = list(set(edge["type"] for edge in request['requests']["predicates"]))

    print("step2 _________________________________________")
    # Group edges by source or target for each edge type
    edge_groupings = []
    for edge_type in edge_types:
        # Filter edges of this type
        
        edges_of_type = [edge for edge  in Edge if edge["data"]["label"] == edge_type]
        print("step3 _________________________________________")
        # Group by source and target
        source_groups = defaultdict(list)
        target_groups = defaultdict(list)
        for edge in edges_of_type:
            source_groups[edge["data"]["source"]].append(edge)
            target_groups[edge["data"]["target"]].append(edge)

        # Choose grouping with fewer groups
        grouped_by = "source" if len(source_groups) <= len(target_groups) else "target"
        groups = source_groups if grouped_by == "source" else target_groups
        print("step4 _________________________________________")
        # Save grouping info
        edge_groupings.append({
            "count": len(edges_of_type),
            "edgeType": edge_type,
            "groupedBy": grouped_by,
            "groups": groups,
        })

    # Sort edge groupings to process the most impactful ones first
    edge_groupings.sort(key=lambda g: g["count"] - len(g["groups"]), reverse=True)
    print("step 5_________________________________________")
    # Process each edge grouping to modify the graph
    new_graph = result_graph.copy()
    for grouping in edge_groupings:
        sorted_groups = sorted(grouping["groups"].items(), key=lambda x: len(x[1]), reverse=True)
        for key, edges in sorted_groups:
            if len(edges) < MINIMUM_EDGES_TO_COLLAPSE:
                continue
            print("step6 _________________________________________")
            # Get IDs of nodes to be grouped
            child_node_ids = [
                edge["data"]["source"] if grouping["groupedBy"] == "target" else edge["data"]["target"]
                for edge in edges
            ]

            # Filter child nodes
            child_nodes = [node for node in new_graph["nodes"] if node["data"]["id"] in child_node_ids]
            unique_parents = list({node["data"].get("parent") for node in child_nodes if "parent" in node["data"]})

            if len(unique_parents) > 1:
                continue  # Skip if nodes have different parents

            # Check if the parent has the same child nodes
            if unique_parents:
                parent_id = unique_parents[0]
                all_child_nodes = [
                    node for node in new_graph["nodes"]
                    if node["data"].get("parent") == parent_id
                ]
                if len(all_child_nodes) == len(child_nodes):
                    add_new_edge(new_graph, edges[0], parent_id, grouping["groupedBy"])
                    continue
            print("step7 _________________________________________")
            # Create a new parent node
            parent_id = f"n{uuid.uuid4().hex[:8]}"
            parent_node = {"data": {"id": parent_id, "type": "parent"}}
            new_graph["nodes"].append(parent_node)

            # Assign parent to child nodes
            for node in new_graph["nodes"]:
                if node["data"]["id"] in child_node_ids:
                    node["data"]["parent"] = parent_id

            # Add a new edge pointing to the parent node
            add_new_edge(new_graph, edges[0], parent_id, grouping["groupedBy"])
            print("step8 _________________________________________")
    print("new_graph",new_graph)
    return new_graph


def add_new_edge(graph, edge, parent_id, grouped_by):
    new_edge_id = f"e{uuid.uuid4().hex[:8]}"
    new_edge = {
        "data": {
            **edge["data"],
            "id": new_edge_id,
            grouped_by: parent_id,
        }
    }
    graph["edges"] = [
        new_edge
    ] + [e for e in graph["edges"] if e != edge]

 

     
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
from fastapi import APIRouter, Depends, HTTPException, Body, status, Query as FQuery
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional, List
import json
import datetime
import logging
from distutils.util import strtobool
import os
from app.api.deps import get_current_user, get_db_instance, get_llm_handler, get_redis_client, get_schema_manager
from app.api.deps import LLMHandler
from app.services.schema_data import SchemaManager
from app.persistence import AnnotationStorageService, UserStorageService, SharedAnnotationStorageService
from app.constants import TaskStatus
from app.lib import validate_request, heuristic_sort, Graph
from app.annotation_controller import handle_client_request
from pathlib import Path
from nanoid import generate
from app.workers.celery_app import redis_state
from app.annotation_controller import process_full_data
from app.lib.email import send_email
import threading
from app.core.config import settings
from app.api.deps import oauth2_scheme
import jwt

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/query")
def process_query(
    data: Dict[str, Any] = Body(...),
    limit: Optional[int] = FQuery(None),
    properties: Optional[str] = FQuery(None), # strtobool handling
    source: Optional[str] = FQuery(None),
    current_user_id: str = Depends(get_current_user),
    db_instance = Depends(get_db_instance),
    llm: LLMHandler = Depends(get_llm_handler),
    redis_client = Depends(get_redis_client),
    schema_manager: SchemaManager = Depends(get_schema_manager)
):
    if 'requests' not in data:
        raise HTTPException(status_code=400, detail="Missing requests data")

    # Handling boolean query param manually or via Pydantic if defined properly
    prop_bool = True
    if properties:
        try:
             prop_bool = bool(strtobool(properties))
        except:
             pass

    try:
        requests = data['requests']
        question = requests.get('question', None)
        answer = None
        
        # Access Check Logic
        annotation_id = requests.get('annotation_id', None)
        if annotation_id:
            existing_annotation = AnnotationStorageService.get_by_id(annotation_id)
            if existing_annotation:
                owner_id = existing_annotation.user_id
                shared_annotation = SharedAnnotationStorageService.get({
                    'user_id': owner_id,
                    'annotation_id': annotation_id
                })
    
                if shared_annotation is None:
                    if str(owner_id) != str(current_user_id):
                        raise HTTPException(status_code=401, detail="Unauthorized")
                else:
                    role = shared_annotation.role
                    share_type = shared_annotation.share_type
                    recipient_user_id = shared_annotation.recipient_user_id
    
                    if share_type == "public":
                        if role not in ["editor", "owner"]:
                            raise HTTPException(status_code=401, detail="Unauthorized")
                    elif share_type == "private":
                         if role not in ["editor", "owner"] or str(recipient_user_id) != str(current_user_id):
                            raise HTTPException(status_code=401, detail="Unauthorized")
                    
                    # If shared and authorized, we might operate as owner
                    current_user_id = str(owner_id)

        # Validate request
        user = UserStorageService.get(current_user_id)
        data_source = user.data_source if user else 'all'
        species = user.species if user else 'human'
        
        # schema for validation
        schema_for_species = schema_manager.schema.get(species, {})
        node_map = validate_request(requests, schema_for_species, source)
        if node_map is None:
             raise HTTPException(status_code=400, detail="Invalid node_map returned by validate_request")

        # Parse ID
        requests = db_instance.parse_id(requests)
        # Sort
        requests = heuristic_sort(requests, node_map)
        
        node_only = True if source == 'hypothesis' else False

        # Generate Query
        query = db_instance.query_Generator(requests, node_map, limit, node_only)
        result_query = query[0]
        total_count_query = query[1]
        count_by_label_query = query[2]
        
        # Node Types
        nodes = requests.get('nodes', [])
        node_types = list(set(node["type"] for node in nodes))

        if source is None:

            response = handle_client_request(query, requests, current_user_id, node_types, species, data_source, node_map)
            return response

        result = db_instance.run_query(result_query)
        graph_components = {
            "nodes": requests.get('nodes', []), 
            "predicates": requests.get('predicates', []),
            'properties': prop_bool}

        result_graph = db_instance.parse_and_serialize(
            result, schema_manager.full_schema_representation,
            graph_components, result_type='graph')

        if source == 'hypothesis':
            return {"nodes": result_graph.get('nodes', [])}

        total_count = db_instance.run_query(total_count_query)
        count_by_label = db_instance.run_query(count_by_label_query)
        count_result = [total_count[0], count_by_label[0]]
        
        meta_data = db_instance.parse_and_serialize(
            count_result, schema_manager.full_schema_representation,
            graph_components, result_type='count')

        title = llm.generate_title(result_query, requests, node_map)
        summary = llm.generate_summary(result_graph, requests) or 'Graph too big, could not summarize'
        answer = llm.generate_summary(result_graph, requests, question, False, summary)
        
        graph = Graph()
        if len(result_graph['edges']) == 0:
            response_grouped = graph.group_node_only(result_graph, requests)
        else:
            response_grouped = graph.group_graph(result_graph)
        
        annotation = {
            "current_user_id": str(current_user_id),
            "request": requests,
            "query": result_query,
            "title": title,
            "summary": summary,
            "node_count": meta_data['node_count'],
            "edge_count": meta_data['edge_count'],
            "node_types": node_types,
            "node_count_by_label": meta_data['node_count_by_label'],
            "edge_count_by_label": meta_data['edge_count_by_label'],
            "answer": answer, 
            "question": question,
            "status": TaskStatus.COMPLETE.value
        }
        
        annotation_id = AnnotationStorageService.save(annotation)
        
        EXP = 3600
        redis_client.setex(str(annotation_id), EXP, json.dumps({
            'task': 4,
            'graph': {'nodes': response_grouped['nodes'], 'edges': response_grouped['edges']}
        }))
        
        response = {
            "annotation_id": str(annotation_id), 
            "question": question, 
            "answer": answer
        }
        return response

    except Exception as e:
        logger.error(f"Error processing query: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.post("/email-query/{id}")
def process_email_query(
    id: str,
    data: Dict[str, Any] = Body(...),
    current_user_id: str = Depends(get_current_user)
):
    if 'email' not in data:
         raise HTTPException(status_code=400, detail="Email missing")

    email = data['email']
    
    def send_full_data_task():
        try:
            link = process_full_data(current_user_id=current_user_id, annotation_id=id)

            if link:
                subject = 'Full Data'
                body = f'Hello {email}. click this link {link} to download the full data you requested.'
                send_email(subject, [email], body)
        except Exception as e:
            logger.error(f"Error processing email query: {e}", exc_info=True)

    sender = threading.Thread(name='main_sender', target=send_full_data_task)
    sender.start()
    return {'message': 'Email sent successfully'}

@router.get("/history")
def process_user_history(
    page_number: int = 1,
    current_user_id: str = Depends(get_current_user)
):
    try:
        cursor = AnnotationStorageService.get_all(current_user_id, page_number)
        
        if cursor is None:
             return [] # JSON response

        return_value = []
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
        return return_value
    except Exception as e:
        logger.error(f"Error calling /history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.get("/annotation/{id}")
def get_annotation_by_id(
    id: str,
    token: Optional[str] = FQuery(None),
    limit: Optional[int] = FQuery(None),
    properties: Optional[str] = FQuery(None),
    source: Optional[str] = FQuery(None),
    auth_header: Optional[str] = Depends(oauth2_scheme),
    redis_client = Depends(get_redis_client),
):
    current_user_id = None
    
    # 1. Check shared token in query param
    if token:
        try:
            shared_secret = os.getenv('SHARED_TOKEN_SECRET')
            if not shared_secret:
                 shared_secret = settings.JWT_SECRET
            
            data = jwt.decode(token, shared_secret, algorithms=['HS256'])
            current_user_id = data['user_id']
            
            # Verify shared resource existence
            shared_resource = SharedAnnotationStorageService.get({
                'user_id': current_user_id,
                'annotation_id': id
            })
            if shared_resource is None:
                raise HTTPException(status_code=401, detail="Unauthorized")

        except Exception as e:
            raise HTTPException(status_code=401, detail="Unauthorized")

    # 2. If no token param, use Auth header (logged in user)
    elif auth_header:
        try:
            data = jwt.decode(auth_header, settings.JWT_SECRET, algorithms=["HS256"])
            current_user_id = data.get('user_id')
        except Exception:
            raise HTTPException(status_code=403, detail="Token is invalid!")
    
    if not current_user_id:
         raise HTTPException(status_code=401, detail="Unauthorized")

    # Access Logic
    existing_annotation = AnnotationStorageService.get_by_id(id)
    if not existing_annotation:
         raise HTTPException(status_code=404, detail="Annotation not found")

    owner_id = existing_annotation.user_id
    
    shared_annotation = SharedAnnotationStorageService.get({
        'user_id': owner_id,
        'annotation_id': id
    })
    
    if shared_annotation is None:
        if str(owner_id) != str(current_user_id):
             raise HTTPException(status_code=401, detail="Unauthorized")
    else:
        share_type = shared_annotation.share_type
        recipient_user_id = shared_annotation.recipient_user_id
        
        if share_type != 'public':
            if str(recipient_user_id) != str(current_user_id):
                raise HTTPException(status_code=401, detail="Unauthorized")
        
        current_user_id = owner_id

    cursor = AnnotationStorageService.get_user_annotation(id, str(current_user_id))


    if cursor is None:
        raise HTTPException(status_code=404, detail="No value Found")

    # Prepare Response
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

    response_data = {
        "annotation_id": str(annotation_id),
        "request": json_request,
        "title": title,
        "query": query,
        "files": files,
        "source": source,
        "species": species,
        "status": status
    }
    
    if summary: response_data["summary"] = summary
    if node_count: response_data["node_count"] = node_count; response_data["edge_count"] = edge_count
    if node_count_by_label: 
        response_data["node_count_by_label"] = node_count_by_label
        response_data["edge_count_by_label"] = edge_count_by_label
        
    if cursor.data_source == 'ai-assistant':
         return {"annotation_id": str(annotation_id), "question": question, "answer": answer}

    # Redis Cache Check
    if redis_client:
        cache = redis_client.get(str(annotation_id))
        if cache:
             cache_data = json.loads(cache)
             graph = cache_data.get('graph')
             if graph:
                 response_data['nodes'] = graph.get('nodes')
                 response_data['edges'] = graph.get('edges')
             return response_data

    if status in [TaskStatus.PENDING.value, TaskStatus.COMPLETE.value]:
        if status == TaskStatus.COMPLETE.value:
            if file_path and os.path.exists(file_path):
                 with open(file_path, 'r') as f:
                     graph = json.load(f)
                 response_data['nodes'] = graph.get('nodes')
                 response_data['edges'] = graph.get('edges')
            else:
                 response_data['status'] = TaskStatus.PENDING.value
                 from app.annotation_controller import requery
                 requery(annotation_id, query, json_request, species)
        return response_data

    return response_data


@router.get("/localized-graph")
def cell_component(
    id: str = FQuery(..., description="The annotation ID"),
    locations: str = FQuery(..., description="Comma-separated GO term IDs"),
    current_user_id: str = Depends(get_current_user),
    db_instance = Depends(get_db_instance)):
    
    # get annotation id and get go term id
    annotation_id = id

    # parse the location
    locations = locations.split(',')

    proteins = []

    try:
        # get the graph and filter out the protein
        file_name = f'{annotation_id}.json'
        path = Path(__file__).parent /".."/".."/".."/".."/"public" / "graph" / f"{file_name}"

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


        logger.info(json.dumps({"status": "success", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/localized-graph"}))
 
        return response
    except Exception as e:
        logger.error(json.dumps({"status": "error", "method": "GET",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/localized-graph",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "message": "An internal server error occurred. Please try again later.",
                "timestamp": datetime.datetime.now().isoformat()
            }
        )

@router.delete('/annotation/{id}')
def delete_by_id(id: str, current_user_id: str = Depends(get_current_user)):
    try:
        # check if the user have access to delete the resource
        annotation = AnnotationStorageService.get_user_annotation(id, current_user_id)

        if annotation is None:
            raise HTTPException(status_code=404, detail="Annotation not found")

        # first check if there is any running running annoation
        stop_event = RedisStopEvent(id, redis_state)
        status = stop_event.get_status()

        # if there is stop the running annoation
        if status is not None:
            stop_event.set_event()

            response_data = {
                'message': f'Annotation {id} has been cancelled.'
            }

        # else delete the annotation from the db
        existing_record = AnnotationStorageService.get_by_id(id)

        if existing_record is None:
            raise HTTPException(status_code=404, detail="Annotation not found")

        deleted_record = AnnotationStorageService.delete(id)

        if deleted_record is None:
            raise HTTPException(status_code=404, detail="Annotation not found")


        response_data = {
            'message': 'Annotation deleted successfully'
        }
        
        logger.info(json.dumps({"status": "success", "method": "DELETE",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>",
                                 }))

        return response_data
    except Exception as e:
        logger.error(json.dumps({"status": "error", "method": "DELETE",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>",
                                  "exception": str(e)}), exc_info=True)
        error_response = {
        "status": "error",
        "message": "An internal server error occurred. Please try again later.",
        "timestamp": datetime.datetime.now().isoformat()
        }

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "message": "An internal server error occurred. Please try again later.",
                "timestamp": datetime.datetime.now().isoformat()
            }
        )

@router.post('/annotation/delete')
async def delete_many(
    # Use Body(...) to grab the raw payload as a dict
    data: dict = Body(...), 
    current_user_id: str = Depends(get_current_user)
):
    annotation_ids = data['annotation_ids']

    # Check if the list is empty
    if len(annotation_ids) == 0:
        raise HTTPException(status_code=400, detail="Annotation must not be empty")

    # Check if user has access to delete the resource
    for annotation_id in annotation_ids:
        annotation = AnnotationStorageService.get_user_annotation(annotation_id, current_user_id)
        if annotation is None:
            # Returning 404 if user doesn't own the annotation or it doesn't exist
            raise HTTPException(status_code=404, detail=f"Annotation {annotation_id} not found or access denied")

    try:
        # Perform the deletion
        delete_count = AnnotationStorageService.delete_many_by_id(annotation_ids)

        response_data = {
            'message': f'Out of {len(annotation_ids)}, {delete_count} were successfully deleted.'
        }
        
        logger.info(json.dumps({"status": "success", "method": "POST",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/delete"}))

        return response_data
        
    except Exception as e:
        logger.error(json.dumps({"status": "error", "method": "POST",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/delete",
                                  "exception": str(e)}), exc_info=True)
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "message": "An internal server error occurred. Please try again later.",
                "timestamp": datetime.datetime.now().isoformat()
            }
        )

@router.post('/annotation/{id}/title')
def update_title(id:str, data: dict = Body(...),current_user_id: str = Depends(get_current_user)):

    if 'title' not in data:
        raise HTTPException(status_code=400, detail="Title is required")

    title = data['title']

    try:
        existing_record = AnnotationStorageService.get_by_id(id)

        if existing_record is None:
            raise HTTPException(status_code=404, detail="Annotation not found")

        AnnotationStorageService.update(id, {'title': title})

        response_data = {
            'message': 'title updated successfully',
            'title': title,
        }

        logger.info(json.dumps({"status": "success", "method": "PUT",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>/title"}))
        return response_data
    except Exception as e:
        logger.error(json.dumps({"status": "error", "method": "PUT",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "/annotation/<id>/title",
                                  "exception": str(e)}), exc_info=True)

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "message": "An internal server error occurred. Please try again later.",
                "timestamp": datetime.datetime.now().isoformat()
            }
        )
import logging
from flask import Response, request, current_app
from app import app, db_instance, schema_manager
import json
import os
import datetime
from app.workers.task_handler import graph_task, start_thread, reset_task, reset_status
from app.lib import convert_to_csv, generate_file_path, \
    adjust_file_path
import time
from app.constants import TaskStatus
from app.persistence import AnnotationStorageService
from .workers.celery_app import init_request_state

llm = app.config['llm_handler']
EXP = os.getenv('REDIS_EXPIRATION', 3600)

def handle_client_request(query, request, current_user_id, node_types, species, data_source, node_map):
    annotation_id = request.get('annotation_id', None)
    
    # --- 1. Check for existing Annotation ---
    if annotation_id:
        existing_query = AnnotationStorageService.get_user_query(
            annotation_id, str(current_user_id), query[0])
    else:
        existing_query = None

    # --- 2. Handle Existing Query ---
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
        AnnotationStorageService.update(
            annotation_id, {"status": TaskStatus.PENDING.value, "updated_at": datetime.datetime.now()})
        
        reset_status(annotation_id)
        # Initialize Redis keys for progress tracking (0/1)
        init_request_state(annotation_id)

        args = {
            'all_status': {
                'result_done': 0, 
                'total_count_done': 0,
                'label_count_done': 0
            }, 
            'query': query, 
            'request': request,
            'summary': summary, 
            'meta_data': meta_data, 
            'data_source': data_source, 
            'species': species
        }

        start_thread(annotation_id, args)
        return Response(
            json.dumps({"annotation_id": str(annotation_id)}),
            mimetype='application/json')

    # --- 3. Handle New Query (Create New Annotation) ---
    elif annotation_id is None:
        title = llm.generate_title(query[0], request, node_map)
        annotation = {"current_user_id": str(current_user_id),
                      "query": str(query[0]), "request": request,
                      "title": title, "node_types": node_types,
                      "status": TaskStatus.PENDING.value,
                      "data_source": data_source, "species": species}

        annotation_id = AnnotationStorageService.save(annotation)
        init_request_state(annotation_id)

        args = {
            'all_status': {
                'result_done': 0, 
                'total_count_done': 0,
                'label_count_done': 0
            }, 
            'query': query, 
            'request': request,
            'summary': None, 
            'meta_data': None, 
            'data_source': data_source, 
            'species': species
        }
        start_thread(annotation_id, args)

        return Response(
            json.dumps({"annotation_id": str(annotation_id)}),
            mimetype='application/json')

    # --- 4. Handle Existing Annotation ID but different query (Update) ---
    else:
        title = llm.generate_title(query[0], request, node_map)
        # Check if annotation_id needs to be removed from request dict (cleanup)
        if 'annotation_id' in request:
            del request['annotation_id']
            
        annotation = {"query": str(query[0]), "request": request,
                      "title": title, "node_types": node_types,
                      'status': TaskStatus.PENDING.value, 'node_count': None,
                      'edge_count': None, 'node_count_by_label': None,
                      'edge_count_by_label': None, 'species': species, 'data_source': data_source}

        AnnotationStorageService.update(annotation_id, annotation)
        reset_task(annotation_id)
        init_request_state(annotation_id)

        args = {
            'all_status': {
                'result_done': 0, 
                'total_count_done': 0,
                'label_count_done': 0
            }, 
            'query': query, 
            'request': request,
            'summary': None, 
            'meta_data': None, 
            'species': species
        }

        start_thread(annotation_id, args)

        return Response(
            json.dumps({'annotation_id': str(annotation_id)}),
            mimetype='application/json'
        )

def process_full_data(current_user_id, annotation_id):
    cursor = AnnotationStorageService.get_by_id(annotation_id)

    if cursor is None:
        return None

    query, title, requests = cursor.query, cursor.title, cursor.request

    graph_components = {
            "nodes": requests['nodes'], "predicates": requests['predicates'],
            'properties': True}

    try:
        file_path = generate_file_path(
            file_name=title, user_id=current_user_id, extension='xls')
        exists = os.path.exists(file_path)

        if exists:
            file_path = adjust_file_path(file_path)
            link = f'{request.host_url}{file_path}'
            return link

        result = db_instance.run_query(query)
        parsed_result = db_instance.convert_to_dict(
            result, schema_manager.schema, graph_components)

        file_path = convert_to_csv(
            parsed_result, user_id=current_user_id, file_name=title)
        file_path = adjust_file_path(file_path)

        link = f'{request.host_url}{file_path}'
        return link

    except Exception as e:
        raise e

def requery(annotation_id, query, request, species='human'):
    """
    Re-runs only the graph generation part of the task.
    """
    AnnotationStorageService.update(
        annotation_id, {"status": TaskStatus.PENDING.value})
    
    # We reset redis status for this task
    reset_status(annotation_id)
    # Ensure redis progress keys are ready
    init_request_state(annotation_id)

    try:
        graph_task.delay(
            query, 
            annotation_id, 
            request, 
            0, # dummy for 'result_status'
            species, 
            status=TaskStatus.COMPLETE.value
        )
    except Exception as e:
        logging.error("Error triggering graph_task celery job %s", e)

    return
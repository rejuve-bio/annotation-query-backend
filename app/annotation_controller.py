import logging
from flask import Response, request
from app import app, db_instance, schema_manager
import json
import os
import threading
import datetime
from app.workers.task_handler import generate_result, start_thread, reset_task, reset_status
from app.lib import convert_to_csv, generate_file_path, \
    adjust_file_path
import time
from app.constants import TaskStatus
from app.persistence import AnnotationStorageService

llm = app.config['llm_handler']
EXP = os.getenv('REDIS_EXPIRATION', 3600) # expiration time of redis cache

def handle_client_request(query, request, current_user_id, node_types, species):
    annotation_id = request.get('annotation_id', None)
    # check if annotation exist

    if annotation_id:
        existing_query = AnnotationStorageService.get_user_query(
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
        AnnotationStorageService.update(
            annotation_id, {"status": TaskStatus.PENDING.value, "updated_at": datetime.datetime.now()})
        reset_status(annotation_id)
        
        args = {'all_status': {'result_done': result_done, 'total_count_done': total_count_done,
                               'label_count_done': label_count_done}, 'query': query, 'request': request,
                'summary': summary, 'meta_data': meta_data, 'species': species}
        
        start_thread(annotation_id, args)
        return Response(
            json.dumps({"annotation_id": str(annotation_id)}),
            mimetype='application/json')
    elif annotation_id is None:
        title = llm.generate_title(query[0])
        annotation = {"current_user_id": str(current_user_id),
                      "query": query[0], "request": request,
                      "title": title, "node_types": node_types,
                      "status": TaskStatus.PENDING.value}

        annotation_id = AnnotationStorageService.save(annotation)

        args = {'all_status': {'result_done': result_done, 'total_count_done': total_count_done,
                               'label_count_done': label_count_done}, 'query': query, 'request': request,
                'summary': None, 'meta_data': None, 'species': species}
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
                      'status': TaskStatus.PENDING.value, 'node_count': None, 
                      'edge_count': None, 'node_count_by_label': None,
                      'edge_count_by_label': None}

        AnnotationStorageService.update(annotation_id, annotation)
        reset_task(annotation_id)

        args = {'all_status': {'result_done': result_done, 'total_count_done': total_count_done,
                               'label_count_done': label_count_done}, 'query': query, 'request': request,
                'summary': None, 'meta_data': None, 'species': species}
        
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


        # Run the query and parse the results
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

def requery(annotation_id, query, request):
    #Event to track tasks
    result_done = threading.Event()
    AnnotationStorageService.update(
        annotation_id, {"status": TaskStatus.PENDING.value})
    
    app.config['annotation_threads'][str(annotation_id)] = threading.Event()

    reset_status(annotation_id)

    annotation_threads = app.config['annotation_threads']
    annotation_threads[str(annotation_id)] = threading.Event()

    def send_annotation():
        time.sleep(0.1)
        try:
            generate_result(query, annotation_id, request, result_done, status=TaskStatus.COMPLETE.value)
        except Exception as e:
                logging.error("Error generating result graph %s", e)
      
    
    result_generator = threading.Thread(
        name='result_generator', target=send_annotation)
    result_generator.start()
    return
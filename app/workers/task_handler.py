from flask import request, Response
from app import app, schema_manager, db_instance, socketio, redis_client, ThreadStopException
import logging
import json
import os
import threading
import time
from app.lib import Graph
from app.constants import TaskStatus
import traceback

llm = app.config['llm_handler']
storage_service = app.config['storage_service']
EXP = os.getenv('REDIS_EXPIRATION', 3600) # expiration time of redis cache

def update_task(annotation_id, graph=None):
    with app.config['annotation_lock']:
        status = TaskStatus.PENDING.value
        # Get the cached data (Handle case where cache is None)
        cache = redis_client.get(str(annotation_id))
        
        cache = json.loads(cache) if cache else {'graph': None, 'status': status}
        
        status = cache['status']
        # Merge graph updates
        graph = graph if graph else cache['graph']
        
        if status == TaskStatus.COMPLETE.value:
            redis_client.setex(str(annotation_id), EXP, json.dumps({
                'graph': graph, 'status': TaskStatus.COMPLETE.value
            }))
            storage_service.update(annotation_id, {'status': status})
            redis_client.delete(f"{annotation_id}_tasks")
            return TaskStatus.COMPLETE.value
        
        # Increment task count atomically and get the new count
        task_num = redis_client.incr(f"{annotation_id}_tasks")
    
        if status in [TaskStatus.FAILED.value, TaskStatus.CANCELLED.value]:
            if task_num >= 4 and cache['status'] == TaskStatus.CANCELLED.value:
                storage_service.delete(annotation_id)
                redis_client.delete(f"{annotation_id}_tasks")
                redis_client.delete(str(annotation_id))
                with app.config['annotation_lock']:
                    annotation_threads = app.config['annotation_threads']
                    del annotation_threads[str(annotation_id)]
        else:
            status = TaskStatus.COMPLETE.value if task_num >= 4 else TaskStatus.PENDING.value
        if status in [TaskStatus.FAILED.value, TaskStatus.COMPLETE.value] and task_num >= 4:
            redis_client.setex(str(annotation_id), EXP, json.dumps({
                'graph': graph, 'status': status
            }))
            storage_service.update(annotation_id, {'status': status})
            redis_client.delete(f"{annotation_id}_tasks")
        elif status == TaskStatus.PENDING.value:
            redis_client.set(str(annotation_id), json.dumps({
                'graph': graph, 'status': status
            }))
        
        return status

def get_status(annotation_id):
    with app.config['annotation_lock']:
        cache = redis_client.get(str(annotation_id))
        if cache is not None:
            cache = json.loads(cache)
            status = cache['status']
            return status
        else:
            return TaskStatus.PENDING.value
    
def set_status(annotation_id, status):
    with app.config['annotation_lock']:
        cache = redis_client.get(str(annotation_id))
        if cache is not None:
            cache = json.loads(cache)
            cache['status'] = status
            redis_client.set(str(annotation_id), json.dumps(cache))
        else:
            redis_client.set(str(annotation_id), json.dumps({'graph': None, 'status': status}))

def get_annotation_redis(annotation_id):
    cache = redis_client.get(str(annotation_id))
    if cache is not None:
        cache = json.loads(cache)
        return cache
    else:
        return None

def reset_status(annotation_id):
    redis_client.delete(f"{annotation_id}_tasks")
    set_status(annotation_id, TaskStatus.PENDING.value)

def reset_task(annotation_id):
    redis_client.delete(f"{annotation_id}_tasks")
    redis_client.delete(str(annotation_id))

def generate_summary(annotation_id, request, all_status, summary=None):
    result_done, total_count_done, label_count_done = all_status.values()
    # wait for all threads to finish
    result_done.wait()
    total_count_done.wait()
    label_count_done.wait()

    if get_status(annotation_id) == TaskStatus.FAILED.value:
        summary = 'Failed to generate summary'
        status = TaskStatus.FAILED.value
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
    except ThreadStopException as e:
        set_status(annotation_id, TaskStatus.CANCELLED.value)
        update_task(annotation_id)
        socketio.emit('update', {'status': TaskStatus.CANCELLED.value, 
                                'update': {'summary': 'Summary cancelled'}})
        logging.error("Error generating result graph %s", e)
    except Exception as e:
        logging.exception("Error generating summary %s", e)
        status = update_task(annotation_id)
        socketio.emit('update', {'status': status, 
                        'update': {'summary': 'Graph too big, could not summarize'}},
                      to=str(annotation_id))


def generate_result(query_code, annotation_id, requests, result_status, status=None):
    try:
        annotation_threads = app.config['annotation_threads']
        stop_event = annotation_threads[str(annotation_id)]
        if stop_event.is_set():
            raise ThreadStopException('Stoping result generation thread')
        
        if get_status(annotation_id) == TaskStatus.CANCELLED.value:
            socketio.emit('update', {'status': TaskStatus.CANCELLED.value, 'update': {'graph': False}})
            status = update_task(annotation_id)
            result_status.set()
            return

        response_data = db_instance.run_query(query_code, stop_event)
        graph_components = {"nodes": requests['nodes'], "predicates":
                            requests['predicates'], "properties": True}
        response = db_instance.parse_and_serialize(
            response_data, schema_manager.schema, graph_components, 'graph')

        graph = Graph()
        
        if len(response['edges']) == 0 and len(response['nodes']) > 0:
            grouped_graph = graph.group_node_only(response, requests)
        else:
            grouped_graph = graph.group_graph(response)
            
        if status:
            set_status(annotation_id, status)
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
    except ThreadStopException as e:
        set_status(annotation_id, TaskStatus.CANCELLED.value)
        update_task(annotation_id, {
            "nodes": [],
            "edges": []
        })
        socketio.emit('update', {'status': TaskStatus.CANCELLED.value, 'update': {'graph': False}})
        result_status.set()
        logging.error("Error generating result graph %s", e)
    except Exception as e:
        set_status(annotation_id, TaskStatus.FAILED.value)
        socketio.emit('update', {'status': TaskStatus.FAILED.value, 'update': {'graph': False}})
        storage_service.update(annotation_id, {'status': TaskStatus.FAILED.value})
        result_status.set()
        logging.error("Error generating result graph %s", e)


def generate_total_count(count_query, annotation_id, requests, total_count_status, meta_data=None):
    if get_status(annotation_id) == TaskStatus.FAILED.value:
        socketio.emit('update', {'status': TaskStatus.FAILED.value, 
                                 'update': {'node_count': 0, 'edge_count': 0}
                                })
        status = update_task(annotation_id)
        total_count_status.set()
        return
    
    if get_status(annotation_id) == TaskStatus.FAILED.value:
        socketio.emit('update', {'status': TaskStatus.CANCELLED.value, 
                                 'update': 
                                    {'node_count': 0, 'edge_count': 0}
                                })
        status = update_task(annotation_id)
        total_count_status.set()
        return
    
    annotation_threads = app.config['annotation_threads']
    stop_event = annotation_threads[str(annotation_id)]
    
    if stop_event.is_set():
        raise ThreadStopException('Stoping result generation thread')
    
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

        total_count = db_instance.run_query(count_query, stop_event)

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
    except ThreadStopException as e:
        set_status(annotation_id, TaskStatus.CANCELLED.value)
        update_task(annotation_id)
        socketio.emit('update', {'status': TaskStatus.CANCELLED.value, 
                                 'update': {'node_count': 0, 'edge_count': 0}
                                 })
        total_count_status.set()
        logging.error("Error generating total count %s", e)
    except Exception as e:
        set_status(annotation_id, TaskStatus.FAILED.value)
        update_task(annotation_id)
        storage_service.update(annotation_id, {'status': TaskStatus.FAILED.value, 
                                               'node_count': 0, 
                                               'edge_count': 0
                                            })
        socketio.emit('update', {'status': TaskStatus.FAILED.value, 
                                 'update': {'node_count': 0, 'edge_count': 0}
                                })
        total_count_status.set()
        logging.error("Error generating total count %s", e)

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
    if get_status(annotation_id) == TaskStatus.FAILED.value:
        update = generate_empty_lable_count(requests)
        status = update_task(annotation_id)
        socketio.emit('update', {'status': status, 'update': update})
        count_label_status.set()
        return
    
    if get_status(annotation_id) == TaskStatus.CANCELLED.value:
        update = generate_empty_lable_count(requests)
        status = update_task(annotation_id)
        socketio.emit('update', {
            'status': TaskStatus.CANCELLED.value,
            'update': {'node_count_by_label':[],
                       'edge_count_by_label':[]
                       }})
        count_label_status.set()
        return

    annotation_threads = app.config['annotation_threads']
    stop_event = annotation_threads[str(annotation_id)]
    
    if stop_event.is_set():
        raise ThreadStopException('Stoping result generation thread')

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

        label_count = db_instance.run_query(count_query, stop_event)

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
    except ThreadStopException as e:
        set_status(annotation_id, TaskStatus.CANCELLED.value)
        update_task(annotation_id)
        update = generate_empty_lable_count(requests)
        socketio.emit('update', {
            'status': TaskStatus.CANCELLED.value,
            'update': {'node_count_by_label':[],
                       'edge_count_by_label':[]
                       }},
                      to=str(annotation_id))
        count_label_status.set()
        logging.error("Error generating result graph %s", e)
    except Exception as e:
        set_status(annotation_id, 'FAILED')
        update_task(annotation_id)

        update = generate_empty_lable_count(requests)
        storage_service.update(annotation_id, {'status': TaskStatus.FAILED.value, 
                                               'node_count_by_label': update['node_count_by_label'],
                                               'edge_count_by_label': update['edge_count_by_label']
                                               })
        socketio.emit('update', {'status': TaskStatus.FAILED.value, 'update': update})
        count_label_status.set()
        logging.error("Error generating label count %s", e)

def start_thread(annotation_id, args):
    all_status = args['all_status']
    find_query = args['query'][0]
    total_count_query = args['query'][1]
    label_count_query = args['query'][2]
    request = args['request']
    summary = args['summary']
    meta_data = args['meta_data']
    
    #TODO: make it trhead safe by locking the resources 
    annotation_threads = app.config['annotation_threads']
    annotation_threads[str(annotation_id)] = threading.Event()

    def send_annotation():
        try:
            generate_result(find_query, annotation_id, request, all_status['result_done'])
        except Exception as e:
                logging.error("Error generating result graph %s", e)
      
    def send_summary():
        try:
            generate_summary(annotation_id, request, all_status, summary)
        except Exception as e:
            logging.error("Error generating summary %s", e)
    
    
    def send_total_count():
        try:
            generate_total_count(
                total_count_query, annotation_id, request, all_status['total_count_done'], meta_data)
        except Exception as e:
            logging.error("Error generating total count %s", e)

    def send_label_count():
        try:
            generate_label_count(label_count_query, annotation_id, request, all_status['label_count_done'], meta_data)
        except Exception as e:
            logging.error("Error generating count by label %s", e)

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
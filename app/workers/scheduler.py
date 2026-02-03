from app.services.cypher_generator import CypherQueryGenerator 
import os
import json
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
import logging
import datetime
import threading
from urllib.parse import urlparse
from app import app

REDIS_URL = app.config['REDIS_URL']
parsed = urlparse(REDIS_URL)
host = parsed.hostname or 'localhost'
port = parsed.port or 6379
password = parsed.password

file_lock = threading.Lock()
db = CypherQueryGenerator('/data')

def update_total_entity_count():
    try:
        total_entity_query = db.get_total_entity_query()
        total_entity_count = db.run_query(total_entity_query)
        return total_entity_count
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "background worker",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "background worker",
                                  "exception": str(e)}), exc_info=True)
        return None

def update_total_connection_count():
    try:
        total_connection_query = db.get_total_connection_query()
        total_connection_count = db.run_query(total_connection_query)
        return total_connection_count
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "background worker",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "background worker",
                                  "exception": str(e)}), exc_info=True)
        return None

def update_total_node_count_by_label():
    try: 
        total_node_count_by_label_query = db.get_node_count_by_label_query()
        total_node_count_by_label = db.run_query(total_node_count_by_label_query)
        return total_node_count_by_label
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "background worker",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "background worker",
                                  "exception": str(e)}), exc_info=True)
        return None

def update_total_connection_count_by_label():
    try:
        total_connection_count_by_label_query = db.get_total_connection_count_by_label_query()
        total_connection_count_by_label = db.run_query(total_connection_count_by_label_query)
        return total_connection_count_by_label
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "background worker",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "background worker",
                                  "exception": str(e)}), exc_info=True)
        return None

def update_total_connection_count_by_label_source_target():
    try:
        total_connection_count_by_label_query = db.get_connection_count_by_label_source_target_query()
        total_connection_count_by_label = db.run_query(total_connection_count_by_label_query)
        return total_connection_count_by_label
    except Exception as e:
        logging.error(json.dumps({"status": "error", "method": "background worker",
                                  "timestamp":  datetime.datetime.now().isoformat(),
                                  "endpoint": "background worker",
                                  "exception": str(e)}), exc_info=True)
        return None

def update_json():
    total_entity_count= update_total_entity_count()
    total_connection_count = update_total_connection_count()
    total_node_count_by_label = update_total_node_count_by_label()
    top_connections_by_label_count = update_total_connection_count_by_label()
    total_connection_by_source_target = update_total_connection_count_by_label_source_target()
    
    total_node_count_by_label = total_node_count_by_label[0]
    total_entity = []
    for key, value in total_node_count_by_label['labels'].items():
        total_entity.append({
            "count": value,
            "name": key
        })

    total_connections = []

    for connection in top_connections_by_label_count:
        total_connections.append({
            "count": connection['value.count'],
            "name": connection['type']
        })

    frequent_relationships = []
    for connection in total_connection_by_source_target:
        frequent_relationships.append({
            "count": connection['count'],
            "entities": [connection['source'], connection['target']]
        })
    data = {
        "node_count": total_entity_count[0]['count'],
        "edge_count": total_connection_count[0]['count'],
        "top_entites": total_entity,
        "top_connections": total_connections,
        "frequent_relationships": frequent_relationships
    }

    current_directory = os.path.dirname(os.path.abspath(__file__))
    graph_info_path = os.path.join(current_directory, '..', '..', 'Data', 'graph_info.json')

    try:
        with open(graph_info_path, 'r') as json_file:
            old_data = json.load(json_file)

        old_data['node_count'] = data['node_count']
        old_data['edge_count'] = data['edge_count']
        old_data['top_entites'] = data['top_entites']
        old_data['top_connections'] = data['top_connections']
        old_data['frequent_relationships'] = data['frequent_relationships']

        with file_lock:
            with open(graph_info_path, 'w') as json_file:
                json.dump(old_data, json_file, ensure_ascii=False, indent=4)

        logging.info(json.dumps({
            "status": "success", "method": "background worker",
            "timestamp": datetime.datetime.now().isoformat(),
        }))
    except FileNotFoundError:
        with file_lock:
            with open(graph_info_path, 'w') as json_file:
                json.dump(data, json_file, ensure_ascii=False, indent=4)
    except json.JSONDecodeError:
        logging.error(json.dumps({"status": "error", "method": "backgroud worker",
                          "timestamp":  datetime.datetime.now().isoformat(),
                          "endpoint": "background worker",
                          "exception": f"Error: Could not decode JSON from '{graph_info_path}'. Check file format."}), exc_info=True)

def metadata_update_worker():
    jobstores = {
        'default': RedisJobStore(host=host, port=port, password=password),
    }

    executors = {
        'default': ThreadPoolExecutor(1)
    }

    # Optional: job defaults
    job_defaults = {
        'coalesce': False,
        'max_instances': 1
    }

    # Create the scheduler
    scheduler = BackgroundScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults
    )

    # Schedule your job to run every Sunday at midnight
    scheduler.add_job(
        update_json,
        trigger='cron',
        day_of_week='sun',
        hour=0,
        minute=0,
        id='update_json_job',          # fixed job ID
        replace_existing=True          # replace any existing job with this ID
    )

    scheduler.start()
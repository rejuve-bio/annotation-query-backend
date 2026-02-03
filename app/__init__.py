from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO
from app.services.schema_data import SchemaManager
from app.services.cypher_generator import CypherQueryGenerator
from app.services.metta_generator import MeTTa_Query_Generator
from logger import init_logging
from app.persistence import AnnotationStorageService, UserStorageService
import os
import logging
import yaml
import redis
from app.error import ThreadStopException, TaskCancelledException
import threading
from app.constants import TaskStatus, GRAPH_INFO_PATH, ES_API_KEY, ES_URL
import json
from dotenv import load_dotenv
from elasticsearch import Elasticsearch

load_dotenv()

# Configure logging to ensure we see the output in Docker logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

perf_logger = init_logging()

app = Flask(__name__)
# Disable werkzeug request logs
logging.getLogger('werkzeug').disabled = True
socketio = SocketIO(app, cors_allowed_origins='*',
                    async_mode='threading', logger=False, engineio_logger=False)

# Get Redis URL from env
redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
app.config['REDIS_URL'] = redis_url

# Initialize Redis
try:
    redis_client = redis.from_url(redis_url)
    logger.info(f"[App Init] Connected to Redis at {redis_url}")
except Exception as e:
    logger.error(f"[App Init] Failed to connect to Redis: {e}")
    redis_client = None

def load_config():
    config_path = os.path.join(os.path.dirname(
        __file__), '..', 'config', 'config.yaml')
    try:
        with open(config_path, 'r') as file:
            config = yaml.safe_load(file)
        logger.info("Configuration loaded successfully.")
        return config
    except FileNotFoundError:
        logger.error(f"Config file not found at: {config_path}")
        raise
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file: {e}")
        raise

config = load_config()

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["10000 per minute"],
)

try:
    es_db = Elasticsearch(ES_URL, api_key=ES_API_KEY)
    if es_db.ping():
        print("Elasticsearch connected")
    else:
        print("Elasticsearch not reachable, continuing without it")
        logger.error("Elasticsearch not reachable")
        es_db = None
except:
    logger.error("Elasticsearch not reachable")
    es_db = None

schema_manager = SchemaManager(schema_config_path='./config/schema_config.yaml',
                               biocypher_config_path='./config/biocypher_config.yaml',
                               config_path='./config/schema',
                               fly_schema_config_path='./config/fly_base_schema/net_act_essential_schema_config.yaml')


from app.services.mork_generator import MorkQueryGenerator

databases = {
    "metta": lambda: MeTTa_Query_Generator("./Data"),
    "cypher": lambda: CypherQueryGenerator("./cypher_data"),
    "mork": lambda: MorkQueryGenerator("./mork_data")
}

database_type = config['database']['type']
db_instance = databases[database_type]()

from app.services.llm_handler import LLMHandler

llm = LLMHandler()

app.config['llm_handler'] = llm
app.config['es_db'] = es_db
app.config['db_type'] = database_type

graph_info = json.load(open(GRAPH_INFO_PATH))

from app import routes
from app.annotation_controller import handle_client_request, process_full_data, requery
from app.workers.scheduler import metadata_update_worker

def listen_to_redis(app):
    """
    Listens to Redis 'socket_event' channel and emits to SocketIO.
    This runs in a background thread.
    """
    if not redis_client:
        logger.error("Redis client not initialized, skipping listener")
        return

    with app.app_context():
        pubsub = redis_client.pubsub()
        pubsub.subscribe('socket_event')
        
        logger.info(f"[Redis Listener] Started. Subscribed to 'socket_event' on {app.config['REDIS_URL']}")
        
        try:
            # Loop forever
            for message in pubsub.listen():
                # Log that we received SOMETHING (even handshake messages)
                if message['type'] != 'message':
                    logger.debug(f"[Redis Listener] System message: {message}")
                    continue

                logger.info(f"[Redis Listener] Message Received! Type: {message['type']}")
                
                try:
                    raw_data = message['data']
                    logger.info(f"🔍 [Redis Listener] Raw Data: {raw_data}")
                    
                    if isinstance(raw_data, bytes):
                        data = json.loads(raw_data.decode('utf-8'))
                    else:
                        data = json.loads(raw_data)

                    status = data.get('status')
                    update = data.get('update')
                    annotation_id = data.get('annotation_id')
                    
                    if annotation_id:
                        room_id = str(annotation_id)
                        logger.info(f"[Redis Listener] Emitting SocketIO to Room: '{room_id}' | Status: {status}")
                        
                        socketio.emit('update', 
                                      {'status': status, 'update': update}, 
                                      to=room_id)
                        logger.info(f"[Redis Listener] Emit called successfully.")
                    else:
                        logger.warning(f"[Redis Listener] Message missing 'annotation_id': {data}")

                except json.JSONDecodeError as e:
                    logger.error(f"[Redis Listener] JSON Decode Error: {e} | Data: {message['data']}")
                except Exception as e:
                    logger.error(f"[Redis Listener] Processing Error: {e}")

        except Exception as e:
            logger.error(f"[Redis Listener] CRITICAL FAILURE: {e}")

def start_redis_listener():
    # Start the listener in a background thread
    logger.info("Init] Starting Redis Listener Thread...")
    redis_thread = threading.Thread(target=listen_to_redis, args=(app,))
    redis_thread.daemon = True
    redis_thread.start()

metadata_update_worker()
start_redis_listener()
from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO
from app.services.schema_data import SchemaManager
from app.services.cypher_generator import CypherQueryGenerator
from app.services.metta_generator import MeTTa_Query_Generator
from db import mongo_init
from app.services.llm_handler import LLMHandler
from app.persistence import AnnotationStorageService, UserStorageService
import os
import logging
import yaml
from flask_redis import FlaskRedis
from app.error import ThreadStopException
import threading
from app.constants import TaskStatus, GRAPH_INFO_PATH
import json

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins='*',
                    async_mode='threading', logger=True, engineio_logger=True)

app.config['REDIS_URL'] = os.getenv('REDIS_URL')

# intialize redis
redis_client = FlaskRedis(app)

def load_config():
    config_path = os.path.join(os.path.dirname(
        __file__), '..', 'config', 'config.yaml')
    try:
        with open(config_path, 'r') as file:
            config = yaml.safe_load(file)
        logging.info("Configuration loaded successfully.")
        return config
    except FileNotFoundError:
        logging.error(f"Config file not found at: {config_path}")
        raise
    except yaml.YAMLError as e:
        logging.error(f"Error parsing YAML file: {e}")
        raise


config = load_config()

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per minute"],
)

mongo_init()

databases = {
    "metta": lambda: MeTTa_Query_Generator("./Data"),
    "cypher": lambda: CypherQueryGenerator("./cypher_data")

    # Add other database instances here
}

database_type = config['database']['type']
db_instance = databases[database_type]()

llm = LLMHandler()  # Initialize the LLMHandler

app.config['llm_handler'] = llm
app.config['annotation_threads'] = {} # holding the stop event for each annotation task
app.config['annotation_lock'] = threading.Lock()

schema_manager = SchemaManager(schema_config_path='./config/schema_config.yaml',
                               biocypher_config_path='./config/biocypher_config.yaml',
                               config_path='./config/schema',
                               fly_schema_config_path='./config/fly_base_schema/net_act_essential_schema_config.yaml')

#load the json that holds the count for the edges
graph_info = json.load(open(GRAPH_INFO_PATH))

# Import routes at the end to avoid circular imports
from app import routes
from app.annotation_controller import handle_client_request, process_full_data, requery
import os
import logging
import yaml
from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO
from app.services.schema_data import SchemaManager
from app.services.cypher_generator import CypherQueryGenerator
from app.services.metta_generator import MeTTa_Query_Generator
from app.services.llm_handler import LLMHandler
from app.persistence.storage_service import StorageService
from db import mongo_init
from flask_cors import CORS
# Initialize Flask app
app = Flask(__name__)


# Set secret key
app.config['SECRET_KEY'] = 'secret'

socketio = SocketIO(app,cors_allowed_origins="*")
CORS(app)
# Function to load configuration from YAML file
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'config.yaml')
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

# Load configuration
config = load_config()

# Initialize rate limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per minute"],
)

# Initialize MongoDB connection
mongo_init()

# Initialize database instances based on configuration
databases = {
    "metta": lambda: MeTTa_Query_Generator("./Data"),
    "cypher": lambda: CypherQueryGenerator("./cypher_data"),
    # Add other database instances here
}

# Fetch the database type from the configuration
database_type = config.get('database', {}).get('type')
if database_type not in databases:
    raise ValueError(f"Unsupported database type: {database_type}")

db_instance = databases[database_type]()

# Initialize LLM handler and storage service
llm = LLMHandler()
storage_service = StorageService()

# Store handlers in app config for global access
app.config['llm_handler'] = llm
app.config['storage_service'] = storage_service

# Initialize schema manager
schema_manager = SchemaManager(
    schema_config_path='./config/schema_config.yaml',
    biocypher_config_path='./config/biocypher_config.yaml'
)

# Import routes at the end to avoid circular imports
from app import routes

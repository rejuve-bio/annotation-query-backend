from flask import Flask
from app.services.schema_data import SchemaManager
from app.services.cypher_generator import CypherQueryGenerator
from app.services.metta_generator import MeTTa_Query_Generator
from db import mongo_init
from app.services.llm_handler import LLMHandler
from app.persistence.storage_service import StorageService

app = Flask(__name__)

mongo_init()

databases = {
    "metta": MeTTa_Query_Generator("./Data"),
    "cypher": CypherQueryGenerator("./cypher_data")
    
    # Add other database instances here
}

llm = LLMHandler()  # Initialize the LLMHandler
storage_service = StorageService() # Initialize the storage service

app.config['llm_handler'] = llm
app.config['storage_service'] = storage_service

schema_manager = SchemaManager(schema_config_path='./config/schema_config.yaml', biocypher_config_path='./config/biocypher_config.yaml')

# Import routes at the end to avoid circular imports
from app import routes


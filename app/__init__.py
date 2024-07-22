from flask import Flask
from app.services.schema_data import SchemaManager
from app.services.cypher_generator import CypherQueryGenerator
from app.services.metta_generator import MeTTa_Query_Generator

app = Flask(__name__)

databases = {
    "metta": MeTTa_Query_Generator("./dataset"),
    "cypher": CypherQueryGenerator("./cypher")
    
    # Add other database instances here
}

schema_manager = SchemaManager(schema_config_path='./config/schema_config.yaml', biocypher_config_path='./config/biocypher_config.yaml')

# Import routes at the end to avoid circular imports
from app import routes

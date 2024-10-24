import pytest
import logging
from app import app
from app.services.schema_data import SchemaManager
import time

# Fixture to suppress logging during tests
@pytest.fixture(autouse=True)
def suppress_logging():
    logging.disable(logging.CRITICAL)  # Disable all logging during tests
    yield
    
    # Flush any remaining log messages before shutting down
    logging.shutdown()  # Ensure that all logging is flushed

    # Re-enable logging after tests
    logging.disable(logging.NOTSET)

@pytest.fixture(scope="session", autouse=True)
def wait_for_db_connection():
    # Wait for 3 seconds before starting the tests
    time.sleep(3)
    # Here you can add code to establish the database connection if needed
    yield

# Initializes a test client
@pytest.fixture
def client():
    with app.test_client() as client:
        yield client  # Provides the test client for use in tests

# List of nodes
@pytest.fixture
def node_list():
    return [
        'gene', 'transcript', 'pathway', 'go',
        'enhancer', 'super enhancer', 'promoter',
        'regulatory region', 'snp', 'protein', 'non-coding rna'
    ]

# Fixture for using against the schema check
@pytest.fixture
def schema():
    schema_manager = SchemaManager(
        schema_config_path='./config/schema_config.yaml',
        biocypher_config_path='./config/biocypher_config.yaml'
    )
    return schema_manager.schema


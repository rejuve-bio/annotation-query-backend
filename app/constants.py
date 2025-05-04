from enum import Enum
import os
from dotenv import load_dotenv

load_dotenv()

class TaskStatus(Enum):
    PENDING = 'PENDING'
    CANCELLED = 'CANCELLED'
    COMPLETE = 'COMPLETE'
    FAILED = 'FAILED'
    
# Define the absolute path to the JSON file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GRAPH_INFO_PATH = os.path.join(BASE_DIR, '../Data/count_info.json')
ES_URL = os.getenv('ES_URL')
ES_API_KEY = os.getenv('ES_API_KEY')

from enum import Enum
import os

class TaskStatus(Enum):
    PENDING = 'PENDING'
    CANCELLED = 'CANCELLED'
    COMPLETE = 'COMPLETE'
    FAILED = 'FAILED'
    
# Define the absolute path to the JSON file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GRAPH_INFO_PATH = os.path.join(BASE_DIR, '../Data/count_info.json')

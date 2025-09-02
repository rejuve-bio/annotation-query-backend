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

CELL_STRUCTURE = {
    "name": "Cell",
    "components": {
            "go_0005643": "Nuclear pore",
            "go_0031965": "Nuclear membrane",
            "go_0005730": "Nucleolus",
            "go_0005654": "Nucleoplasm",
            "go_0000790": "Nuclear chromatin",
            "go_0048238": "Smooth endoplasmic reticulum lumen",
            "go_0030868": "Smooth endoplasmic reticulum membrane",
            "go_0005840": "Rough endoplasmic reticulum ribosome",
            "go_0030867": "Rough endoplasmic reticulum membrane",
            "go_0048237": "Rough endoplasmic reticulum lumen",
            "go_0005798": "Golgi-associated vesicle",
            "go_0000139": "Golgi membrane",
            "go_0005796": "Golgi lumen",
            "go_0005759": "Mitochondrial matrix",
            "go_0005743": "Mitochondrial inner membrane",
            "go_0005758": "Mitochondrial intermembrane space",
            "go_0005741": "Mitochondrial outer membrane",
            "go_0030061": "Mitochondrial crista",
            "go_0015934": "Large ribosomal subunit",
            "go_0015935": "Small ribosomal subunit"
    }
}

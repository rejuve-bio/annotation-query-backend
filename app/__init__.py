import json
from app.constants import GRAPH_INFO_PATH

#load the json that holds the count for the edges
graph_info = json.load(open(GRAPH_INFO_PATH))
import json
import os

# Define the absolute path to the JSON file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GRAPH_INFO_PATH = os.path.join(BASE_DIR, '../../Data/count_info.json')

def heuristic_sort(requests, node_map):
    """
    Sorts the predicates based on their properties and counts.
    """
    graph_info = json.load(open(GRAPH_INFO_PATH))
    predicates = requests['predicates']

    not_unique = {'associated_with', 'expressed_in'}

    def has_properties(node_id):
        node = node_map.get(node_id, {})
        return bool(node.get('properties'))

    def get_count(predicate):
        predicate_type = predicate['type'].replace(" ", "_").lower()
        if predicate_type in not_unique:
            predicate_type = f"{predicate['source']}_{predicate_type}_{predicate['target']}"
        return graph_info.get(predicate_type, {}).get('count', 0)

    def predicate_sort_key(predicate):
        source_has_props = has_properties(predicate['source'])
        target_has_props = has_properties(predicate['target'])
        has_any_props = source_has_props or target_has_props
        count = get_count(predicate)

        return (-int(has_any_props), -count)

    requests['predicates'] = sorted(predicates, key=predicate_sort_key)
    return requests

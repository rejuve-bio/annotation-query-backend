import json
import os

def heuristic_sort(requests, node_map):
    """
    Sorts the predicates based on their properties and counts.
    Priority Hierarchy:
    1. Property key is exactly 'id'
    2. Property key contains 'name' (e.g., 'gene_name', 'transcript_name')
    3. Any other property
    4. No properties
    """
    from app import graph_info
    predicates = requests['predicates']
    not_unique = {'associated_with', 'expressed_in'}

    def get_node_priority_score(node_id):
        """
        Returns a score (lower is better) based on property keys.
        """
        node = node_map.get(node_id, {})
        props = node.get('properties')

        # Priority 4: If properties is None or empty dict
        if not props:
            return 3

        # Priority 1: Exact property key 'id'
        if 'id' in props:
            return 0
        
        # Priority 2: Any key containing the substring 'name'
        # This covers 'gene_name', 'transcript_name', etc.
        if any('name' in key.lower() for key in props.keys()):
            return 1
            
        # Priority 3: Just property (generic)
        return 2

    def get_count(predicate):
        predicate_type = predicate['type'].replace(" ", "_").lower()
        if predicate_type in not_unique:
            predicate_type = f"{predicate['source']}_{predicate_type}_{predicate['target']}"
        return graph_info.get(predicate_type, {}).get('count', 0)

    def predicate_sort_key(predicate):
        # We evaluate both source and target.
        # We take the BEST (lowest) score between the two nodes.
        source_score = get_node_priority_score(predicate['source'])
        target_score = get_node_priority_score(predicate['target'])
        
        best_score = min(source_score, target_score)
        count = get_count(predicate)
        
        # Tuple sort: Primary (Priority Score), Secondary (Count)
        return (best_score, count)

    requests['predicates'] = sorted(predicates, key=predicate_sort_key)
    return requests
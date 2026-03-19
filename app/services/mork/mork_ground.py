def _edge_label_from_tuple(match):
    if not match:
        return 'unknown'

    if len(match) >= 7:
        property_key = match[0]
        inner_predicate = match[1] if len(match) > 1 else None
        if isinstance(property_key, str) and property_key.endswith('_id') and inner_predicate:
            return inner_predicate

    return match[0]

def get_total_counts(graph_data):
    """
    Calculate the total number of nodes and edges.

    Args:
        graph_data (dict): The input graph data containing nodes and edges.

    Returns:
        dict: A dictionary with total node count and edge count.
    """
    if isinstance(graph_data, list):
        node_count = 0
        edge_count = 0
        has_dict_items = any(isinstance(item, dict) for item in graph_data)

        if has_dict_items:
            for item in graph_data:
                if not isinstance(item, dict):
                    continue
                data = item.get('data', {}) if isinstance(item.get('data', {}), dict) else {}
                is_edge = False
                if 'predicate' in item or ('source' in item and 'target' in item):
                    is_edge = True
                if 'label' in data or ('source' in data and 'target' in data):
                    is_edge = True
                if is_edge:
                    edge_count += 1
                else:
                    node_count += 1
            return {"node_count": node_count, "edge_count": edge_count}

        try:
            from app.services.metta.metta_seralizer import metta_seralizer
            tuples = metta_seralizer(graph_data)
        except Exception:
            tuples = []

        for match in tuples:
            if len(match) >= 5:
                edge_count += 1
            elif len(match) >= 2:
                node_count += 1

        return {"node_count": node_count, "edge_count": edge_count}

    if not isinstance(graph_data, dict):
        return {"node_count": 0, "edge_count": 0}

    node_count = len(graph_data.get('nodes', []))
    edge_count = len(graph_data.get('edges', []))
    return {"node_count": node_count, "edge_count": edge_count}


def get_count_by_label(graph_data):
    """
    Calculate the count of nodes and edges grouped by their labels.

    Args:
        graph_data (dict): The input graph data containing nodes and edges.

    Returns:
        dict: A dictionary with node counts and edge counts grouped by labels.
    """
    node_count_by_label = {}
    edge_count_by_label = {}

    if isinstance(graph_data, list):
        has_dict_items = any(isinstance(item, dict) for item in graph_data)

        if has_dict_items:
            for item in graph_data:
                if not isinstance(item, dict):
                    continue
                data = item.get('data', {}) if isinstance(item.get('data', {}), dict) else {}
                is_edge = False
                if 'predicate' in item or ('source' in item and 'target' in item):
                    is_edge = True
                if 'label' in data or ('source' in data and 'target' in data):
                    is_edge = True
                if is_edge:
                    label = data.get('label') or item.get('predicate') or 'unknown'
                    edge_count_by_label[label] = edge_count_by_label.get(label, 0) + 1
                else:
                    label = data.get('type', 'unknown')
                    node_count_by_label[label] = node_count_by_label.get(label, 0) + 1
        else:
            try:
                from app.services.metta.metta_seralizer import metta_seralizer
                tuples = metta_seralizer(graph_data)
            except Exception:
                tuples = []

            for match in tuples:
                if len(match) >= 5:
                    label = _edge_label_from_tuple(match)
                    edge_count_by_label[label] = edge_count_by_label.get(label, 0) + 1
                elif len(match) >= 2:
                    label = match[0]
                    node_count_by_label[label] = node_count_by_label.get(label, 0) + 1
    else:
        nodes = graph_data.get('nodes', []) if isinstance(graph_data, dict) else []
        for node in nodes:
            label = node['data'].get('type', 'unknown')
            node_count_by_label[label] = node_count_by_label.get(label, 0) + 1

    # Convert node counts to the desired format
    node_count_by_label_list = [
        {"label": label, "count": count} for label, count in node_count_by_label.items()
    ]

    if not isinstance(graph_data, list):
        edges = graph_data.get('edges', []) if isinstance(graph_data, dict) else []
        for edge in edges:
            label = edge['data'].get('label', 'unknown')
            edge_count_by_label[label] = edge_count_by_label.get(label, 0) + 1

    # Convert edge counts to the desired format
    edge_count_by_label_list = [
        {"label": label, "count": count} for label, count in edge_count_by_label.items()
    ]

    return {
        "node_count_by_label": node_count_by_label_list,
        "edge_count_by_label": edge_count_by_label_list,
    }

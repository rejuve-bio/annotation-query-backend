import copy
import hashlib
import json
from collections import deque

def canonicalize_graph(request):
    """
    Deterministically renames node_id and predicate source/target/predicate_id
    to stable ids (e.g. n0, n1, ...; p0, p1, ...).
    Returns a deep copy of the request with canonicalized IDs, and a map from old_id to new_id.
    Pathological symmetric cases may still collide, but this covers most real graphs.
    """
    req_copy = copy.deepcopy(request)
    nodes = req_copy.get('nodes', [])
    predicates = req_copy.get('predicates', [])
    logic = req_copy.get('logic')

    # 1. Compute basic sort key for each node. Logic conditions on a node are
    #    part of its key, so nodes that differ only in 'logic' still get a
    #    stable order (and equivalent requests the same fingerprint).
    def get_node_sort_key(node):
        node_type = node.get('type', '')
        node_id_val = str(node.get('id', ''))
        props = node.get('properties', {})
        canon_props_str = json.dumps(props, sort_keys=True)
        if not logic:
            return (node_type, node_id_val, canon_props_str)
        return (node_type, node_id_val, canon_props_str, _logic_node_signature(logic, node.get('node_id')))

    # Attach old_id and sort key
    for i, node in enumerate(nodes):
        node['_old_id'] = node.get('node_id')
        node['_sort_key'] = get_node_sort_key(node)
        node['_orig_idx'] = i

    # 2. Build adjacency for BFS
    adj = {node['_old_id']: [] for node in nodes}
    for p in predicates:
        source = p.get('source')
        target = p.get('target')
        if source in adj and target in adj:
            # We treat undirected for BFS distance
            adj[source].append(target)
            adj[target].append(source)

    # 3. BFS to compute distance from "anchored" nodes
    # Anchored nodes have a non-empty 'id' property.
    anchored_nodes = [n for n in nodes if n.get('id', '') != '']
    anchored_nodes.sort(key=lambda x: str(x.get('id', '')))

    distances = {n['_old_id']: float('inf') for n in nodes}
    queue = deque()

    for i, n in enumerate(anchored_nodes):
        distances[n['_old_id']] = 0
        queue.append((n['_old_id'], 0))

    while queue:
        curr, dist = queue.popleft()
        for neighbor in adj[curr]:
            if distances[neighbor] > dist + 1:
                distances[neighbor] = dist + 1
                queue.append((neighbor, dist + 1))

    # 4. Final sort: Sort by sort_key, then BFS distance, then original index
    nodes.sort(key=lambda n: (n['_sort_key'], distances[n['_old_id']], n['_orig_idx']))

    # 5. Assign new IDs
    old_to_new_node = {}
    for i, node in enumerate(nodes):
        new_id = f"n{i}"
        old_to_new_node[node['_old_id']] = new_id
        node['node_id'] = new_id
        # Clean up internal fields
        del node['_old_id']
        del node['_sort_key']
        del node['_orig_idx']

    # 6. Update predicates
    for p in predicates:
        if p.get('source') in old_to_new_node:
            p['source'] = old_to_new_node[p['source']]
        if p.get('target') in old_to_new_node:
            p['target'] = old_to_new_node[p['target']]

    # 7. Renumber predicates based on their source/target/type (already canonicalized).
    #    With logic, the operator of the predicate's logic group is part of the
    #    key, so "NOT p" and a plain p are ordered deterministically.
    predicate_operator = _logic_predicate_operators(logic) if logic else {}

    def get_predicate_sort_key(p):
        key = (p.get('source', ''), p.get('target', ''), p.get('type', ''), json.dumps(p.get('properties', {}), sort_keys=True))
        if not logic:
            return key
        return key + (predicate_operator.get(p.get('predicate_id'), ''),)

    predicates.sort(key=get_predicate_sort_key)

    old_to_new_predicate = {}
    for i, p in enumerate(predicates):
        # With logic, validation guarantees predicate ids are unique.
        old_to_new_predicate[p.get('predicate_id')] = f"p{i}"
        p['predicate_id'] = f"p{i}"

    req_copy['nodes'] = nodes
    req_copy['predicates'] = predicates
    if logic:
        req_copy['logic'] = _canonical_logic(logic, old_to_new_node, old_to_new_predicate)

    return req_copy, old_to_new_node


def _logic_node_signature(logic, node_id):
    """Describe the logic conditions on one node, without ids, as a stable string."""
    groups = [_strip_node_ids(child) for child in logic.get('children', []) if node_id in _group_node_ids(child)]
    return json.dumps(sorted(json.dumps(g, sort_keys=True) for g in groups))


def _group_node_ids(group):
    if 'nodes' in group:
        return {group['nodes']['node_id']}
    ids = set()
    for child in group.get('children', []):
        ids |= _group_node_ids(child)
    return ids


def _strip_node_ids(group):
    if 'nodes' in group:
        return {'operator': group['operator'], 'properties': group['nodes']['properties']}
    if 'children' in group:
        return {'operator': group['operator'], 'children': [_strip_node_ids(c) for c in group['children']]}
    return {'operator': group['operator'], 'predicates': len(group['predicates'])}


def _logic_predicate_operators(logic):
    """predicate_id -> operator of the logic group that refers to it."""
    return {pid: child['operator'] for child in logic.get('children', []) if 'predicates' in child
            for pid in child['predicates']}


def _canonical_logic(group, old_to_new_node, old_to_new_predicate):
    """Rename node and predicate references in a (validated) logic group, and
    sort its order-independent parts so equivalent requests look the same.

    AND / OR / NOT are all order-independent in their parts (NOT means "none
    of them"), so children, predicate ids and property values are sorted.
    """
    out = {'operator': group['operator']}
    if 'nodes' in group:
        out['nodes'] = {
            'node_id': old_to_new_node.get(group['nodes']['node_id'], group['nodes']['node_id']),
            'properties': {name: sorted(values) for name, values in sorted(group['nodes']['properties'].items())},
        }
    elif 'predicates' in group:
        out['predicates'] = sorted(old_to_new_predicate.get(pid, pid) for pid in group['predicates'])
    else:
        children = [_canonical_logic(c, old_to_new_node, old_to_new_predicate) for c in group['children']]
        out['children'] = sorted(children, key=lambda c: json.dumps(c, sort_keys=True))
    return out

def query_fingerprint(canonical_request, species, data_source, limit, node_only, properties, db_type=None):
    """
    Computes a stable SHA-256 hash of the normalized request components.
    """
    # Extract only the parts that change results
    payload = {
        "nodes": canonical_request.get('nodes', []),
        "predicates": canonical_request.get('predicates', []),
        "species": species,
        "data_source": data_source,
        "limit": limit,
        "node_only": node_only,
        "properties": properties,
        "db_type": db_type,
    }
    # Only when present, so fingerprints of requests without logic (and the
    # annotations already stored under them) are unchanged.
    if canonical_request.get('logic'):
        payload["logic"] = canonical_request['logic']

    # Strip annotation_id and question if they somehow made it in
    if 'annotation_id' in payload:
        del payload['annotation_id']
    if 'question' in payload:
        del payload['question']

    payload_str = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(payload_str.encode('utf-8')).hexdigest()

from typing import Dict, Set, List
import hashlib
import json
import uuid

class Connection:
    def __init__(self, is_source: bool):
        self.is_source = is_source
        self.nodes: Set[str] = set()

class ConnectionWithType:
    def __init__(self, is_source: bool, nodes: List[str], edge_type: str):
        self.is_source = is_source
        self.nodes = sorted(nodes)
        self.type = edge_type

EdgeTypeToConnectionMapping = Dict[str, Connection]
NodeToConnectionsMap = Dict[str, EdgeTypeToConnectionMapping]

def get_node_to_connections_map(annotation):
    node_to_connections: NodeToConnectionsMap = {}

    def add_to_map(edge, node: str):
        node_id = edge["data"][node]
        label = edge["data"]["label"]
        other_node = edge["data"]["target"] if node == "source" else edge["data"]["source"]

        if node_id not in node_to_connections:
            node_to_connections[node_id] = {}
        
        if label not in node_to_connections[node_id]:
            node_to_connections[node_id][label] = Connection(is_source=(node == "source"))
        
        node_to_connections[node_id][label].nodes.add(other_node)

    for edge in annotation["edges"]:
        add_to_map(edge, "source")
        add_to_map(edge, "target")

    return node_to_connections

def collapse_nodes(annotation):
    node_map = get_node_to_connections_map(annotation)
    map_string: Dict[str, Dict] = {}
    ids: Dict[str, str] = {}
    
    for node_id, connections in node_map.items():
        connections_array = [ConnectionWithType(conn.is_source, list(conn.nodes), label)
                             for label, conn in connections.items()]
        connections_array.sort(key=lambda x: json.dumps(x.__dict__, sort_keys=True))
        
        connections_hash = hashlib.sha256(json.dumps([c.__dict__ for c in connections_array], sort_keys=True).encode()).hexdigest()
        
        if connections_hash in map_string:
            map_string[connections_hash]["nodes"].append(node_id)
        else:
            map_string[connections_hash] = {"connections": connections_array, "nodes": [node_id]}
        
        ids[node_id] = connections_hash
    
    new_graph = {"edges": [], "nodes": []}
    
    for group_id, group in map_string.items():
        node = next((n for n in annotation["nodes"] if n["data"]["id"] in group["nodes"]), None)
        
        if node:
            node_type = node["data"]["type"]
            node_name = node["data"]["name"] if len(group["nodes"]) == 1 else f"{len(group['nodes'])} {node_type} nodes"
            new_node = {"data": {"id": group_id, "type": node_type, "name": node_name, "nodes": group["nodes"]}}
            new_graph["nodes"].append(new_node)
        
        added = set()
        edges = []
        
        for conn in group["connections"]:
            if conn.is_source:
                for n in conn.nodes:
                    other_node_id = ids.get(n)
                    edge_id = str(uuid.uuid4())
                    edge_data = {"id": edge_id, "label": conn.type, "source": group_id, "target": other_node_id}
                    edge_key = f"{edge_data['label']}{edge_data['source']}{edge_data['target']}"
                    
                    if edge_key not in added:
                        added.add(edge_key)
                        edges.append({"data": edge_data})
        
        new_graph["edges"].extend(edges)
    
    return new_graph

def group_into_parents(annotation):
    node_map = get_node_to_connections_map(annotation)
    parent_map = {}
    
    for node_id, connections in node_map.items():
        for edge_type, conn in connections.items():
            if len(conn.nodes) < 2:
                continue
            key = ",".join(sorted(conn.nodes))
            
            if key not in parent_map:
                parent_map[key] = {
                    "id": str(uuid.uuid4()),
                    "node": node_id,
                    "label": edge_type,
                    "count": len(conn.nodes),
                    "is_source": conn.is_source
                }
    
    keys = list(parent_map.keys())
    invalid_groups = [k for k in keys if any(
        k != a and parent_map[a]["is_source"] == parent_map[k]["is_source"] and
        parent_map[a]["count"] > parent_map[k]["count"] and
        any(b in a for b in k.split(","))
        for a in keys
    )]
    
    for k in invalid_groups:
        del parent_map[k]
    
    parents = set()
    grouped_nodes = {}
    
    for node in annotation["nodes"]:
        node_count = 0
        for key, parent in parent_map.items():
            if node["data"]["id"] in key and parent["count"] > node_count:
                node["data"]["parent"] = parent["id"]
                node_count = parent["count"]
        
        parent_id = node["data"].get("parent")
        if parent_id:
            parents.add(parent_id)
            grouped_nodes.setdefault(parent_id, []).append(node)
    
    for key, entry in list(grouped_nodes.items()):
        if len(entry) < 2:
            parents.discard(key)
            for n in entry:
                n["data"].pop("parent", None)
    
    for p in parents:
        annotation["nodes"].append({"data": {"id": p, "type": "parent", "name": p}})
    
    edges = [e for e in annotation["edges"] if not any(
        parent["id"] in parents and
        parent["node"] == (e["data"]["source"] if parent["is_source"] else e["data"]["target"]) and
        parent["label"] == e["data"]["label"]
        for parent in parent_map.values()
    )]
    
    for parent in parent_map.values():
        if parent["id"] in parents:
            edges.append({
                "data": {
                    "id": str(uuid.uuid4()),
                    "source": parent["node"] if parent["is_source"] else parent["id"],
                    "target": parent["id"] if parent["is_source"] else parent["node"],
                    "label": parent["label"]
                }
            })
    
    annotation["edges"] = edges

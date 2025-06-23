from nanoid import generate
import json
import hashlib
from app.lib.utils import extract_middle
import networkx as nx
from networkx.readwrite import json_graph
class Graph:
    def __init__(self):
        pass

    def group_graph(self, graph):
        graph = self.collapse_node_nx(graph)
        graph = self.group_into_parents(graph)
        return graph

    def group_node_only(self, graph, request):
        nodes = graph['nodes']
        new_graph = {'nodes': [], 'edges': []}
        
        node_map_by_label = {}
        
        request_nodes = request['nodes']
        
        for node in request_nodes:
            node_map_by_label[node['type']] = []
            
        for node in nodes:
            if node['data']['type'] in node_map_by_label:
                node_map_by_label[node['data']['type']].append(node)
        
        for node_type, nodes in node_map_by_label.items():
            name = f"{len(nodes)} {node_type} nodes"
            new_node = {
                "data": {
                    "id": generate(),
                    "type": node_type,
                    "name": name,
                    "nodes": nodes
                }
            }
            new_graph['nodes'].append(new_node)
        return new_graph

    def get_node_to_connections_map(self, graph):
        '''
        Build a mapping from node IDs to a dictionary of connections.
        Each connection is keyed by the edge label and stores whether
        the node is the source, and a set of node IDs it connects to.
        '''
        node_to_id_map = {node["data"]["id"]: node["data"] for node in graph.get("nodes", [])}
        node_mapping = {}

        def add_to_map(edge, node_role):
            node_key = edge["data"][node_role]
            connections = node_mapping.get(node_key, {})
            edge_id = edge["data"]["edge_id"]
            if edge_id not in connections:
                connections[edge_id] = {"is_source": (
                    node_role == "source"), "nodes": set()}
            # Determine the “other” node for this edge.
            other_node = edge["data"]["target"] if node_role == "source"\
                else edge["data"]["source"]
            connections[edge_id]["nodes"].add(other_node)
            node_mapping[node_key] = connections

        for edge in graph.get("edges", []):
            add_to_map(edge, "source")
            add_to_map(edge, "target")

        return node_mapping, node_to_id_map

    def collapse_nodes(self, graph):
        """
        Collapse nodes that have the same connectivity.
        Returns a new graph where groups of nodes have been merged into a single node.
        """
        node_mapping, node_to_id_map = self.get_node_to_connections_map(graph)
        map_string = {}  # Maps a hash to a group { connections, nodes }
        ids = {}         # Maps each original node ID to its group hash

        # Group nodes by their connection signature.
        for node_id, connections in node_mapping.items():
            connections_array = []
            for edge_id, connection in connections.items():
                # Sort the list of connected node IDs for consistency.
                nodes_list = sorted(list(connection["nodes"]))
                connections_array.append({
                    "nodes": nodes_list,
                    "edge_id": edge_id,
                    "is_source": connection["is_source"]
                })
            # Sort the connections array using its JSON representation.
            connections_array_sorted = sorted(
                connections_array, key=lambda x: (x["is_source"], x["edge_id"], x["nodes"])
            )
            json_str = json.dumps(connections_array_sorted, sort_keys=True)
            connections_hash = hashlib.sha256(
                json_str.encode("utf-8")).hexdigest()

            if connections_hash in map_string:
                map_string[connections_hash]["nodes"].append(node_to_id_map[node_id])
            else:
                map_string[connections_hash] = {
                    "connections": connections_array,
                    "nodes": [node_to_id_map[node_id]]
                }
            ids[node_id] = connections_hash

        new_graph = {"edges": [], "nodes": []}

        # For each group, create a new compound node and new edges.
        for group_hash, group in map_string.items():
            # Find a representative node from the original annotation
            rep_node = next((n for n in graph["nodes"]\
                if n["data"]["id"] in \
                    {node["id"] for node in group["nodes"]}), None)

            if rep_node is None:
                continue

            node_type = rep_node["data"]["type"]
            if len(group["nodes"]) == 1:
                name = rep_node["data"].get("name", rep_node["data"]["id"])
            else:
                name = f"{len(group['nodes'])} {node_type} nodes"

            new_node = {
                "data": {
                    "id": group_hash,
                    "type": node_type,
                    "name": name,
                    "nodes": group["nodes"]
                }
            }
            new_graph["nodes"].append(new_node)

            # Create new edges for connections that are marked as a source.
            added = set()
            new_edges = []
            for connection in group["connections"]:
                if connection["is_source"]:
                    for n in connection["nodes"]:
                        other_node_id = ids.get(n)
                        label = extract_middle(connection["edge_id"])
                        edge = {
                            "data": {
                                "id": generate(),
                                "edge_id": connection["edge_id"],
                                "label": label,
                                "source": group_hash,  # current group node is the source
                                "target": other_node_id
                            }
                        }
                        # Use a string key to avoid duplicate edges.
                        key = f"{edge['data']['edge_id']}{edge['data']['source']}{edge['data']['target']}"
                        if key in added:
                            continue
                        added.add(key)
                        new_edges.append(edge)
            new_graph["edges"].extend(new_edges)
        return new_graph

    def collapse_node_nx(self, graph):
        G = self.build_graph_nx(graph)
        node_to_id_map = {node["data"]["id"]: node["data"] for node in graph.get("nodes", [])}
        signatures = {}

        # Graph traversal for in/out edges
        for node in G.nodes():
            if isinstance(G, nx.DiGraph):
                in_edges = [(u, data['edge_id']) for u, _, data in G.in_edges(node, data=True)]
                out_edges = [(v, data['edge_id']) for _, v, data in G.out_edges(node, data=True)]
                signature = (tuple(sorted(in_edges)), tuple(sorted(out_edges)))
            else:
                edges = [(nbr, data['edge_id']) for _, nbr, data in G.edges(node, data=True)]
                signature = tuple(sorted(edges))
                
            signatures.setdefault(signature, []).append(node)
        
        # print("Signuature finished: ", signatures)
        # Merge nodes based on their signatures
        for nodes in signatures.values():
            first_node = nodes[0]
            base_label = first_node.split(" ")[0]
            merged_id = generate()  # Generate a new unique ID for the merged node

            if len(nodes) == 1:
                name = first_node
            else:
                name = f'{len(nodes)} {base_label} nodes'
            
            other_nodes = []
            
            for single_node in nodes:
                nd = node_to_id_map[single_node]
                data = {
                    **nd
                }
                other_nodes.append(data)

            merged_attrs = {
                "type": base_label,
                "name": name,
                "nodes": other_nodes,
                "id": merged_id,
            }

            G.add_node(merged_id, **merged_attrs)
            
            #track collapsed nodes to connect 
            connected_nodes = set()
            # Redirect all connections to/from merged nodes
            for node in nodes:
                for u, _, data in G.in_edges(node, data=True):
                    if u not in nodes and u not in connected_nodes:
                        G.add_edge(u, merged_id, **data)
                        connected_nodes.add(u)
                for _, v, data in G.out_edges(node, data=True):
                    if v not in nodes and v not in connected_nodes:
                        G.add_edge(merged_id, v, **data)
                        connected_nodes.add(v)
                G.remove_node(node)
        graph = self.convert_to_graph_json(G)
        return graph

    def build_graph_nx(self, graph):
        G = nx.MultiDiGraph()
        
        # Create nodes
        nodes = graph['nodes']
        for node in nodes:
            G.add_node(node['data']['id'], **node)
            
        # Create edges
        edges = graph['edges']
        for edge in edges:
            G.add_edge(edge['data']['source'], edge['data']['target'], edge_id=edge['data']['edge_id'], label=edge['data']['label'], id=generate())

        return G
    
    def convert_to_graph_json(self, graph):
        graph_json = {"nodes": [], "edges": []}

        # build the nodes
        for node in graph.nodes():
            data = {
                "data": graph.nodes[node]  # Get the node's attributes here
            }
            graph_json['nodes'].append(data)

        # build the edges
        for u, v, data in graph.edges(data=True):
            edge = {
                "data": {
                    "source": u,
                    "target": v,
                    "id": data['id'], # Any edge attributes
                    "label": data['label'],
                    "edge_id": data['edge_id']
                }
            }
            graph_json['edges'].append(edge)

        return graph_json

    def group_into_parents(self, graph):
        """
        Group nodes into parents based on common incoming/outgoing edges.
        This creates compound (parent) nodes for groups of nodes
        that share identical edges.
        """
        # Create directed graph to capture edge relationships
        G = nx.DiGraph()
        
        # Add nodes with their data
        for node in graph.get("nodes", []):
            node_id = node["data"]["id"]
            G.add_node(node_id, **node["data"])
        
        # Add edges with their data
        for edge in graph.get("edges", []):
            edge_data = edge["data"]
            G.add_edge(edge_data["source"], edge_data["target"], **edge_data)
        
        # Build node_mapping: dict[node_id] = {edge_id: {is_source: bool, nodes: set}}
        node_mapping = {}
        for node in G.nodes:
            connections = {}
            # Process outgoing edges (node as source)
            for _, neighbor, data in G.out_edges(node, data=True):
                edge_id = data['edge_id']
                if edge_id not in connections:
                    connections[edge_id] = {"is_source": True, "nodes": set()}
                connections[edge_id]['nodes'].add(neighbor)
            
            # Process incoming edges (node as target)
            for predecessor, _, data in G.in_edges(node, data=True):
                edge_id = data['edge_id']
                if edge_id not in connections:
                    connections[edge_id] = {"is_source": False, "nodes": set()}
                connections[edge_id]['nodes'].add(predecessor)
            
            node_mapping[node] = connections
    
        # Maps a sorted, comma‐joined string of node IDs to parent info.
        parent_map = {}
    
        # Build an initial parent_map for connection records that involve two or more nodes.
        for node_id, connections in node_mapping.items():
            for edge_id, record in connections.items():
                if len(record["nodes"]) < 2:
                    continue
                key_nodes = sorted(list(record["nodes"]))
                key = ",".join(key_nodes)
                if key not in parent_map:
                    label = extract_middle(edge_id)
                    parent_map[key] = {
                        "id": generate(),
                        "node": node_id,
                        "edge_id": edge_id,
                        "label": label,
                        "count": len(record["nodes"]),
                        "is_source": record["is_source"]
                    }
    
        # Remove invalid groups.
        keys = list(parent_map.keys())
        invalid_groups = []
        for k in keys:
            parent_k = parent_map[k]
            for a in keys:
                if a == k:
                    continue
                parent_a = parent_map[a]
                if (parent_a["is_source"] == parent_k["is_source"] and
                        parent_a["count"] > parent_k["count"]):
                    # Compare the sets of node IDs.
                    if set(k.split(",")) & set(a.split(",")):
                        invalid_groups.append(k)
                        break
        for k in invalid_groups:
            parent_map.pop(k, None)
    
        # Assign each node to a parent group if applicable.
        parents = set()
        grouped_nodes = {}  # Maps parent id to list of nodes
        for n in graph["nodes"]:
            node_count = 0
            for key, parent in parent_map.items():
                # Check if the current node is in the group (using set membership).
                if n["data"]["id"] in key.split(",") and parent["count"] > node_count:
                    n["data"]["parent"] = parent["id"]
                    node_count = parent["count"]
            parent_id = n["data"].get("parent")
            if parent_id:
                parents.add(parent_id)
                grouped_nodes.setdefault(parent_id, []).append(n)
    
        # Remove groups that contain only one node.
        for parent_id, nodes in list(grouped_nodes.items()):
            if len(nodes) < 2:
                parents.discard(parent_id)
                for n in nodes:
                    n["data"]["parent"] = ""
                grouped_nodes.pop(parent_id, None)
    
        # Add new parent nodes to the annotation.
        for p in parents:
            graph["nodes"].append({
                "data": {
                    "id": p,
                    "type": "parent",
                    "name": p
                }
            })
    
        # Remove edges that point to nodes that have just been assigned a parent.
        new_edges = []
        for e in graph["edges"]:
            keep_edge = True
            for key, parent in parent_map.items():
                if parent["id"] not in parents:
                    continue
                # Determine which end of the edge to check.
                if parent["is_source"]:
                    edge_key = e["data"]["target"]
                    parent_node = e["data"]["source"]
                else:
                    edge_key = e["data"]["source"]
                    parent_node = e["data"]["target"]
    
                if (edge_key in key.split(",") and
                    parent["node"] == parent_node and
                        parent["edge_id"] == e["data"]["edge_id"]):
                    keep_edge = False
                    break
            if keep_edge:
                new_edges.append(e)
    
        # Add new edges that point to the newly created parent nodes.
        for key, parent in parent_map.items():
            if parent["id"] not in parents:
                continue
            if parent["is_source"]:
                source = parent["node"]
                target = parent["id"]
            else:
                source = parent["id"]
                target = parent["node"]
            new_edge = {
                "data": {
                    "id": generate(),
                    "source": source,
                    "target": target,
                    "label": parent["label"],
                    "edge_id": parent["edge_id"]
                }
            }
            new_edges.append(new_edge)
        graph["edges"] = new_edges
        return graph

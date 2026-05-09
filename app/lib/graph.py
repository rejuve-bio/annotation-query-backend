from nanoid import generate
import json
import hashlib
from app.lib.utils import extract_middle
import random
from copy import deepcopy
import networkx as nx
from networkx.readwrite import json_graph
from copy import deepcopy
import random
from networkx.algorithms.isomorphism import is_isomorphic

class Graph:
    def __init__(self):
        pass

    def group_graph(self, graph):
        graph = self.collapse_node_nx(graph)
        graph = self.group_into_parents(graph)
        return graph

    def collapse_node_nx_location(self, graph):
        """
        Group nodes and edges of a graph based on their cellular location.

         - Nodes with multiple locations are duplicated per location and linked
           with a `location_alias` edge.
         - Original edges are remapped to the chosen main duplicate node.
         - Nodes with the same location and identical in/out edge patterns
           are merged into a single meta-node.
         - Returns a simplified graph JSON with redundant nodes collapsed.
        """
        G = nx.DiGraph()
        node_to_id_map = {}
        original_id_to_main_id = {}

        for node_entry in graph.get("nodes", []):
            node_data = deepcopy(node_entry["data"])
            node_id = node_data["id"]
            locations = node_data.get("location", "")
            location_list = [loc.strip() for loc in locations.split(",") if loc.strip()] or [""]

            # Generate unique IDs per location
            dup_nodes = []
            for idx, location in enumerate(location_list):
                dup_data = deepcopy(node_data)
                dup_data["location"] = location
                dup_id = f"{node_id}_loc_{idx}" if len(location_list) > 1 else node_id
                dup_data["id"] = dup_id
                dup_nodes.append((dup_id, dup_data))

            # Choose a main node arbitrarily
            main_dup_id, main_data = random.choice(dup_nodes)
            main_data.pop("duplicate", None)  # Ensure no duplicate flag

            for dup_id, dup_data in dup_nodes:
                if dup_id != main_dup_id:
                    dup_data["duplicate"] = True
                    G.add_node(dup_id, data=dup_data)
                    # Connect to main node
                    G.add_edge(dup_id, main_dup_id, id=generate(), edge_id="location_alias", label="location_alias")
                else:
                    G.add_node(dup_id, data=dup_data)

                node_to_id_map[dup_id] = dup_data

            # Map original ID to selected main node
            original_id_to_main_id[node_id] = main_dup_id

        # Add edges with remapped node IDs
        for edge in graph.get("edges", []):
            src = original_id_to_main_id.get(edge["data"]["source"], edge["data"]["source"])
            tgt = original_id_to_main_id.get(edge["data"]["target"], edge["data"]["target"])
            edge_data = edge["data"]
            G.add_edge(src, tgt, **edge_data)

        # Group nodes by (location, in_edges, out_edges)
        signatures = {}
        for node in G.nodes():
            node_data = G.nodes[node].get("data", {})
            location = node_data.get("location", "")
            in_edges = [(u, data['edge_id']) for u, _, data in G.in_edges(node, data=True)]
            out_edges = [(v, data['edge_id']) for _, v, data in G.out_edges(node, data=True)]
            signature = (location, tuple(sorted(in_edges)), tuple(sorted(out_edges)))
            signatures.setdefault(signature, []).append(node)

        # Collapse by signature
        for nodes in signatures.values():
            if len(nodes) == 1:
                continue

            base_label = G.nodes[nodes[0]]["data"]["id"].split(" ")[0]
            merged_id = generate()
            name = f'{len(nodes)} {base_label} nodes'
            other_nodes = [node_to_id_map[n] for n in nodes]

            merged_attrs = {
                "type": base_label,
                "name": name,
                "nodes": other_nodes,
                "id": merged_id,
            }

            G.add_node(merged_id, **merged_attrs)

            connected_nodes = set()
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

        return self.convert_to_graph_json(G)

    def group_node_only(self, graph, request):
        nodes = graph['nodes']
        new_graph = {'nodes': [], 'edges': []}

        node_map_by_label = {}

        request_nodes = request['nodes']

        for node in request_nodes:
            node_map_by_label[node['type']] = []

        for node in nodes:
            if node['data']['type'] in node_map_by_label:
                node_map_by_label[node['data']['type']].append(node['data'])

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
            rep_node = rep_node = next((n for n in graph["nodes"]\
                if n["data"]["id"] in \
                    {node["id"] for node in group["nodes"]}), None)

            if rep_node is None:
                continue

            node_type = rep_node["data"]["type"]
            if len(group["nodes"]) == 1:
                name = rep_node["data"]["name"]
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
        node_to_id_map = {}
        for node in graph.get("nodes", []):
            data = node.get("data") if isinstance(node, dict) and "data" in node else node
            if not isinstance(data, dict):
                continue
            node_id = data.get("id")
            if not node_id:
                continue
            node_to_id_map[node_id] = data
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
                node_data = G.nodes[first_node].get("data", G.nodes[first_node])
                name = node_data.get("name") or node_data.get("id", first_node)
            else:
                name = f'{len(nodes)} {base_label} nodes'

            other_nodes = []

            for single_node in nodes:
                nd = node_to_id_map.get(single_node)
                if not nd:
                    continue
                other_nodes.append({**nd})

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


    def convert_to_graph_json(self, graph, allow_data=True):
        """
        Convert a networkx graph to a json representation.
        """
        graph_json = {"nodes": [], "edges": []}

        # build the nodes
        for node in graph.nodes():
            if allow_data:
                data = {"data": graph.nodes[node]}
            else:
                data = graph.nodes[node]
            graph_json['nodes'].append(data)

        # build the edges
        for u, v, data in graph.edges(data=True):
            if allow_data:
                edge = {
                    "data": {
                        "source": u,
                        "target": v,
                        "id": data['id'],
                        "label": data['label'],
                        "edge_id": data['edge_id']
                    }
                }
            else:
                edge = {
                    "source": u,
                    "target": v,
                    "id": data['id'],
                    "label": data['label'],
                    "edge_id": data['edge_id']
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

    def collapse_node_nx_location(self, graph):
        G = nx.DiGraph()
        node_to_id_map = {}
        original_id_to_main_id = {}

        for node_entry in graph.get("nodes", []):
            node_data = deepcopy(node_entry["data"])
            node_id = node_data["id"]
            locations = node_data.get("location", "")
            location_list = [loc.strip() for loc in locations.split(",") if loc.strip()] or [""]

            # Generate unique IDs per location
            dup_nodes = []
            for idx, location in enumerate(location_list):
                dup_data = deepcopy(node_data)
                dup_data["location"] = location
                dup_id = f"{node_id}_loc_{idx}" if len(location_list) > 1 else node_id
                dup_data["id"] = dup_id
                dup_nodes.append((dup_id, dup_data))

            # Choose a main node arbitrarily
            main_dup_id, main_data = random.choice(dup_nodes)
            main_data.pop("duplicate", None)  # Ensure no duplicate flag

            for dup_id, dup_data in dup_nodes:
                if dup_id != main_dup_id:
                    dup_data["duplicate"] = True
                    G.add_node(dup_id, data=dup_data)
                    # Connect to main node
                    G.add_edge(dup_id, main_dup_id, id=generate(), edge_id="location_alias", label="location_alias")
                else:
                    G.add_node(dup_id, data=dup_data)

                node_to_id_map[dup_id] = dup_data

            # Map original ID to selected main node
            original_id_to_main_id[node_id] = main_dup_id

        # Add edges with remapped node IDs
        for edge in graph.get("edges", []):
            src = original_id_to_main_id.get(edge["data"]["source"], edge["data"]["source"])
            tgt = original_id_to_main_id.get(edge["data"]["target"], edge["data"]["target"])
            edge_data = edge["data"]
            G.add_edge(src, tgt, **edge_data)

        # Group nodes by (location, in_edges, out_edges)
        signatures = {}
        for node in G.nodes():
            node_data = G.nodes[node].get("data", {})
            location = node_data.get("location", "")
            in_edges = [(u, data['edge_id']) for u, _, data in G.in_edges(node, data=True)]
            out_edges = [(v, data['edge_id']) for _, v, data in G.out_edges(node, data=True)]
            signature = (location, tuple(sorted(in_edges)), tuple(sorted(out_edges)))
            signatures.setdefault(signature, []).append(node)

        # Collapse by signature
        for nodes in signatures.values():
            if len(nodes) == 1:
                continue

            base_label = G.nodes[nodes[0]]["data"]["id"].split(" ")[0]
            merged_id = generate()
            name = f'{len(nodes)} {base_label} nodes'
            other_nodes = [node_to_id_map[n] for n in nodes]

            merged_attrs = {
                "type": base_label,
                "name": name,
                "nodes": other_nodes,
                "id": merged_id,
            }

            G.add_node(merged_id, **merged_attrs)

            connected_nodes = set()
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

        return self.convert_to_graph_json(G, allow_data=False)

    def break_grouping(self, graph):
        nodes = graph['nodes']
        edges = graph['edges']

        # filter out the parents
        parent_edges = {}

        for node in nodes:
            if node['data']['type'] == 'parent':
                parent_edges[node['data']['id']] = []

        for node in nodes:
            if 'parent' in node['data'] and node['data']['type'] == 'protein':
                parent_edges[node['data']['parent']].append(node['data']['id'])

        new_edge = []

        for i, edge in enumerate(edges):
            if edge['data']['source'] in parent_edges:
                for child in parent_edges[edge['data']['source']]:
                    new_edge.append({
                        "data": {
                            "source": child,
                            "target": edge['data']['target'],
                            "label": edge['data']['label'],
                            "edge_id": edge['data']['edge_id'],
                            "id": generate()
                        }
                    })
            elif edge['data']['target'] in parent_edges:
                for child in parent_edges[edge['data']['target']]:
                    new_edge.append({
                        "data": {
                            "source": edge['data']['source'],
                            "target": child,
                            "label": edge['data']['label'],
                            "edge_id": edge['data']['edge_id'],
                            "id": generate()
                        }
                    })
            else:
                new_edge.append({
                    "data": {
                        "source": edge['data']['source'],
                        "target": edge['data']['target'],
                        "label": edge['data']['label'],
                        "edge_id": edge['data']['edge_id'],
                        "id": generate()
                    }
                })

        node_to_edge_relationship = {}

        inital_node_map = {}

        for node in nodes:
            if node['data']['id'] not in inital_node_map:
                inital_node_map[node['data']['id']] = node

        for edge in new_edge:
            source = edge['data']['source']
            target = edge['data']['target']
            label = edge['data']['label']

            if source in inital_node_map and target in inital_node_map:
                source_nodes = []
                target_nodes = []

                if inital_node_map[source]['data']['type'] != 'parent':
                    for single_node in inital_node_map[source]['data']['nodes']:
                        source_nodes.append(single_node['id'])

                if inital_node_map[target]['data']['type'] != 'parent':
                    for single_node in inital_node_map[target]['data']['nodes']:
                        target_nodes.append(single_node['id'])

                for source_node in source_nodes:
                    for target_node in target_nodes:
                        key = f"{source_node}_{label}_{target_node}"
                        node_to_edge_relationship[key] = {
                            'source': source_node,
                            'label': label,
                            'target': target_node
                        }

        response = {"nodes": [], "edges": []}

        for key, value in node_to_edge_relationship.items():
            edge_id_arr = key.split(' ')
            middle_arr = edge_id_arr[1].split('_')
            middle = '_'.join(middle_arr[1:len(middle_arr)])
            edge_id = f'{edge_id_arr[0]}_{middle}'
            response['edges'].append({
                'data': {
                    'id': generate(),
                    'source': value['source'],
                    'target': value['target'],
                    'label': value['label'],
                    'edge_id': edge_id
                }
            })

        for node in nodes:
            if node['data']['type'] != "parent":
                for single_node in node['data']['nodes']:
                    response['nodes'].append({
                        'data': {
                            **single_node
                        }
                    })

        return response

    def build_graph_nx(self, graph):
        G = nx.MultiDiGraph()

        # Create nodes
        nodes = graph['nodes']
        for node in nodes:
            G.add_node(node['data']['id'], **node['data'])

        # Create edges
        edges = graph['edges']
        for edge in edges:
            G.add_edge(edge['data']['source'], edge['data']['target'], edge_id=edge['data']['edge_id'], label=edge['data']['label'], id=generate())

        return G

    def build_subgraph_nx(self, graph):
        # Identify connected components
        connected_components = list(nx.weakly_connected_components(graph))

        # Create subgraph objects
        subgraphs = []
        for component in connected_components:
            subgraph = graph.subgraph(component).copy()
            subgraphs.append(subgraph)

        return subgraphs

    def diff_graph_structures(self, G1, G2):
        return not is_isomorphic(G1, G2)

    def diff_graphs_node_and_edges(self, G1, G2):
        added_nodes = set(G2.nodes()) - set(G1.nodes())
        removed_nodes = set(G1.nodes()) - set(G2.nodes())
        edges1 = {data.get("edge_id", (u, v)) for u, v, data in G1.edges(data=True)}
        edges2 = {data.get("edge_id", (u, v)) for u, v, data in G2.edges(data=True)}
        added_edges = edges2 - edges1
        removed_edges = edges1 - edges2
        return {
            "structurally_different": True,
            "added_nodes": added_nodes,
            "removed_nodes": removed_nodes,
            "added_edges": added_edges,
            "removed_edges": removed_edges
        }

    def merge_view(self, G1, G2, resolve_conflicts="mark", handle_reverse_edges=True):
        """
        Merge two graphs into one.
        :param G1: First NetworkX MultiDiGraph
        :param G2: Second NetworkX MultiDiGraph
        :param resolve_conflicts: "mark" | "prefer_G1" | "prefer_G2"
            - "mark": Flag conflicts and store both versions
            - "prefer_G1": Use G1's version when conflicts exist
            - "prefer_G2": Use G2's version when conflicts exist
        :param handle_reverse_edges: If True, detect reverse edges (u->v vs v->u) and mark them
        :return: (merged_graph, conflicts_list)
        """
        merged = nx.MultiDiGraph()
        conflicts = []

        # ---- Merge Nodes ----
        all_nodes = set(G1.nodes()) | set(G2.nodes())
        
        for node in all_nodes:
            if node in G1.nodes() and node in G2.nodes():
                n1, n2 = G1.nodes[node], G2.nodes[node]

                if n1 != n2:
                    # Conflict: node exists in both with different attributes
                    if resolve_conflicts == "mark":
                        merged.add_node(node, **{
                            **n1,
                            "conflict": True,
                            "origin": "both",
                            "G1_data": n1,
                            "G2_data": n2
                        })
                        conflicts.append({
                            "type": "node_conflict",
                            "id": node,
                            "from": n1,
                            "to": n2
                        })
                    elif resolve_conflicts == "prefer_G1":
                        merged.add_node(node, **{**n1, "origin": "G1"})
                    elif resolve_conflicts == "prefer_G2":
                        merged.add_node(node, **{**n2, "origin": "G2"})
                else:
                    # No conflict: identical in both
                    merged.add_node(node, **{**n1, "origin": "both"})
            elif node in G1.nodes():
                # Only in G1
                merged.add_node(node, **{**G1.nodes[node], "origin": "G1"})
            else:
                # Only in G2
                merged.add_node(node, **{**G2.nodes[node], "origin": "G2"})

        # ---- Merge Edges ----
        # Track processed edges to avoid duplicates
        processed_edges = set()

        # Collect all unique (u, v) pairs from both graphs
        edge_pairs = set()
        for u, v, _ in G1.edges(data=True):
            edge_pairs.add((u, v))
        for u, v, _ in G2.edges(data=True):
            edge_pairs.add((u, v))

        # For each (u, v) pair, merge all edges (handles multiple edges)
        for u, v in edge_pairs:
            if (u, v) in processed_edges:
                continue

            edge_dict1 = G1.get_edge_data(u, v) if G1.has_edge(u, v) else {}
            edge_dict2 = G2.get_edge_data(u, v) if G2.has_edge(u, v) else {}

            # Get all edge keys (for MultiDiGraph)
            all_keys = set(edge_dict1.keys()) | set(edge_dict2.keys())

            for key in all_keys:
                data1 = edge_dict1.get(key)
                data2 = edge_dict2.get(key)

                if data1 and data2:
                    # Edge exists in both graphs
                    if data1 == data2:
                        # Duplicate edge with identical attributes - only add once
                        merged.add_edge(u, v, key=key, **{**data1, "origin": "both", "duplicate": True})
                        processed_edges.add((u, v))
                    else:
                        # Different attributes - conflict
                        if resolve_conflicts == "mark":
                            merged.add_edge(u, v, key=f"{key}_G1", **{
                                **data1,
                                "conflict": False,
                                "origin": "both",
                                "G1_data": data1,
                            })
                            merged.add_edge(u, v, key=f"{key}_G2", **{
                                **data2,
                                "conflict": True,
                                "origin": "both",
                                "G2_data": data2
                            })
                            conflicts.append({
                                "type": "edge_conflict",
                                "from": u,
                                "to": v,
                                "edge_from": data1,
                                "edge_to": data2
                            })
                        elif resolve_conflicts == "prefer_G1":
                            merged.add_edge(u, v, key=key, **{**data1, "origin": "G1"})
                        elif resolve_conflicts == "prefer_G2":
                            merged.add_edge(u, v, key=key, **{**data2, "origin": "G2"})
                elif data1:
                    # Only in G1
                    merged.add_edge(u, v, key=key, **{**data1, "origin": "G1"})
                else:
                    # Only in G2
                    merged.add_edge(u, v, key=key, **{**data2, "origin": "G2"})
                
                processed_edges.add((u, v))

        # ---- Handle Reverse Edges ----
        if handle_reverse_edges:
            reverse_conflicts = []
            
            # Check for reverse edge pairs (u->v in G1, v->u in G2)
            for u, v in processed_edges:
                reverse_pair = (v, u)
                
                if reverse_pair in processed_edges and (u, v) < (v, u):  # Check once
                    edge_dict_forward = merged.get_edge_data(u, v) if merged.has_edge(u, v) else {}
                    edge_dict_reverse = merged.get_edge_data(v, u) if merged.has_edge(v, u) else {}
                    
                    if edge_dict_forward and edge_dict_reverse:
                        # Get first edge of each for simplicity
                        edge_forward = list(edge_dict_forward.values())[0] if edge_dict_forward else None
                        edge_reverse = list(edge_dict_reverse.values())[0] if edge_dict_reverse else None
                        
                        if edge_forward and edge_reverse:
                            reverse_conflicts.append({
                                "type": "reverse_edge_detected",
                                "forward": {"from": u, "to": v, "label": edge_forward.get("label")},
                                "reverse": {"from": v, "to": u, "label": edge_reverse.get("label")},
                                "note": "Opposite direction edges detected - may represent bidirectional relationship"
                            })
            
            conflicts.extend(reverse_conflicts)

        return merged, conflicts

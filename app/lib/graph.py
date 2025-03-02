from nanoid import generate
import json
import hashlib


class Graph:
    def __init__(self):
        pass

    def group_graph(self, graph):
        graph = self.collapse_nodes(graph)
        graph = self.group_into_parents(graph)
        return graph

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
            label = edge["data"]["label"]
            if label not in connections:
                connections[label] = {"is_source": (
                    node_role == "source"), "nodes": set()}
            # Determine the “other” node for this edge.
            other_node = edge["data"]["target"] if node_role == "source"\
                else edge["data"]["source"]
            connections[label]["nodes"].add(other_node)
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
            for label, connection in connections.items():
                # Sort the list of connected node IDs for consistency.
                nodes_list = sorted(list(connection["nodes"]))
                connections_array.append({
                    "nodes": nodes_list,
                    "type": label,
                    "is_source": connection["is_source"]
                })
            # Sort the connections array using its JSON representation.
            connections_array_sorted = sorted(
                connections_array, key=lambda x: json.dumps(x, sort_keys=True))
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
                        edge = {
                            "data": {
                                "id": generate(),
                                "label": connection["type"],
                                "source": group_hash,  # current group node is the source
                                "target": other_node_id
                            }
                        }
                        # Use a string key to avoid duplicate edges.
                        key = f"{edge['data']['label']}{edge['data']['source']}{edge['data']['target']}"
                        if key in added:
                            continue
                        added.add(key)
                        new_edges.append(edge)
            new_graph["edges"].extend(new_edges)

        return new_graph

    def group_into_parents(self, graph):
        """
        Group nodes into parents based on common incoming/outgoing edges.
        This creates compound (parent) nodes for groups of nodes
        that share identical edges.
        """
        node_mapping, _ = self.get_node_to_connections_map(graph)
        # Maps a sorted, comma‐joined string of node IDs to parent info.
        parent_map = {}

        # Build an initial parent_map for connection records that involve two or more nodes.
        for node_id, connections in node_mapping.items():
            for label, record in connections.items():
                if len(record["nodes"]) < 2:
                    continue
                key_nodes = sorted(list(record["nodes"]))
                key = ",".join(key_nodes)
                if key not in parent_map:
                    parent_map[key] = {
                        "id": generate(),
                        "node": node_id,
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
                        parent["label"] == e["data"]["label"]):
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
                    "label": parent["label"]
                }
            }
            new_edges.append(new_edge)
        graph["edges"] = new_edges

        return graph

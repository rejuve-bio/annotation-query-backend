from collections import defaultdict
import sys
import os

# Add the parent directory of 'app' to sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from routes import data  # Now it should work

def check_subgraphs(data):
    # Extract nodes
    nodes = set(node["node_id"] for node in data["requests"]["nodes"])
    
    # Build adjacency list
    edges = defaultdict(set)
    for predicate in data["requests"]["predicates"]:
        source, target = predicate["source"], predicate["target"]
        edges[source].add(target)
        edges[target].add(source)
    
    # Keep only nodes that are part of some connection
    connected_nodes = set(edges.keys()) 
    print(edges) 
   
    # Function to traverse the graph using DFS
    def dfs(node, visited):
        stack = [node]
        print("stack",stack)
        print("node",node)
        while stack:
            current = stack.pop()
            if current not in visited:
               visited.add(current)
               print("visted",visited)
               print("edges[current]",edges[current])
               print("_",edges[current] - visited)
               stack.extend(edges[current] - visited)

    visited = set()
    subgraph_count = 0

    # Count connected components
    for node in connected_nodes:  # Only iterate over connected nodes
        if node not in visited:
            subgraph_count += 1
            dfs(node, visited)

    # Debugging: Print detected components
    print(f"Subgraphs detected: {subgraph_count}")

    # If there's more than one connected component, raise an error
    if subgraph_count > 1:
        raise ValueError("Error: More than one subgraph detected. Disconnect extra subgraphs.")

# Example JSON data (one subgraph)
data = {
    "requests": {
        "nodes": [
            {"node_id": "n1", "id": "", "type": "transcript", "properties": {}},
            {"node_id": "n2", "id": "", "type": "gene", "properties": {}},
            {"node_id": "n3", "id": "", "type": "promoter", "properties": {}},
            {"node_id": "n4", "id": "", "type": "gene", "properties": {}},  # Not connected
            {"node_id": "n5", "id": "", "type": "protein", "properties": {}},  # Not connected
        ],
        "predicates": [
            {"predicate_id": "p1", "type": "transcribed_from", "source": "n1", "target": "n2"},
            {"predicate_id": "p2", "type": "associated_with", "source": "n2", "target": "n3"},
             

        ]
    }
}

# Run the check
check_subgraphs(data)

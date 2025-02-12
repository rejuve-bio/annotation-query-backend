import networkx as nx
import matplotlib.pyplot as plt

# Load the provided 
data=''
# Define colors for different node types
node_colors_map = {"gene": "green", "transcript": "yellow", "exon": "blue"}

# Create a graph
G = nx.DiGraph()

# Add nodes
for node in data["nodes"]:
    print(node['data']['id'])
    G.add_node(node['data']["id"], label=node['data']["name"], color=node_colors_map.get(node['data']["type"], "gray"))

# Add edges
for edge in data["edges"]:
    G.add_edge(edge["data"]["source"], edge["data"]["target"], label=edge["data"]["label"])

# Extract node labels and colors
node_labels = {node['data']["id"]: node['data']["name"] for node in data["nodes"]}
node_colors = [G.nodes[node['data']["id"]]["color"] for node in data["nodes"]]

# Draw the graph
plt.figure(figsize=(8, 6))
pos = nx.spring_layout(G)
nx.draw(G, pos, with_labels=True, labels=node_labels, node_color=node_colors, font_size=10, font_weight="bold", edge_color="gray", arrows=True)
edge_labels = {(edge["data"]["source"], edge["data"]["target"]): edge["data"]["label"] for edge in data["edges"]}
nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=8)
plt.title("Network Graph with Node Types and Edge Labels")
plt.show()

import networkx as nx
import matplotlib.pyplot as plt

# Create a directed graph
G = nx.DiGraph()

# Add nodes
G.add_nodes_from([1, 2, 3, 4])

# Add edges (directed)
G.add_edges_from([(1, 2), (2, 3), (3, 4), (4, 2), (1, 3)])

# Define node positions
pos = nx.spring_layout(G)

# Identify ingoing and outgoing edges for node 2
target_node = 2
incoming_edges = [(u, v) for u, v in G.in_edges(target_node)]
outgoing_edges = [(u, v) for u, v in G.out_edges(target_node)]

# Draw nodes
nx.draw(G, pos, with_labels=True, node_color="lightblue", node_size=1000, font_size=12)

# Draw edges
nx.draw_networkx_edges(G, pos, edgelist=incoming_edges, edge_color="red", width=2, label="Incoming")
nx.draw_networkx_edges(G, pos, edgelist=outgoing_edges, edge_color="green", width=2, label="Outgoing")

# Draw remaining edges (not related to node 2)
remaining_edges = [e for e in G.edges if e not in incoming_edges and e not in outgoing_edges]
nx.draw_networkx_edges(G, pos, edgelist=remaining_edges, edge_color="gray", width=1, alpha=0.6)

# Show legend
plt.legend(["Incoming", "Outgoing"])
plt.show()


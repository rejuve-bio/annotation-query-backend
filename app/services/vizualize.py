import networkx as nx 
import matplotlib
matplotlib.use('TkAgg')  # or 'Qt5Agg', 'GTK3Agg', etc., depending on your system

import matplotlib.pyplot as plt

G=nx.Graph()
G.add_node("1")
G.add_edge("Elduye","jony")
G.add_edge(1,3)
nx.draw_spring(G,with_labels=True)
plt.savefig("output.png")
plt.show(block=True)
plt.ion()

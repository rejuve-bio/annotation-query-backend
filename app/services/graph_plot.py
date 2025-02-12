import networkx as nx
import matplotlib.pyplot as plt

# Load the provided data
data= {
        "edges": [
            {
                "data": {
                    "id": "l2CO4LnncpFZP10TZTgJJ",
                    "label": "transcribed_to",
                    "source": "1159957edbaa5108e2cd363a8a64317b",
                    "target": "75c7d7d0364e0f0393c4597c79d232a7"
                }
            },
            {
                "data": {
                    "id": "hUwKfROFlrnLbvn8PR3QP",
                    "label": "includes",
                    "source": "75c7d7d0364e0f0393c4597c79d232a7",
                    "target": "3b443f14abef5acdc09c98056ba8a660"
                }
            },
            {
                "data": {
                    "id": "6JkRZUFQWoT6Exu_Xx2V2",
                    "label": "includes",
                    "source": "75c7d7d0364e0f0393c4597c79d232a7",
                    "target": "b1932157d8b24866173b342d9728b8da"
                }
            },
            {
                "data": {
                    "id": "xiGjP3SOwfNztkM9rsIP0",
                    "label": "includes",
                    "source": "5ecc2bdebf745bd6a8625b0062c0d0b9",
                    "target": "b1932157d8b24866173b342d9728b8da"
                }
            },
            {
                "data": {
                    "id": "75GmVoKyNP-dqIvOofGAO",
                    "label": "includes",
                    "source": "35f45f560695b5b9bd34ade981590b7c",
                    "target": "b1932157d8b24866173b342d9728b8da"
                }
            },
            {
                "data": {
                    "id": "XNAiYDhPpkngsLpOR8m5D",
                    "label": "transcribed_to",
                    "source": "1159957edbaa5108e2cd363a8a64317b",
                    "target": "5ecc2bdebf745bd6a8625b0062c0d0b9"
                }
            },
            {
                "data": {
                    "id": "NY3zQ2NqEWnpN3_wYxA6m",
                    "label": "includes",
                    "source": "5ecc2bdebf745bd6a8625b0062c0d0b9",
                    "target": "a3fcd0e5a04f35a8a1bf7a08482ae7d0"
                }
            },
            {
                "data": {
                    "id": "lKsTm9jcNLKLyDxB6pozS",
                    "label": "transcribed_to",
                    "source": "1159957edbaa5108e2cd363a8a64317b",
                    "target": "35f45f560695b5b9bd34ade981590b7c"
                }
            },
            {
                "data": {
                    "id": "0_ujKmPeS7feaONi4JY-0",
                    "label": "includes",
                    "source": "35f45f560695b5b9bd34ade981590b7c",
                    "target": "ec0f5738a31ab00eae07eaf276ab1aa8"
                }
            },
            {
                "data": {
                    "id": "SQ1FlYJd8HxR_GIhPqaw3",
                    "label": "transcribed_to",
                    "source": "56091db3df4dca339fe129c79c31463a",
                    "target": "c30aca45add2c1098b71d768533843a7"
                }
            },
            {
                "data": {
                    "id": "s9ZDGqmCjgCKOXN7Ezzl0",
                    "label": "includes",
                    "source": "c30aca45add2c1098b71d768533843a7",
                    "target": "84d44b3c1496390ea54dc7e801a69a88"
                }
            },
            {
                "data": {
                    "id": "5oMo9Lv486ZDDqDL1uqV3",
                    "label": "transcribed_to",
                    "source": "0eee0cda371d9ea0a9ea1f849da3f0f4",
                    "target": "33a40b8d46dfbda126974e22da5f37f9"
                }
            },
            {
                "data": {
                    "id": "T68Evwk_Ao7YawCXh5CSU",
                    "label": "includes",
                    "source": "33a40b8d46dfbda126974e22da5f37f9",
                    "target": "258b907826da3ab6589ae39f4cad9f9e"
                }
            },
            {
                "data": {
                    "id": "nDpzQ1C50Lz0nOtHjQaHY",
                    "label": "transcribed_to",
                    "source": "1591ed5b52598a609f11f83cdea57fe1",
                    "target": "591823940f657639367b34c1cebfc1c3"
                }
            },
            {
                "data": {
                    "id": "-ZnCnQTrsEmR1cu6PlJRA",
                    "label": "includes",
                    "source": "591823940f657639367b34c1cebfc1c3",
                    "target": "a9131e0eceb1155ffe377022e781ba36"
                }
            }
        ],
        "nodes": [
            {
                "data": {
                    "id": "75c7d7d0364e0f0393c4597c79d232a7",
                    "name": "7 transcript nodes",
                    "type": "transcript"
                }
            },
            {
                "data": {
                    "id": "1159957edbaa5108e2cd363a8a64317b",
                    "name": "23 gene nodes",
                    "type": "gene"
                }
            },
            {
                "data": {
                    "id": "3b443f14abef5acdc09c98056ba8a660",
                    "name": "exon ense00001901152",
                    "type": "exon"
                }
            },
            {
                "data": {
                    "id": "b1932157d8b24866173b342d9728b8da",
                    "name": "18 exon nodes",
                    "type": "exon"
                }
            },
            {
                "data": {
                    "id": "5ecc2bdebf745bd6a8625b0062c0d0b9",
                    "name": "8 transcript nodes",
                    "type": "transcript"
                }
            },
            {
                "data": {
                    "id": "a3fcd0e5a04f35a8a1bf7a08482ae7d0",
                    "name": "2 exon nodes",
                    "type": "exon"
                }
            },
            {
                "data": {
                    "id": "35f45f560695b5b9bd34ade981590b7c",
                    "name": "8 transcript nodes",
                    "type": "transcript"
                }
            },
            {
                "data": {
                    "id": "ec0f5738a31ab00eae07eaf276ab1aa8",
                    "name": "2 exon nodes",
                    "type": "exon"
                }
            },
            {
                "data": {
                    "id": "c30aca45add2c1098b71d768533843a7",
                    "name": "2 transcript nodes",
                    "type": "transcript"
                }
            },
            {
                "data": {
                    "id": "56091db3df4dca339fe129c79c31463a",
                    "name": "2 gene nodes",
                    "type": "gene"
                }
            },
            {
                "data": {
                    "id": "84d44b3c1496390ea54dc7e801a69a88",
                    "name": "2 exon nodes",
                    "type": "exon"
                }
            },
            {
                "data": {
                    "id": "33a40b8d46dfbda126974e22da5f37f9",
                    "name": "2 transcript nodes",
                    "type": "transcript"
                }
            },
            {
                "data": {
                    "id": "0eee0cda371d9ea0a9ea1f849da3f0f4",
                    "name": "2 gene nodes",
                    "type": "gene"
                }
            },
            {
                "data": {
                    "id": "258b907826da3ab6589ae39f4cad9f9e",
                    "name": "2 exon nodes",
                    "type": "exon"
                }
            },
            {
                "data": {
                    "id": "591823940f657639367b34c1cebfc1c3",
                    "name": "3 transcript nodes",
                    "type": "transcript"
                }
            },
            {
                "data": {
                    "id": "1591ed5b52598a609f11f83cdea57fe1",
                    "name": "3 gene nodes",
                    "type": "gene"
                }
            },
            {
                "data": {
                    "id": "a9131e0eceb1155ffe377022e781ba36",
                    "name": "3 exon nodes",
                    "type": "exon"
                }
            }
        ]
    }
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

import networkx as nx
import matplotlib.pyplot as plt

# Load the provided 
data= {
        "edges": [
            {
                "data": {
                    "id": "XyBlwj4QaF5iqRxbtVJzD",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "RrhdUU4P5t5WzbujFDQ-X",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "8sdFT8K3kSPWykOKBUUcu",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "WyXh5Q7AAmqgZC2ewHNMP",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "z4yPletcGGcdkk8hAv4Oc",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "gu0B4kGWi9Wk8f4uD_aLO",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "gL1zr9nQe7RLU7hTWz91A",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "eSFmdLeiBVFQ8uu4tbC_0",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "2tQ6ad12GBSs2ANcn37gp",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "YPeGjMvz8SMprAz8T4yrx",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "IxyqDMZBnOgC9IyYSvYha",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "e09xte53xS1UUUzDCFzW0",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "TvVfXgc4-QVHO0kGaFXyU",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "UkDUvx0y_KlxfTGUYRkoc",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "P7J9FFsWf1MY0CIQHEhVA",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "8n1DbkR5VmvyRqju8-ama",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "e8bCotxrZxHjQ8j74gZ9j",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "8jLaU9RV4HcSwXn5rgz8l",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "q9o2J0DKTFgfb9HJcJzHy",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "U0kFkbfqMwHROFI7uGz24",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "l1BJ6DHckA49NXjDZ_nvR",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "mjf0IivXfinLi-iPtZqM8",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "i_SeCYfMDIvqIfxB4tCAW",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "aVADGJ7WwecgQqKTYOt2j",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "sgNEO_7h_U-FvEXEMi1Z_",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "ZKVGLSKAcyAFLKAVGiIxf",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "hjF5AjWM7uqEOcUY7KKCB",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "fA39hLm6e8IXAU4hqaJpZ",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "gocUFbMD5ShH83-UY-NJw",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "uEpzTECk5evm5HaMfkSda",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "983nAB6d0Xu2H-mDKCn5j",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "nE9iRGMS9S5tr65iYFjLZ",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "1M4jO3vojYJDJdfzA31tA",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "ja8i3DJPA_QzsQ6WxSl09",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "uniolgZPN-AH55pUQePGn",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "kvi-GZ3K9aC7BWogUX8Ut",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "NZM9fblV9QED8uHSzdMv1",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "9hZLzHDiPSEC4kqHYSfIW",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "F-IppolkL_io205dbqlqu",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "rgGu5xh7w38dnRqgsSfAk",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "nosbEJ0xOZNJKKICqdUp7",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "4Df8m6t6CEVlzcwHAR3oH",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "vc-RHWrn6XHGqOQ_4v9rv",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "WZfT5tEyy0ByGSfxVWbQQ",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "c6PU4rwlr-QGlYdvT6l31",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "-kYAkL0uczW3xfvtTINH5",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "8bpccwx59TjNsVLUKOm6j",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "yzZJ9ork2_Iz13i2WQLlc",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "tSm2axMO5HaLovFiMooMl",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "MY57ZH96-FdUCf1e_EGLT",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "fDA9fBXPUNFS6SkmwBOZA",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "20y-pK1IkltexGdwNPVTZ",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "5jQ4V5NsDtWNtNfTSvoyZ",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "zRdZEdoTmVsxCwb_4oA9C",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "ZaRDaX0riy5Tcpi8y7q9k",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "fEObrwqN7lYFvU4On5YfO",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "Ao_p077YYbBfrxQHLoR0A",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "dQROku81FtFmXX32K5HCR",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "kaIwfm32TN2T2dkRMO9L4",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "h6hDFn0-wIRyaL_z-rMV1",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "pN8LPp7aQJfUGEdMYpbYz",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "VnvXykNGDprlHXJho3n9r",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            },
            {
                "data": {
                    "id": "5sMnHAcyKB7CixX4Xp-bj",
                    "label": "eqtl_association",
                    "source": "29f528c62e1229edf835153892529e83",
                    "target": "6feabb8ff9eeb5a002f67ee35b844d9f"
                }
            }
        ],
        "nodes": [
            {
                "data": {
                    "id": "29f528c62e1229edf835153892529e83",
                    "name": "63 snp nodes",
                    "type": "snp"
                }
            },
            {
                "data": {
                    "id": "6feabb8ff9eeb5a002f67ee35b844d9f",
                    "name": "gene ensg00000116717",
                    "type": "gene"
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

from app.lib.map_graph import map_graph

def limit_graph(graph, threshold):
    (edge_idx, single_node_idx) = map_graph(graph)
    allowed_edges = set()
    remaining = threshold

    for _, adj_list in enumerate(edge_idx):
        if len(adj_list) == 0:
            continue
        
        if len(adj_list) + 1 <= remaining:
            allowed_edges.update(adj_list)
            remaining -= (len(adj_list) + 1)
    nodes_to_include = set()
    for edge_idx in allowed_edges:
        edge = graph["edges"][edge_idx]
        source_id = edge["data"]["source"]
        target_id = edge["data"]["target"]
        
        nodes_to_include.add(source_id)
        nodes_to_include.add(target_id)
    
    node_id_to_index = {node["data"]["id"]: idx for idx, node in enumerate(graph["nodes"])}
    
    new_response = {"nodes": [], "edges": []}
    
    # add nodes with edges
    for node_id in nodes_to_include:
        if node_id in node_id_to_index:
            new_response["nodes"].append(graph["nodes"][node_id_to_index[node_id]])
    
    # add edges
    for edge_idx in allowed_edges:
        new_response["edges"].append(graph["edges"][edge_idx])
    
    # add nodes without edges
    for node_widx in single_node_idx:
        if remaining != 0:
            new_response["nodes"].append(graph["nodes"][node_widx])
            remaining = remaining - 1
    return new_response 

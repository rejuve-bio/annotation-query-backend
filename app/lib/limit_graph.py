from app.lib.map_graph import map_graph

def limit_graph(graph, threshold):
    '''
    Reduces the number of graphs based on the threshold while keeping relvant information

    How it works:
        1. Identify the nodes with edges and nodes without edges
        2. Select edges connecting each node that doesn't exceed the threshold.
        3. Add the nodes connected by the selected edges to a collection of included nodes.
        4. If capacity allows, includes isolated nodes until the threshold is reached.
    
    Args:
        graph (dict): Graph containing 'nodes' and 'edges'
        threshold (int): The maximum number of nodes to be displayed

    Returns:
        dict: A new graph containg 'nodes' and 'edges'
    '''
    (edge_idx, single_node_idx, node_id_to_index) = map_graph(graph)
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

def map_graph(graph):
    '''
    Maps graph nodes to their indices and identify nodes with no connected edges

    How it works:
        1. Extract nodes and edges from the graph.
        2. Maps nodes Ids to their list indices.
        3. Loop through edges, updating 'edge_indices' and marking nodes that are connected
        4. Identify nodes with no edges and add them to 'single_node_idx'

    Args: 
        graph (dict): Graph containing 'nodes' and 'edges'

    Returns:
        tuple:
            - edge_indices: a list containing the indices of edges connected to a given node
            - single_node_idx: a list containg indices of nodes with no edges
            - node_id_to_index: a mapping of nodes Ids to their corresponding indices
    '''
    nodes = graph["nodes"]
    edges = graph["edges"]

    # Create a mapping of node IDs to their indices
    node_id_to_index = {node["data"]["id"]: idx for idx, node in enumerate(nodes)}

    edge_indices = [[] for _ in range(len(nodes))]
    single_node_idx = []

    # Track nodes that have edges
    has_edges = [False] * len(nodes)

    # Process edges and populate edge_indices
    for edge_index, edge in enumerate(edges):
        source_id = edge["data"]["source"]
        target_id = edge["data"]["target"]

        if source_id in node_id_to_index:
            source_index = node_id_to_index[source_id]
            edge_indices[source_index].append(edge_index)
            has_edges[source_index] = True

        if target_id in node_id_to_index:
            target_index = node_id_to_index[target_id]
            has_edges[target_index] = True

    # Determine nodes without edges
    for idx, has_edge in enumerate(has_edges):
        if not has_edge:
            single_node_idx.append(idx)
    return edge_indices, single_node_idx, node_id_to_index


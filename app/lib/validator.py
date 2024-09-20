def validate_request(request, schema):
    if 'nodes' not in request:
        raise Exception("node is missing")

    nodes = request['nodes']
        
    # validate nodes
    if not isinstance(nodes, list):
        raise Exception("nodes should be a list")

    for node in nodes:
        if not isinstance(node, dict):
            raise Exception("Each node must be a dictionary")
        if 'id' not in node:
            raise Exception("id is required!")
        if 'type' not in node or node['type'] == "":
            raise Exception("type is required")
        if 'node_id' not in node or node['node_id'] == "":
            raise Exception("node_id is required")
        if 'properties' not in node:
            node["properties"] = {}

    ''''    
    # validate properties of nodes
    for node in nodes:
        properties = node['properties']
        node_type = node['type']
        for property in properties.keys():
            if property not in schema[node_type]['properties']:
                raise Exception(f"{property} doesn't exsist in the schema!")
    '''

    node_map = {node['node_id']: node for node in nodes}

    # validate predicates
    if 'predicates' in request:
        predicates = request['predicates']
            
        if not isinstance(predicates, list):
            raise Exception("Predicate should be a list")
        for predicate in predicates:
            if 'type' not in predicate or predicate['type'] == "":
                raise Exception("predicate type is required")
            if 'source' not in predicate or predicate['source'] == "":
                raise Exception("source is required")
            if 'target' not in predicate or predicate['target'] == "":
                raise Exception("target is required")

            if predicate['source'] not in node_map:
                raise Exception(f"Source node {predicate['source']} does not exist in the nodes object")
            if predicate['target'] not in node_map:
                raise Exception(f"Target node {predicate['target']} does not exist in the nodes object")
            
            # format the predicate type using _
            predicate_type = predicate['type'].split(' ')
            predicate_type = '_'.join(predicate_type)
            
            source_type = node_map[predicate['source']]['type']
            target_type = node_map[predicate['target']]['type']

            predicate_type = f'{source_type}-{predicate_type}-{target_type}'
            if predicate_type not in schema:
                raise Exception(f"Invalid source and target for the predicate {predicate['type']}")
    return node_map

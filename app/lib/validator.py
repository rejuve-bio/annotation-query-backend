import networkx as nx
import re

def clean_string(s):
    return re.sub(r'[-_]', '', s)

def validate_request(request, schema, source):
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
        
        # format the node id into approperiate format
        node_id = node['node_id']
        node['node_id'] = clean_string(node_id)

        node.setdefault('properties', {})

        if 'chr' in node["properties"]:
            chr_property = node["properties"]["chr"]
            chr_property = str(chr_property)
            if chr_property and not chr_property.startswith('chr'):
                node["properties"]["chr"] = 'chr' + chr_property

    ''''
    # validate properties of nodes
    for node in nodes:
        properties = node['properties']
        node_type = node['type']
        for property in properties.keys():
            if property not in schema[node_type]['properties']:
                raise Exception(f"{property} doesn't exsist in the schema!")
    '''

    node_map = {}
    for node in nodes:
        if node['node_id'] not in node_map:
            node_map[node['node_id']] = node
        else:
            raise Exception('Repeated Node_id')

    # validate predicates
    if 'predicates' in request:
        predicates = request['predicates']

        if not isinstance(predicates, list):
            raise Exception("Predicate should be a list")
        for i, predicate in enumerate(predicates):
            if 'type' not in predicate or predicate['type'] == "":
                raise Exception("predicate type is required")
            if 'source' not in predicate or predicate['source'] == "":
                raise Exception("source is required")
            if 'target' not in predicate or predicate['target'] == "":
                raise Exception("target is required")
            
            predicate['source'] = clean_string(predicate['source'])
            predicate['target'] = clean_string(predicate['target'])
            
            # Handle cases validation for the ai-assistant
            if 'predicate_id' not in predicate:
                predicate['predicate_id'] = f'p{i}'

            if predicate['source'] not in node_map:
                raise Exception(
                    f"Source node {predicate['source']}\
                    does not exist in the nodes object")
            if predicate['target'] not in node_map:
                raise Exception(
                    f"Target node {predicate['target']}\
                    does not exist in the nodes object")

            # format the predicate type using _
            predicate_type = predicate['type'].split(' ')
            predicate_type = '_'.join(predicate_type)

            source_type = node_map[predicate['source']]['type']
            target_type = node_map[predicate['target']]['type']
            
            # TODO: to be removed
            predicate_type_one = f'{source_type}_{predicate_type}_{target_type}'
            predicate_type_two = f'{source_type}_{source_type}_{predicate_type}_{target_type}'
            if predicate_type_one not in schema and predicate_type_two not in schema:
                raise Exception(
                    f"Invalid source and target for\
                    the predicate {predicate['type']}")
    if source != 'hypothesis':
        if check_disconnected_graph(request):
            raise Exception("Disconnected subgraph found")

    return node_map


def check_disconnected_graph(request):
    # create a networkx graph
    nodes = request['nodes']
    edges = request['predicates']

    G = nx.Graph()

    # create the nodes
    for node in nodes:
        G.add_node(node["node_id"])

    # create the edges
    for edge in edges:
        G.add_edge(edge["source"], edge["target"])

    # identify subgraphs
    connected_components = list(nx.connected_components(G))

    if len(connected_components) > 1:
        return True

    return False

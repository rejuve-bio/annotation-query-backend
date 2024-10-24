import json
from tests.lib.header_generator import generate_headers

# test for the /relations/<node>
def test_node_relations(client, node_list):
    headers = generate_headers()

    for node in node_list:
        # make a call to endpoint for each possible node value
        response = client.get(f'/relations/{node}', headers=headers)

        # assert url returned an HTTP 200 OK code
        assert '200 OK' == response._status

        # decode return and parse to a dict object
        schemas = json.loads(response.data.decode('utf-8'))
        for schema in schemas:
            # assert that each return has the value of the node
            assert node in schema.values()

# test for the /edge route
def test_edge_route(client):
    headers = generate_headers()
    # make a call to the edges endpoint
    response = client.get('/edges', headers=headers)

    # check the return status
    assert '200 OK' == response._status

    # decode return and parse to a dict object
    schemas = json.loads(response.data.decode('utf-8'))
    for schema in schemas:
        # assert that each item has child and parent edges
        assert ('child_edges', 'parent_edge') == tuple(schema.keys())

# test for the /node route
def test_node_route(client):
    headers = generate_headers()
    # make a call to the nodes endpoint
    response = client.get('/nodes', headers=headers)

    # check the return status
    assert '200 OK' == response._status

    # decode return and parse to a dict object
    schemas = json.loads(response.data.decode('utf-8'))
    for schema in schemas:
        # assert that each item has child and parent nodes
        assert ('child_nodes', 'parent_node') == tuple(schema.keys())

# test for empty json /query route
def test_query_without_data(client):
    headers = generate_headers()
    # make a call to the /query endpoint with out json data
    response = client.post('/query', headers=headers)
    assert response._status == '415 UNSUPPORTED MEDIA TYPE'

def test_query_with_empty_data(client):
    headers=generate_headers()
    # make a call to the /query endpoint with empty json data
    response = client.post('/query', data=json.dumps({'request': 'test'}), headers=headers, content_type='application/json')
    assert response._status == '400 BAD REQUEST'


import pytest
from app.lib.validator import validate_request 
from app import schema_manager

def test_node_is_missing():
    # assert validate raises an exeption with no node key in request dict
    request = []
    with pytest.raises(Exception, match="node is missing"):
        validate_request(request, schema_manager.schema)

def test_wrong_node_type():
    # assert validate_request raises an exception with node value not a list
    requests = [{"nodes": ''},{"nodes": {}},{"nodes": set()},{"nodes": ()}]
    with pytest.raises(Exception, match="nodes should be a list"):
        for request in requests:
            validate_request(request, schema_manager.schema)

def test_wrong_node_values():
    # assert the values of node is a list of dict
    requests = [ {'nodes':[str()]},{'nodes':[list()]},{'nodes':[set()]},{'nodes':[tuple()]} ]
    with pytest.raises(Exception, match="Each node must be a dictionary"):
        for request in requests:
            validate_request(request, schema_manager.schema)

def test_node_without_node_id():
    #assert each node in nodes value have a node_id
    request = {'nodes': [
        {"id": "", # node without node_id
        "type": "gene",
        "properties": {}
      }]}

    with pytest.raises(Exception, match="node_id is required"):
        validate_request(request, schema_manager.schema)
        
    request = { 'nodes':[
               {"node_id": "", # node with empty node_id
                "id": "",
                "type": "gene",
                "properties": {}
                }]}

    with pytest.raises(Exception, match="node_id is required"):
        validate_request(request, schema_manager.schema)


def test_node_without_id():
    #assert each node in nodes value has an id
    request = {'nodes': [
        { "node_id": "n1", # node with out id
          "type": "gene",
          "properties": {}
        }]}

    with pytest.raises(Exception, match="id is required!"):
        validate_request(request, schema_manager.schema)

def test_node_without_type():
    #assert each node in nodes value have a type
    request = {'nodes': [
        {"node_id": "n1", # node without type
         "id": "", 
        "properties": {}
      }]}

    with pytest.raises(Exception, match="type is required"):
        validate_request(request, schema_manager.schema)

    request = { 'nodes':[
               {"node_id": "", # node with empty type
                "id": "",
                "type": "",
                "properties": {}
                }]}

    with pytest.raises(Exception, match="type is required"):
        validate_request(request, schema_manager.schema)

'''
def test_properties_key():
    # assert each predicate has proper keys
    request = {'nodes': [{
            "node_id": "n3",
            "id": "",
            "type": "protein",
            "properties": { # node with improper properties key
                    "protein_nam": "MKKS"
                }
        }
    ]}

    with pytest.raises(Exception, match="protein_nam doesn't exsist in the schema!"):
        validate_request(request, schema_manager.schema)
'''

def test_predicate_type():
    # assert predicate is of type list
    requests = [
                {'nodes': [{
                    "node_id": "n1",
                    "id": "",
                    "type": "gene",
                    "properties": {}
                  }]
                 , 'predicates': str()}, # predicates with str type
                {'nodes': [{
                    "node_id": "n1",
                    "id": "",
                    "type": "gene",
                    "properties": {}
                  }]
                 , 'predicates': dict()}, # predicates with list type
                {'nodes': [{
                    "node_id": "n1",
                    "id": "",
                    "type": "gene",
                    "properties": {}
                  }]
                 , 'predicates': set()},
                {'nodes': [{
                    "node_id": "n1",
                    "id": "",
                    "type": "gene",
                    "properties": {}
                  }]
                 , 'predicates': tuple()},
               ]


    with pytest.raises(Exception, match="Predicate should be a lis"):
        for request in requests:
            validate_request(request, schema_manager.schema)

def test_predicates_type():
    # assert each predicate has non emptry type value
    request = {
               'nodes':[
                {
                    "node_id": "n1",
                    "id": "",
                    "type": "gene",
                    "properties": {}
                }],
                'predicates':[
                {        
                    "source": "n1",
                    "target": "n2"
                }]
            }

    with pytest.raises(Exception, match="predicate type is required"):
        validate_request(request, schema_manager.schema)

    request['predicates'][0]['type'] = "" # add empty string to predicates and assert same exception

    with pytest.raises(Exception, match="predicate type is required"):
        validate_request(request, schema_manager.schema)

def test_predicates_source():
    # assert each predicate has non emptry source value
    request = {
               'nodes':[
                {
                    "node_id": "n1",
                    "id": "",
                    "type": "gene",
                    "properties": {}
                }],
                'predicates':[
                {
                    "type": "translates_to",
                    "target": "n2"
                }]
            }

    with pytest.raises(Exception, match="source is required"):
        validate_request(request, schema_manager.schema)

    request['predicates'][0]['source'] = "" # add empty string to predicates and assert same exception

    with pytest.raises(Exception, match="source is required"):
        validate_request(request, schema_manager.schema)


def test_predicates_target():
    # assert each predicate has non emptry target value
    request = {
               'nodes':[
                {
                    "node_id": "n1",
                    "id": "",
                    "type": "gene",
                    "properties": {}
                }],
                'predicates':[
                {
                    "type": "translates_to",
                    "source": "n1"
                }]
            }

    with pytest.raises(Exception, match="target is required"):
        validate_request(request, schema_manager.schema)

    request['predicates'][0]['target'] = "" # add empty string to predicates and assert same exception

    with pytest.raises(Exception, match="target is required"):
        validate_request(request, schema_manager.schema)

def test_predicte_source_map():
    # assert predicate source is available in node_id value
    request = {
               'nodes':[
                {
                    "node_id": "n1",
                    "id": "",
                    "type": "gene",
                    "properties": {}
                }],
                'predicates':[ 
                {
                    "type": "translates_to",
                    "source": "n0",
                    "target": "n1",
                }]
            }

    with pytest.raises(Exception, match="Source node n0 does not exist in the nodes object"):
        validate_request(request, schema_manager.schema)

def test_predicte_target_map():
    # assert predicate target is available in node_id value
    request = {
               'nodes':[
                {
                    "node_id": "n1",
                    "id": "",
                    "type": "gene",
                    "properties": {}
                }],
                'predicates':[ 
                {
                    "type": "translates_to",
                    "source": "n1",
                    "target": "n0",
                }]
            }

    with pytest.raises(Exception, match="Target node n0 does not exist in the nodes object"):
        validate_request(request, schema_manager.schema)

# add test for last exception
def test_predicate_schema_type():
    pass

import pytest

one_node_id_propoerties = {
    "requests": {
        "nodes": [
        {
            "node_id": "n1",
            "id": "ensg00000101349",
            "type": "gene",
            "properties": {
                "gene_type": "protein_coding"
            }
        }]
    }
}

one_node_id_noproperties = {
    "requests": {
        "nodes": [
        {
            "node_id": "n1",
            "id": "ensg00000101349",
            "type": "gene",
            "properties": {}
        }]
    }
}

one_node_noid_properties = {
    "requests": {
        "nodes": [
        {
            "node_id": "n1",
            "id": "",
            "type": "protein",
            "properties": {
                "protein_name": "LAMP2"
            }
        }]
    }
}



two_node_bothid = {
    "requests": {
        "nodes": [
        {
            "node_id": "n1",
            "id": "ensg00000101349",
            "type": "gene",
            "properties": {
                "gene_type": "protein_coding"
            }
        },
        {
            "node_id": "n2",
            "id": "p13473",
            "type": "protein",
            "properties": {}
        }
        ]
    }    
}

test_two_node_id_property = {
    "requests": {
        "nodes": [
        {
            "node_id": "n1",
            "id": "ensg00000101349",
            "type": "gene",
            "properties": {}
        },
        {
            "node_id": "n2",
            "id": "",
            "type": "protein",
            "properties": {
                "protein_name": "SNP25"
            }
        }
        ]
    }    
}

test_two_node_id_one_edge = {
        "requests": {
            "nodes": [
            {
                "node_id": "n1",
                "id": "ensg00000101349",
                "type": "gene",
                "properties": {
                "gene_type": "protein_coding"
                }
            },
            {
                "node_id": "n2",
                "id": "",
                "type": "transcript",
                "properties": {}
            }
            ],
            "predicates": [
            {
                "type": "transcribed to",
                "source": "n1",
                "target": "n2"
            }
        ]
        }
}

test_two_node_two_edge = {
    "requests": {
        "nodes": [
            {
                "node_id": "n1",
                "id": "",
                "type": "transcript",
                "properties": {}
            },
            {
                "node_id": "n2",
                "id": "",
                "type": "protein",
                "properties": {
                    "protein_name": "SNP25"
                }
            }
            ],
        "predicates": [
            {
                "type": "translates to",
                "source": "n1",
                "target": "n2"
            },
            {
                "type": "translation of",
                "source": "n2",
                "target": "n1"

            }
        ]
    }
}

test_three_node_one_edge = {
    "requests": {
        "nodes": [
            {
                "node_id": "n1",
                "id": "ensg00000101349",
                "type": "gene",
                "properties": {
                "gene_type": "protein_coding"
                }
            },
            {
                "node_id": "n2",
                "id": "",
                "type": "transcript",
                "properties": {}
            },
            {
                "node_id": "n3",
                "id": "",
                "type": "protien",
                "properties": {}
            }
            ],
        "predicates": [
            {
                "type": "transcribed to",
                "source": "n1",
                "target": "n2"
            }
        ]
    }
}

test_three_node_two_edge = {
    "requests": {
        "nodes": [
            {
                "node_id": "n1",
                "id": "ensg00000101349",
                "type": "gene",
                "properties": {
                    "gene_type": "protein_coding"
                }
            },
            {
                "node_id": "n2",
                "id": "",
                "type": "transcript",
                "properties": {}
            },
            {
                "node_id": "n3",
                "id": "",
                "type": "protein",
                "properties": {
                }
            }
            ],
        "predicates": [
            {
                "type": "transcribed to",
                "source": "n1",
                "target": "n2"
            },
            {
                "type": "translates_to",
                "source": "n2",
                "target": "n3"
            }
        ]
    }
}

@pytest.fixture(params=[
    one_node_id_noproperties,
    one_node_id_propoerties,
    one_node_noid_properties,
    two_node_bothid,
    test_two_node_id_property,
    test_two_node_id_one_edge,
    test_two_node_two_edge,
    test_three_node_one_edge,
    test_three_node_two_edge
])
def query_list(request):
    return request.param

import pytest


one_node_id_properties = {
    "nodes": [
        {
            "node_id": "n1",
            "id": "ensg00000101349",
            "type": "gene",
            "properties": {
                "gene_type": "protein_coding",
            },
        }
    ],
    "predicates": [],
}

one_node_id_noproperties = {
    "nodes": [
        {
            "node_id": "n1",
            "id": "ensg00000101349",
            "type": "gene",
            "properties": {},
        }
    ],
    "predicates": [],
}

one_node_noid_properties = {
    "nodes": [
        {
            "node_id": "n1",
            "id": "",
            "type": "protein",
            "properties": {
                "protein_name": "LAMP2",
            },
        }
    ],
    "predicates": [],
}

two_node_bothid = {
    "nodes": [
        {
            "node_id": "n1",
            "id": "ensg00000101349",
            "type": "gene",
            "properties": {
                "gene_type": "protein_coding",
            },
        },
        {
            "node_id": "n2",
            "id": "p13473",
            "type": "protein",
            "properties": {},
        },
    ],
    "predicates": [],
}

two_node_one_edge = {
    "nodes": [
        {
            "node_id": "n1",
            "id": "ensg00000101349",
            "type": "gene",
            "properties": {
                "gene_type": "protein_coding",
            },
        },
        {
            "node_id": "n2",
            "id": "",
            "type": "transcript",
            "properties": {},
        },
    ],
    "predicates": [
        {
            "type": "transcribed to",
            "source": "n1",
            "target": "n2",
        }
    ],
}

two_node_two_edge = {
    "nodes": [
        {
            "node_id": "n1",
            "id": "",
            "type": "transcript",
            "properties": {},
        },
        {
            "node_id": "n2",
            "id": "",
            "type": "protein",
            "properties": {
                "protein_name": "SNP25",
            },
        },
    ],
    "predicates": [
        {
            "type": "translates to",
            "source": "n1",
            "target": "n2",
        },
        {
            "type": "translation of",
            "source": "n2",
            "target": "n1",
        },
    ],
}


@pytest.fixture(
    params=[
        one_node_id_noproperties,
        one_node_id_properties,
        one_node_noid_properties,
        two_node_bothid,
        two_node_one_edge,
        two_node_two_edge,
    ]
)
def request_list(request):
    return request.param

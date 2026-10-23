"""Property names and values are never written into Cypher unsafely (no database needed).

Run: python -m pytest tests/unit/test_cypher_security.py --noconftest
"""
import pytest

from app.lib.validator import validate_request
from app.services.cypher_generator import CypherQueryGenerator


@pytest.fixture
def gen():
    # Build queries only; no Neo4j connection is made.
    return CypherQueryGenerator.__new__(CypherQueryGenerator)


def node(node_id, node_type, properties=None, id_=""):
    return {"node_id": node_id, "id": id_, "type": node_type, "properties": properties or {}}


def test_where_construct_output_unchanged_for_normal_properties(gen):
    assert gen.where_construct(node("n0", "gene", {"gene_name": "TP53"}), "n0") == ["n0.gene_name =~ '(?i)TP53'"]


def test_where_construct_rejects_unsafe_property_name(gen):
    with pytest.raises(ValueError, match="Invalid node/relationship type"):
        gen.where_construct(node("n0", "gene", {"gene_name) RETURN 1 //": "x"}), "n0")


def test_string_list_is_escaped(gen):
    assert gen._cypher_string_list(["ENSG1", "a'b", "c\\d"]) == "['ENSG1', 'a\\'b', 'c\\\\d']"


def _list_request(gene_props=None, gene_id="ENSG00000141510, ENSG00000012048"):
    return {
        "nodes": [node("n0", "gene", gene_props, id_=gene_id), node("n1", "transcript")],
        "predicates": [{"predicate_id": "p0", "type": "transcribed to", "source": "n0", "target": "n1"}],
    }


def test_list_query_unchanged_for_normal_ids(gen):
    query = gen.in_list_query_generator(_list_request())[0]
    assert "WITH ['ENSG00000141510', 'ENSG00000012048'] AS listA" in query
    assert "n0.id IN listA" in query


def test_list_query_escapes_quotes_in_ids(gen):
    query = gen.in_list_query_generator(_list_request(gene_id="ENSG1, x' }) MATCH (z) DETACH DELETE z //"))[0]
    assert "'X\\' }) MATCH (Z) DETACH DELETE Z //'" in query
    assert "x' })" not in query


def test_list_query_escapes_property_values(gen):
    request = _list_request()
    request["nodes"][1]["properties"] = {"transcript_type": "a.b' OR true //"}
    query = gen.in_list_query_generator(request)[0]
    assert "n1.transcript_type =~ '(?i)a\\.b OR true //'" in query


def test_list_query_rejects_unsafe_property_name(gen):
    request = _list_request()
    request["nodes"][1]["properties"] = {"x) RETURN 1 //": "y"}
    with pytest.raises(ValueError, match="Invalid node/relationship type"):
        gen.in_list_query_generator(request)


def test_validator_rejects_unsafe_property_name_in_normal_properties():
    request = {"nodes": [node("n0", "gene", {"gene_name) RETURN 1 //": "x"})], "predicates": []}
    with pytest.raises(ValueError, match="invalid property name"):
        validate_request(request, {}, None)


def test_client_cannot_send_server_only_logic_conditions(gen):
    # '_logic_conditions' is written into the query as is; only the server may set it.
    request = {"nodes": [{**node("n0", "gene", {"gene_name": "TP53"}),
                          "_logic_conditions": ["1=1 WITH n0 DETACH DELETE n0 //"]}], "predicates": []}
    with pytest.raises(Exception, match="unknown key '_logic_conditions'"):
        validate_request(request, {}, None)
    # Paths that skip validation cannot inject it either.
    query = gen.query_Generator(request, {"n0": request["nodes"][0]})[0]
    assert "DETACH" not in query and "1=1" not in query

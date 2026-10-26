"""
Boolean logic against a real Neo4j: results must match hand-written Cypher,
and count queries must agree with the returned results.

Opt-in, and only light queries (filtered anchors), so it is safe on a
shared database:
    LOGIC_LIVE_TESTS=1 python -m pytest tests/integration/cypher/test_logic_live.py --noconftest
Uses FLY_NEO4J_* / HUMAN_NEO4J_* from the environment (.env).
"""
import copy
import logging
import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("LOGIC_LIVE_TESTS") != "1",
                                reason="set LOGIC_LIVE_TESTS=1 to run against a real Neo4j")


def node(node_id, node_type, properties=None, id_=""):
    return {"node_id": node_id, "id": id_, "type": node_type, "properties": properties or {}}


def pred(pid, ptype, source, target):
    return {"predicate_id": pid, "type": ptype, "source": source, "target": target}


GENE_COUNT = "MATCH (g:gene) WHERE {} RETURN count(DISTINCT g) AS c"

CASES = [
    ("fly", "OR across properties",
     {"nodes": [node("n0", "gene")], "predicates": [],
      "logic": {"operator": "OR", "nodes": {"node_id": "n0", "properties": {"gene_name": "N", "gene_type": "rRNA"}}}},
     GENE_COUNT.format("g.gene_name =~ '(?i)N' OR g.gene_type =~ '(?i)rRNA'")),
    ("fly", "NOT on a property with a positive filter",
     {"nodes": [node("n0", "gene", {"gene_name": "N"})], "predicates": [],
      "logic": {"operator": "NOT", "nodes": {"node_id": "n0", "properties": {"gene_type": "pseudogene"}}}},
     GENE_COUNT.format("g.gene_name =~ '(?i)N' AND NOT coalesce(g.gene_type =~ '(?i)pseudogene', false)")),
    ("fly", "OR group AND a predicate",
     {"nodes": [node("n0", "gene"), node("n1", "biological_process")], "predicates": [pred("p0", "involved in", "n0", "n1")],
      "logic": {"operator": "AND", "children": [
          {"operator": "OR", "nodes": {"node_id": "n0", "properties": {"gene_name": "N", "gene_type": "rRNA"}}}]}},
     "MATCH (g:gene)-[:involved_in]->(:biological_process) "
     "WHERE g.gene_name =~ '(?i)N' OR g.gene_type =~ '(?i)rRNA' RETURN count(DISTINCT g) AS c"),
    ("fly", "NOT on a predicate",
     {"nodes": [node("n0", "gene", {"gene_type": "rRNA"}), node("n1", "biological_process")],
      "predicates": [pred("p0", "involved in", "n0", "n1")],
      "logic": {"operator": "AND", "children": [{"operator": "NOT", "predicates": ["p0"]}]}},
     GENE_COUNT.format("g.gene_type =~ '(?i)rRNA' AND NOT EXISTS { (g)-[:involved_in]->(:biological_process) }")),
    ("fly", "OR between predicates",
     {"nodes": [node("n0", "gene", {"gene_type": "rRNA"}), node("n1", "biological_process"), node("n2", "molecular_function")],
      "predicates": [pred("p0", "involved in", "n0", "n1"), pred("p1", "enables", "n0", "n2")],
      "logic": {"operator": "AND", "children": [{"operator": "OR", "predicates": ["p0", "p1"]}]}},
     GENE_COUNT.format("g.gene_type =~ '(?i)rRNA' AND (EXISTS { (g)-[:involved_in]->(:biological_process) } "
                       "OR EXISTS { (g)-[:enables]->(:molecular_function) })")),
    ("human", "several values inside an AND group",
     {"nodes": [node("n0", "gene")], "predicates": [],
      "logic": {"operator": "AND", "nodes": {"node_id": "n0", "properties": {"gene_type": ["snoRNA", "scaRNA"], "chr": "21"}}}},
     GENE_COUNT.format("(g.gene_type =~ '(?i)snoRNA' OR g.gene_type =~ '(?i)scaRNA') AND g.chr =~ '(?i)chr21'")),
    ("human", "same property twice",
     {"nodes": [node("n0", "gene")], "predicates": [],
      "logic": {"operator": "OR", "nodes": {"node_id": "n0", "properties": {"gene_name": ["TP53", "BRCA1"]}}}},
     GENE_COUNT.format("g.gene_name =~ '(?i)TP53' OR g.gene_name =~ '(?i)BRCA1'")),
]


@pytest.fixture(scope="module")
def generator():
    logging.disable(logging.CRITICAL)
    from app.services.cypher_generator import CypherQueryGenerator
    return CypherQueryGenerator("./cypher_data")


def _returned(rows, label):
    import neo4j
    labelled, everything = set(), set()

    def walk(value):
        if isinstance(value, neo4j.graph.Node):
            everything.add(value.element_id)
            if label in value.labels:
                labelled.add(value.element_id)
        elif isinstance(value, neo4j.graph.Relationship):
            walk(value.start_node)
            walk(value.end_node)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)

    for row in rows:
        for value in row.values():
            walk(value)
    return labelled, everything


@pytest.mark.parametrize("species, name, request_, truth", CASES, ids=[c[1] for c in CASES])
def test_logic_matches_hand_written_cypher(generator, species, name, request_, truth):
    from app.lib.validator import validate_request
    request = copy.deepcopy(request_)
    node_map = validate_request(request, {
        "gene_involved_in_biological_process": {}, "gene_enables_molecular_function": {}}, None)
    result_query, total_query, _ = generator.query_Generator(request, node_map)

    genes, everything = _returned(generator.run_query(result_query, species=species), "gene")
    expected = generator.run_query(truth, species=species)[0]["c"]
    assert len(genes) == expected

    totals = generator.run_query(total_query, species=species)
    if expected:
        assert totals[0]["total_nodes"] == len(everything)

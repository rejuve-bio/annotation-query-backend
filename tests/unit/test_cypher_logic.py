"""Cypher generated for the boolean 'logic' section (no database needed).

Run: python -m pytest tests/unit/test_cypher_logic.py --noconftest
"""
import copy

import pytest

from app.lib.logic import LogicValidationError
from app.lib.validator import validate_request
from app.services.cypher_generator import CypherQueryGenerator

SCHEMA = {
    "gene_involved_in_biological_process": {},
    "gene_enables_molecular_function": {},
    "gene_transcribed_to_transcript": {},
    "transcript_translates_to_protein": {},
}


@pytest.fixture
def gen():
    # Build queries only; no Neo4j connection is made.
    return CypherQueryGenerator.__new__(CypherQueryGenerator)


def node(node_id, node_type, properties=None, id_=""):
    return {"node_id": node_id, "id": id_, "type": node_type, "properties": properties or {}}


def pred(pid, ptype, source, target):
    return {"predicate_id": pid, "type": ptype, "source": source, "target": target}


def generate(gen, request):
    node_map = validate_request(request, SCHEMA, None)
    return gen.query_Generator(request, node_map, limit=None)


def flat(query):
    return " ".join(query.split())


# --- property groups ------------------------------------------------------------

def test_or_group_across_properties(gen):
    request = {"nodes": [node("n0", "gene")], "predicates": [],
               "logic": {"operator": "OR", "nodes": {"node_id": "n0", "properties": {"gene_name": "N", "gene_type": "rRNA"}}}}
    result, total, _ = generate(gen, request)
    assert flat(result) == "MATCH (n0:gene) WHERE (n0.gene_name =~ '(?i)N' OR n0.gene_type =~ '(?i)rRNA') RETURN n0"
    assert "(n0.gene_name =~ '(?i)N' OR n0.gene_type =~ '(?i)rRNA')" in flat(total)


def test_several_values_for_one_property_mean_any_of_them(gen):
    request = {"nodes": [node("n0", "gene")], "predicates": [],
               "logic": {"operator": "AND", "nodes": {"node_id": "n0", "properties": {"gene_type": ["rRNA", "tRNA"], "chr": "21"}}}}
    result = flat(generate(gen, request)[0])
    assert "(n0.chr =~ '(?i)chr21' AND (n0.gene_type =~ '(?i)rRNA' OR n0.gene_type =~ '(?i)tRNA'))" in result


def test_not_treats_a_missing_property_as_not_matching(gen):
    request = {"nodes": [node("n0", "gene", {"chr": "chr1"})], "predicates": [],
               "logic": {"operator": "NOT", "nodes": {"node_id": "n0", "properties": {"gene_type": ["lncRNA", "misc_RNA"]}}}}
    result = flat(generate(gen, request)[0])
    assert "n0.chr =~ '(?i)chr1' AND NOT coalesce((n0.gene_type =~ '(?i)lncRNA' OR n0.gene_type =~ '(?i)misc_RNA'), false)" in result


def test_nested_groups(gen):
    logic = {"operator": "OR", "children": [
        {"operator": "AND", "nodes": {"node_id": "n0", "properties": {"gene_name": "N", "chr": "X"}}},
        {"operator": "AND", "nodes": {"node_id": "n0", "properties": {"gene_type": "rRNA"}}}]}
    request = {"nodes": [node("n0", "gene")], "predicates": [], "logic": logic}
    result = flat(generate(gen, request)[0])
    assert "((n0.chr =~ '(?i)chrX' AND n0.gene_name =~ '(?i)N') OR n0.gene_type =~ '(?i)rRNA')" in result


def test_values_are_escaped_and_property_names_checked(gen):
    request = {"nodes": [node("n0", "gene")], "predicates": [],
               "logic": {"operator": "OR", "nodes": {"node_id": "n0", "properties": {"gene_name": ["a.b' OR true //", "N"]}}}}
    result = flat(generate(gen, request)[0])
    assert "n0.gene_name =~ '(?i)a\\.b OR true //'" in result


def test_logic_conditions_apply_to_a_node_with_an_id(gen):
    request = {"nodes": [node("n0", "gene", id_="ENSG00000141510")], "predicates": [],
               "logic": {"operator": "NOT", "nodes": {"node_id": "n0", "properties": {"gene_type": "lncRNA"}}}}
    result = flat(generate(gen, request)[0])
    assert "MATCH (n0:gene {id: 'ENSG00000141510'}) WHERE NOT coalesce(n0.gene_type =~ '(?i)lncRNA', false)" in result


def test_unnormalized_values_are_refused_not_split_into_letters(gen):
    with pytest.raises(LogicValidationError, match="not normalized"):
        gen._render_property_condition("n0", "gene_type", "rRNA")


def test_callers_request_is_not_modified(gen):
    request = {"nodes": [node("n0", "gene", {"chr": "chr1"}), node("n1", "biological_process")],
               "predicates": [pred("p0", "involved in", "n0", "n1")],
               "logic": {"operator": "AND", "children": [{"operator": "NOT", "predicates": ["p0"]}]}}
    node_map = validate_request(request, SCHEMA, None)
    before = copy.deepcopy(request)
    gen.query_Generator(request, node_map)
    assert request == before
    assert all("_logic_conditions" not in n for n in request["nodes"])


# --- NOT on predicates ----------------------------------------------------------

def test_not_predicate_becomes_not_exists_and_far_node_is_dropped(gen):
    request = {"nodes": [node("n0", "gene", {"gene_type": "rRNA"}), node("n1", "biological_process")],
               "predicates": [pred("p0", "involved in", "n0", "n1")],
               "logic": {"operator": "AND", "children": [{"operator": "NOT", "predicates": ["p0"]}]}}
    result, total, label = generate(gen, request)
    assert flat(result) == ("MATCH (n0:gene) WHERE n0.gene_type =~ '(?i)rRNA' AND "
                            "NOT EXISTS { MATCH (n0)-[:involved_in]->(n1:biological_process) } RETURN n0")
    assert "n1_biological_process" not in label


def test_not_predicate_keeps_far_node_filters_inside_not_exists(gen):
    request = {"nodes": [node("n0", "gene", {"gene_type": "rRNA"}), node("n1", "biological_process", {"term_name": "x"})],
               "predicates": [pred("p0", "involved in", "n0", "n1")],
               "logic": {"operator": "AND", "children": [{"operator": "NOT", "predicates": ["p0"]}]}}
    result = flat(generate(gen, request)[0])
    assert "NOT EXISTS { MATCH (n0)-[:involved_in]->(n1:biological_process) WHERE n1.term_name =~ '(?i)x' }" in result


def test_not_predicate_on_a_far_node_with_list_values_is_refused(gen):
    request = {"nodes": [node("n0", "gene", {"gene_type": "rRNA"}), node("n1", "biological_process", {"term_name": "a, b"})],
               "predicates": [pred("p0", "involved in", "n0", "n1")],
               "logic": {"operator": "AND", "children": [{"operator": "NOT", "predicates": ["p0"]}]}}
    with pytest.raises(LogicValidationError, match="list values on node 'n1'"):
        generate(gen, request)


# --- OR between predicates --------------------------------------------------------

def or_request(gene_props=None):
    return {"nodes": [node("n0", "gene", gene_props or {"gene_type": "rRNA"}), node("n1", "biological_process"),
                      node("n2", "molecular_function")],
            "predicates": [pred("p0", "involved in", "n0", "n1"), pred("p1", "enables", "n0", "n2")],
            "logic": {"operator": "AND", "children": [{"operator": "OR", "predicates": ["p0", "p1"]}]}}


def test_or_predicates_are_separate_arms_with_an_or_check(gen):
    result = generate(gen, or_request())[0]
    assert result.count("CALL (n0) {") == 2
    assert "WITH * WHERE (size(p0) > 0 OR size(p1) > 0)" in result
    assert result.startswith("MATCH (n0:gene)\nWHERE n0.gene_type =~ '(?i)rRNA'")


def test_or_count_queries_check_arms_with_exists_and_count_each_arm_separately(gen):
    _, total, label = generate(gen, or_request())
    assert "OPTIONAL MATCH" not in total
    assert ("WITH n0 WHERE (EXISTS { MATCH (n0)-[p0:involved_in]->(n1:biological_process) } "
            "OR EXISTS { MATCH (n0)-[p1:enables]->(n2:molecular_function) })") in flat(total)
    assert flat(total).count("CALL (anchors) { UNWIND anchors AS n0") == 2
    assert "RETURN (size(anchors) + c_n1 + c_n2) AS total_nodes, (c_p0 + c_p1) AS total_edges" in total
    assert ("RETURN size(anchors) AS n0_gene, c_n1 AS n1_biological_process, c_p0 AS p0_involved_in, "
            "c_n2 AS n2_molecular_function, c_p1 AS p1_enables") in label


def test_or_with_comma_separated_values_is_refused(gen):
    request = or_request({"gene_name": "TP53, BRCA1"})
    with pytest.raises(LogicValidationError, match="comma-separated values"):
        generate(gen, request)


def test_or_groups_on_different_nodes_are_refused(gen):
    with pytest.raises(LogicValidationError, match="OR groups on different nodes"):
        gen._or_anchor([("n0", ["p0", "p1"]), ("n3", ["p2", "p3"])])


# --- requests without logic -----------------------------------------------------

def test_request_without_logic_takes_the_unchanged_path(gen):
    request = {"nodes": [node("n0", "gene", {"gene_name": "N"}), node("n1", "biological_process"), node("n2", "molecular_function")],
               "predicates": [pred("p0", "involved in", "n0", "n1"), pred("p1", "enables", "n0", "n2")]}
    result = generate(gen, request)[0]
    assert "WITH * WHERE size(p0) > 0 AND size(p1) > 0" in result


# --- count queries for multi-predicate requests (with or without logic) ---------

def test_multi_predicate_counts_use_arms_not_one_flat_match(gen):
    request = {"nodes": [node("n0", "gene", {"gene_name": "N"}), node("n1", "biological_process"), node("n2", "anatomy")],
               "predicates": [pred("p0", "involved in", "n0", "n1"), pred("p1", "expressed in", "n0", "n2")]}
    schema = {**SCHEMA, "gene_expressed_in_anatomy": {}}
    node_map = validate_request(request, schema, None)
    _, total, label = gen.query_Generator(request, node_map)
    assert ("WITH n0 WHERE EXISTS { MATCH (n0)-[p0:involved_in]->(n1:biological_process) } "
            "AND EXISTS { MATCH (n0)-[p1:expressed_in]->(n2:anatomy) }") in flat(total)
    assert flat(total).count("CALL (anchors) {") == 2
    assert "c_n1 AS n1_biological_process" in label and "c_p1 AS p1_expressed_in" in label


def test_counts_for_a_chain_walk_the_arm_once(gen):
    request = {"nodes": [node("n0", "gene", id_="ENSG00000141510"), node("n1", "transcript"), node("n2", "protein")],
               "predicates": [pred("p0", "transcribed to", "n0", "n1"), pred("p1", "translates to", "n1", "n2")]}
    _, total, _ = generate(gen, request)
    assert flat(total).count("CALL (anchors) {") == 1
    assert ("RETURN count(DISTINCT n1) AS c_n1, count(DISTINCT p0) AS c_p0, "
            "count(DISTINCT n2) AS c_n2, count(DISTINCT p1) AS c_p1") in flat(total)
    assert "RETURN (size(anchors) + c_n1 + c_n2) AS total_nodes, (c_p0 + c_p1) AS total_edges" in total


def test_virtual_overlaps_with_keeps_the_flat_count_query(gen):
    predicates = [pred("p0", "overlaps with", "n0", "n1"), pred("p1", "overlaps with", "n0", "n2")]
    request = {"nodes": [node("n0", "snp", {"chr": "chr1"}), node("n1", "enhancer"), node("n2", "promoter")],
               "predicates": predicates}
    _, total, _ = gen.query_Generator(request, {n["node_id"]: n for n in request["nodes"]})
    assert "apoc.create.vRelationship" in total and "CALL (anchors)" not in total

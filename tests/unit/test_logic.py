"""Validation and normalization of the boolean 'logic' section (no database needed).

Run: python -m pytest tests/unit/test_logic.py --noconftest
"""
import copy

import pytest

from app.core.config import settings
from app.lib.logic import (
    MAX_LOGIC_DEPTH,
    MAX_LOGIC_GROUPS,
    MAX_VALUES_PER_PROPERTY,
    LogicValidationError,
    QueryTooBroadError,
    counted_nodes_and_predicates,
    ensure_has_positive_filter,
    negated_predicate_ends,
    or_predicate_ends,
)
from app.lib.validator import validate_request

SCHEMA = {
    "gene_involved_in_biological_process": {},
    "gene_enables_molecular_function": {},
    "gene_transcribed_to_transcript": {},
    "transcript_translates_to_protein": {},
}


def node(node_id, node_type, properties=None, id_=""):
    return {"node_id": node_id, "id": id_, "type": node_type, "properties": properties or {}}


def pred(pid, ptype, source, target):
    return {"predicate_id": pid, "type": ptype, "source": source, "target": target}


def gene_request(logic=None, gene_props=None, with_bp=False, with_mf=False):
    nodes = [node("n0", "gene", gene_props)]
    predicates = []
    if with_bp:
        nodes.append(node("n1", "biological_process"))
        predicates.append(pred("p0", "involved in", "n0", "n1"))
    if with_mf:
        nodes.append(node("n2", "molecular_function"))
        predicates.append(pred("p1", "enables", "n0", "n2"))
    request = {"nodes": nodes, "predicates": predicates}
    if logic is not None:
        request["logic"] = logic
    return request


def or_names(*names):
    return {"operator": "OR", "nodes": {"node_id": "n0", "properties": {"gene_name": list(names)}}}


def validate(request):
    validate_request(request, SCHEMA, None)
    return request


# --- normalization ------------------------------------------------------------

def test_lone_group_at_root_is_wrapped_in_and():
    request = validate(gene_request(logic=or_names("TP53", "BRCA1")))
    assert request["logic"] == {"operator": "AND", "children": [
        {"operator": "OR", "nodes": {"node_id": "n0", "properties": {"gene_name": ["TP53", "BRCA1"]}}}]}


def test_operators_are_upper_cased_and_root_defaults_to_and():
    logic = {"children": [{"operator": "not", "nodes": {"node_id": "n0", "properties": {"gene_type": "lncRNA"}}}]}
    request = validate(gene_request(logic=logic, gene_props={"chr": "chr1"}))
    assert request["logic"]["operator"] == "AND"
    assert request["logic"]["children"][0]["operator"] == "NOT"


def test_values_become_lists_of_strings_and_chr_is_prefixed():
    logic = {"operator": "AND", "children": [
        {"operator": "OR", "nodes": {"node_id": "n0", "properties": {"gene_type": "lncRNA", "chr": 7}}}]}
    request = validate(gene_request(logic=logic))
    assert request["logic"]["children"][0]["nodes"]["properties"] == {"gene_type": ["lncRNA"], "chr": ["chr7"]}


def test_node_ids_in_logic_are_cleaned_like_the_nodes():
    request = gene_request(logic={"operator": "OR", "nodes": {"node_id": "n_0", "properties": {"gene_name": "N"}}})
    request["nodes"][0]["node_id"] = "n_0"
    validate(request)
    assert request["logic"]["children"][0]["nodes"]["node_id"] == "n0"


def test_request_without_logic_is_left_unchanged():
    request = gene_request(gene_props={"gene_name": "TP53"}, with_bp=True)
    before = copy.deepcopy(request)
    validate(request)
    assert "logic" not in request
    assert request["nodes"] == before["nodes"] and request["predicates"] == before["predicates"]


# --- strictness and limits ----------------------------------------------------

def test_unknown_key_in_group_is_rejected_with_a_hint():
    logic = {"operator": "AND", "children": [
        {"operater": "NOT", "nodes": {"node_id": "n0", "properties": {"gene_type": "lncRNA"}}}]}
    with pytest.raises(LogicValidationError, match="unknown key 'operater'.*did you mean 'operator'"):
        validate(gene_request(logic=logic, gene_props={"chr": "chr1"}))


def test_unknown_key_in_nodes_target_is_rejected():
    logic = {"operator": "OR", "nodes": {"node_id": "n0", "properties": {"gene_name": "N"}, "propertie": {}}}
    with pytest.raises(LogicValidationError, match="unknown key 'propertie'"):
        validate(gene_request(logic=logic))


def test_unknown_key_at_root_is_rejected():
    with pytest.raises(LogicValidationError, match="unknown key 'childs'"):
        validate(gene_request(logic={"operator": "AND", "childs": []}))


def test_invalid_operator_is_rejected():
    with pytest.raises(LogicValidationError, match="invalid operator"):
        validate(gene_request(logic={"operator": "XOR", "nodes": {"node_id": "n0", "properties": {"gene_name": "N"}}}))


def test_nesting_deeper_than_the_limit_is_rejected():
    group = {"operator": "AND", "nodes": {"node_id": "n0", "properties": {"gene_name": "N"}}}
    for _ in range(MAX_LOGIC_DEPTH):
        group = {"operator": "AND", "children": [group]}
    with pytest.raises(LogicValidationError, match="nested too deeply"):
        validate(gene_request(logic={"operator": "AND", "children": [group]}))


def test_more_groups_than_the_limit_is_rejected():
    children = [{"operator": "OR", "nodes": {"node_id": "n0", "properties": {f"p{i}": "x"}}}
                for i in range(MAX_LOGIC_GROUPS + 1)]
    with pytest.raises(LogicValidationError, match="too many groups"):
        validate(gene_request(logic={"operator": "AND", "children": children}))


def test_more_values_than_the_limit_is_rejected():
    with pytest.raises(LogicValidationError, match="too many values"):
        validate(gene_request(logic=or_names(*[f"G{i}" for i in range(MAX_VALUES_PER_PROPERTY + 1)])))


def test_empty_and_non_string_values_are_rejected():
    for bad in ([], "", "  ", [True], [{"a": 1}]):
        with pytest.raises(LogicValidationError):
            validate(gene_request(logic={"operator": "OR", "nodes": {"node_id": "n0", "properties": {"gene_name": bad}}}))


# --- security -----------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "gene_name = 'x' OR true WITH n0 MATCH (z) DETACH DELETE z //",
    "a.b", "a b", "a)", "1abc", "a-b",
])
def test_unsafe_property_name_in_logic_is_rejected(name):
    logic = {"operator": "OR", "nodes": {"node_id": "n0", "properties": {name: "x", "gene_type": "y"}}}
    with pytest.raises(LogicValidationError, match="invalid property name"):
        validate(gene_request(logic=logic))


# --- unsupported / disallowed shapes ------------------------------------------

def test_not_on_a_whole_node_is_rejected():
    with pytest.raises(LogicValidationError, match="NOT on the whole node"):
        validate(gene_request(logic={"operator": "NOT", "nodes": {"node_id": "n0", "properties": {}}},
                              gene_props={"chr": "chr1"}))


def test_position_filter_inside_logic_is_rejected():
    with pytest.raises(LogicValidationError, match="position filter 'start'"):
        validate(gene_request(logic={"operator": "OR", "nodes": {"node_id": "n0", "properties": {"start": "1"}}}))


def test_property_in_both_properties_and_logic_is_rejected():
    with pytest.raises(LogicValidationError, match="in both 'properties' and 'logic'"):
        validate(gene_request(logic=or_names("N"), gene_props={"gene_name": "TP53"}))


def test_unknown_node_and_predicate_references_are_rejected():
    with pytest.raises(LogicValidationError, match="unknown node 'n9'"):
        validate(gene_request(logic={"operator": "OR", "nodes": {"node_id": "n9", "properties": {"gene_name": "N"}}}))
    with pytest.raises(LogicValidationError, match="unknown predicate 'p9'"):
        validate(gene_request(logic={"operator": "AND", "children": [{"operator": "NOT", "predicates": ["p9"]}]},
                              gene_props={"chr": "chr1"}, with_bp=True))


def test_predicate_group_must_sit_under_an_and_root():
    logic = {"operator": "OR", "children": [{"operator": "AND", "predicates": ["p0"]}]}
    with pytest.raises(LogicValidationError, match="predicate groups must sit directly under"):
        validate(gene_request(logic=logic, gene_props={"chr": "chr1"}, with_bp=True))


def test_combined_group_across_two_nodes_is_rejected():
    logic = {"operator": "AND", "children": [{"operator": "OR", "children": [
        {"operator": "AND", "nodes": {"node_id": "n0", "properties": {"gene_name": "N"}}},
        {"operator": "AND", "nodes": {"node_id": "n1", "properties": {"term_name": "x"}}}]}]}
    with pytest.raises(LogicValidationError, match="exactly one node"):
        validate(gene_request(logic=logic, with_bp=True))


def test_duplicate_predicate_ids_are_rejected_only_with_logic():
    request = gene_request(gene_props={"chr": "chr1"}, with_bp=True, with_mf=True)
    request["predicates"][1]["predicate_id"] = "p0"
    validate(copy.deepcopy(request))  # fine without logic
    request["logic"] = {"operator": "AND", "children": [{"operator": "NOT", "predicates": ["p0"]}]}
    with pytest.raises(Exception, match="duplicate predicate_id 'p0'"):
        validate(request)


def test_same_predicate_in_two_groups_is_rejected():
    logic = {"operator": "AND", "children": [
        {"operator": "NOT", "predicates": ["p0"]}, {"operator": "AND", "predicates": ["p0"]}]}
    with pytest.raises(LogicValidationError, match="more than one predicate group"):
        validate(gene_request(logic=logic, gene_props={"chr": "chr1"}, with_bp=True))


# --- NOT / OR on predicates: which end is kept --------------------------------

def test_not_predicate_keeps_the_source_when_neither_end_is_used_elsewhere():
    p0 = pred("p0", "involved in", "n0", "n1")
    assert negated_predicate_ends(p0, [p0]) == ("n0", "n1")


def test_not_predicate_keeps_the_end_used_by_another_predicate():
    p0 = pred("p0", "transcribed to", "n0", "n1")
    p1 = pred("p1", "translates to", "n1", "n2")
    assert negated_predicate_ends(p1, [p0, p1]) == ("n1", "n2")


def test_not_predicate_with_both_ends_used_elsewhere_is_rejected():
    p0, p1, p2 = pred("p0", "a", "n0", "n1"), pred("p1", "b", "n1", "n2"), pred("p2", "c", "n0", "n2")
    with pytest.raises(LogicValidationError, match="both used by other predicates"):
        negated_predicate_ends(p2, [p0, p1, p2])


def test_or_predicates_keep_the_shared_node():
    p0, p1 = pred("p0", "involved in", "n0", "n1"), pred("p1", "enables", "n0", "n2")
    assert or_predicate_ends(["p0", "p1"], [p0, p1]) == ("n0", {"p0": "n1", "p1": "n2"})


def test_or_predicates_that_share_no_node_are_rejected():
    p0, p1 = pred("p0", "a", "n0", "n1"), pred("p1", "b", "n2", "n3")
    with pytest.raises(LogicValidationError, match="share no node"):
        or_predicate_ends(["p0", "p1"], [p0, p1])


def test_label_counts_skip_negated_predicates_and_their_far_nodes():
    request = validate(gene_request(logic={"operator": "AND", "children": [{"operator": "NOT", "predicates": ["p0"]}]},
                                    gene_props={"chr": "chr1"}, with_bp=True))
    nodes, predicates = counted_nodes_and_predicates(request)
    assert [n["node_id"] for n in nodes] == ["n0"] and predicates == []


# --- the "too broad" rule -----------------------------------------------------

def test_no_filter_at_all_is_too_broad():
    with pytest.raises(QueryTooBroadError, match="too broad"):
        validate(gene_request())


def test_predicates_alone_are_too_broad():
    with pytest.raises(QueryTooBroadError):
        validate(gene_request(with_bp=True))


def test_only_negative_conditions_are_too_broad():
    with pytest.raises(QueryTooBroadError):
        validate(gene_request(logic={"operator": "NOT", "nodes": {"node_id": "n0", "properties": {"gene_type": "lncRNA"}}}))
    with pytest.raises(QueryTooBroadError):
        validate(gene_request(logic={"operator": "AND", "children": [{"operator": "NOT", "predicates": ["p0"]}]},
                              with_bp=True))


def test_or_with_a_negative_branch_is_too_broad():
    logic = {"operator": "OR", "children": [
        {"operator": "AND", "nodes": {"node_id": "n0", "properties": {"gene_name": "N"}}},
        {"operator": "NOT", "nodes": {"node_id": "n0", "properties": {"gene_type": "lncRNA"}}}]}
    with pytest.raises(QueryTooBroadError):
        validate(gene_request(logic={"operator": "AND", "children": [logic]}))


def test_empty_property_value_does_not_count_as_a_filter():
    with pytest.raises(QueryTooBroadError):
        validate(gene_request(gene_props={"gene_name": ""}))


@pytest.mark.parametrize("request_", [
    gene_request(gene_props={"gene_type": "lncRNA"}),
    gene_request(logic=or_names("TP53", "BRCA1")),
    gene_request(logic={"operator": "AND", "children": [or_names("N"), {"operator": "NOT", "predicates": ["p0"]}]},
                 with_bp=True),
])
def test_positive_filters_are_accepted(request_):
    validate(request_)


def test_node_id_counts_as_a_filter():
    request = gene_request(with_bp=True)
    request["nodes"][0]["id"] = "ENSG00000148400"
    validate(request)


def test_rule_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_POSITIVE_FILTER", False)
    validate(gene_request(with_bp=True))


def test_ensure_has_positive_filter_works_on_raw_requests():
    ensure_has_positive_filter({"nodes": [{"id": "", "ids": ["A", "B"], "properties": {}}]})

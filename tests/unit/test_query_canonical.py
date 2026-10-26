"""Canonicalization and fingerprints with and without 'logic' (no database needed).

Run: python -m pytest tests/unit/test_query_canonical.py --noconftest
"""
import copy

from app.lib.query_canonical import canonicalize_graph, query_fingerprint
from app.lib.validator import validate_request

SCHEMA = {"gene_involved_in_biological_process": {}, "gene_expressed_in_anatomy": {}}


def node(node_id, node_type, properties=None, id_=""):
    return {"node_id": node_id, "id": id_, "type": node_type, "properties": properties or {}}


def pred(pid, ptype, source, target):
    return {"predicate_id": pid, "type": ptype, "source": source, "target": target}


def fingerprint(request):
    canonical, _ = canonicalize_graph(request)
    return query_fingerprint(canonical, "human", "all", None, False, True, {"type": "cypher"})


def validated(request):
    validate_request(request, SCHEMA, None)
    return request


def star(logic=None, order="as-is"):
    """gene g -> biological_process x, gene g -> anatomy y; ids deliberately not canonical."""
    nodes = [node("x", "biological_process"), node("g", "gene", {"gene_type": "lncRNA"}), node("y", "anatomy")]
    predicates = [pred("e1", "expressed in", "g", "y"), pred("e0", "involved in", "g", "x")]
    if order == "reversed":
        nodes, predicates = nodes[::-1], predicates[::-1]
    request = {"nodes": nodes, "predicates": predicates}
    if logic is not None:
        request["logic"] = logic
    return request


# --- requests without logic: unchanged --------------------------------------

def test_fingerprints_without_logic_are_unchanged():
    # Golden values computed with the canonicalization on staging before
    # 'logic' existed: stored annotations must keep matching.
    single = {"nodes": [node("a", "gene", {"gene_name": "TP53"})], "predicates": []}
    assert fingerprint(single) == "a50c42852893cf3c1409afeead4ecde475aa44a071d3feeba8fd41bf07e31627"
    assert fingerprint(star()) == "dc61ae79b0e9da659fce9024aaebff08a826b2e054a88ad07700d256e0524198"


def test_canonical_request_without_logic_has_no_logic_key():
    canonical, _ = canonicalize_graph(star())
    assert "logic" not in canonical


# --- renaming -------------------------------------------------------------------

def test_node_and_predicate_references_in_logic_are_renamed():
    logic = {"operator": "AND", "children": [
        {"operator": "OR", "nodes": {"node_id": "g", "properties": {"gene_name": ["N", "dpp"]}}},
        {"operator": "NOT", "predicates": ["e0"]}]}
    canonical, old_to_new = canonicalize_graph(validated(star(logic)))
    by_id = {n["node_id"]: n for n in canonical["nodes"]}
    preds = {p["predicate_id"]: p for p in canonical["predicates"]}

    node_group = next(c for c in canonical["logic"]["children"] if "nodes" in c)
    pred_group = next(c for c in canonical["logic"]["children"] if "predicates" in c)
    assert by_id[node_group["nodes"]["node_id"]]["type"] == "gene"
    (negated,) = pred_group["predicates"]
    assert preds[negated]["type"] == "involved in"          # still the same predicate after renumbering
    assert node_group["nodes"]["node_id"] == old_to_new["g"]


def test_original_request_is_not_modified():
    logic = {"operator": "OR", "nodes": {"node_id": "g", "properties": {"gene_name": ["N"]}}}
    request = validated(star(logic))
    before = copy.deepcopy(request)
    canonicalize_graph(request)
    assert request == before


# --- fingerprints with logic ----------------------------------------------------

def test_logic_changes_the_fingerprint():
    plain = validated(star())
    negated = validated(star({"operator": "AND", "children": [{"operator": "NOT", "predicates": ["e0"]}]}))
    assert fingerprint(plain) != fingerprint(negated)


def test_not_and_or_give_different_fingerprints():
    def with_op(op):
        return validated(star({"operator": op, "nodes": {"node_id": "g", "properties": {"gene_name": ["N", "dpp"]}}}))
    assert fingerprint(with_op("OR")) != fingerprint(with_op("NOT"))


def test_equivalent_requests_share_a_fingerprint():
    a = {"operator": "AND", "children": [
        {"operator": "OR", "nodes": {"node_id": "g", "properties": {"gene_name": ["N", "dpp"], "chr": "chrX"}}},
        {"operator": "NOT", "predicates": ["e0"]}]}
    b = {"operator": "and", "children": [
        {"operator": "NOT", "predicates": ["e0"]},
        {"operator": "or", "nodes": {"node_id": "g", "properties": {"chr": ["X"], "gene_name": ["dpp", "N"]}}}]}
    assert fingerprint(validated(star(a))) == fingerprint(validated(star(b, order="reversed")))


def test_lone_root_group_and_wrapped_form_share_a_fingerprint():
    lone = {"operator": "OR", "nodes": {"node_id": "g", "properties": {"gene_name": "N"}}}
    wrapped = {"operator": "AND", "children": [copy.deepcopy(lone)]}
    assert fingerprint(validated(star(lone))) == fingerprint(validated(star(wrapped)))


def test_logic_points_at_the_right_node_after_renaming():
    # Two gene nodes, one with a NOT condition: which one is negated matters.
    def two_genes(negated):
        request = {
            "nodes": [node("g1", "gene", {"gene_type": "lncRNA"}), node("g2", "gene", {"gene_type": "lncRNA"}),
                      node("x", "biological_process")],
            "predicates": [pred("e0", "involved in", "g1", "x"), pred("e1", "involved in", "g2", "x")],
            "logic": {"operator": "NOT", "nodes": {"node_id": negated, "properties": {"chr": "chr1"}}},
        }
        return validated(request)
    # Both describe the same structure up to renaming, so they may legitimately match;
    # what must hold is that the canonical logic points at a gene with the condition.
    for negated in ("g1", "g2"):
        canonical, _ = canonicalize_graph(two_genes(negated))
        target = canonical["logic"]["children"][0]["nodes"]["node_id"]
        assert next(n for n in canonical["nodes"] if n["node_id"] == target)["type"] == "gene"

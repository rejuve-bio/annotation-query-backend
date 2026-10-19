import pytest
from pydantic import ValidationError

from app.api.api_v1.endpoints.neighbourhood import NeighbourhoodRequest
from app.services.cypher_generator import CypherQueryGenerator


class FakeNode(dict):
    def __init__(self, eid, label, node_id, **props):
        super().__init__(id=node_id, **props)
        self.element_id = eid
        self.labels = frozenset([label])


class FakeRel(dict):
    def __init__(self, eid, rel_type, start, end, **props):
        super().__init__(**props)
        self.element_id = eid
        self.type = rel_type
        self.start_node = start
        self.end_node = end


# seed -> g1, g2, g3 (regulates); g1 -> a1 (expressed_in); g1 <-> g2 (paralog_of)
SEED = FakeNode("e0", "gene", "G0", gene_name="seed")
G1 = FakeNode("e1", "gene", "G1", gene_name="one")
G2 = FakeNode("e2", "gene", "G2", gene_name="two")
G3 = FakeNode("e3", "gene", "G3", gene_name="three")
A1 = FakeNode("e4", "anatomy", "A1", term_name="eye disc")
EDGES = [
    FakeRel("r1", "regulates", SEED, G1, score="1"),
    FakeRel("r2", "regulates", SEED, G2),
    FakeRel("r3", "regulates", SEED, G3),
    FakeRel("r4", "expressed_in", G1, A1),
    FakeRel("r5", "paralog_of", G1, G2),
]


class FakeGenerator(CypherQueryGenerator):
    """CypherQueryGenerator with the database replaced by the graph above."""

    def __init__(self):
        self.queries = []

    def run_query(self, query_code, stop_event=None, species="human", query_type=None, parameters=None):
        text = getattr(query_code, "text", query_code)
        self.queries.append((text, parameters))
        params = parameters or {}
        if "RETURN s LIMIT 1" in text:
            return [{"s": SEED}] if params["id"] == "G0" else []
        if "count(*) AS count" in text:
            return [{"edge_type": "regulates", "neighbour_type": "gene", "direction": "out", "count": 3}]
        # hop query: expand each frontier node, honouring direction + type filters
        rows = []
        for eid in params["frontier"]:
            per_node = 0
            for rel in EDGES:
                if "[r:" in text and f":{rel.type}" not in text and f"|{rel.type}" not in text:
                    continue
                if rel.start_node.element_id == eid and "<-" not in text:
                    source, other = rel.start_node, rel.end_node
                elif rel.end_node.element_id == eid and "]->" not in text:
                    source, other = rel.end_node, rel.start_node
                else:
                    continue
                if params.get("node_types") and not (other.labels & set(params["node_types"])):
                    continue
                if per_node >= params["per_node_fetch"]:
                    break
                rows.append({"n": source, "r": rel, "m": other})
                per_node += 1
        return rows[:params["hop_fetch"]]

    def _neighbourhood_vocabulary(self, species):
        return ({"gene", "anatomy"}, {"regulates", "expressed_in", "paralog_of"},
                {"id", "score", "evidence"})


def request(**overrides):
    body = {"seed": {"type": "gene", "id": "G0"}, "max_hops": 1,
            "hops": [{"edge_types": [], "direction": "both", "node_types": [], "limit": 500}],
            "per_node_limit": 50, "properties": True}
    body.update(overrides)
    return body


def node_ids(result):
    return {n["data"]["id"]: n["data"]["hop"] for n in result["nodes"]}


def test_one_hop_out():
    r = FakeGenerator().expand_neighbourhood(
        request(hops=[{"edge_types": ["regulates"], "direction": "out", "limit": 500}]))
    assert r["seed"]["found"] is True
    assert node_ids(r) == {"gene G0": 0, "gene G1": 1, "gene G2": 1, "gene G3": 1}
    assert r["edge_count"] == 3 and r["node_count"] == 4
    assert r["node_count_by_label"] == [{"label": "gene", "count": 4}]
    assert r["hops"] == [{"hop": 1, "node_count": 3, "edge_count": 3, "truncated": False, "ranked_by": None}]
    assert r["seed_degree"][0]["count"] == 3


def test_edge_keeps_true_direction_and_properties():
    r = FakeGenerator().expand_neighbourhood(
        request(hops=[{"edge_types": ["regulates"], "direction": "out", "limit": 500}]))
    edge = next(e["data"] for e in r["edges"] if e["data"]["target"] == "gene G1")
    assert edge["source"] == "gene G0" and edge["label"] == "regulates"
    assert edge["edge_id"] == "gene_regulates_gene" and edge["score"] == "1" and edge["hop"] == 1


def test_two_hops_with_per_hop_filters():
    r = FakeGenerator().expand_neighbourhood(request(max_hops=2, hops=[
        {"edge_types": ["regulates"], "direction": "out", "limit": 500},
        {"edge_types": ["expressed_in"], "direction": "out", "node_types": ["anatomy"], "limit": 500},
    ]))
    assert node_ids(r)["anatomy A1"] == 2
    assert [h["edge_count"] for h in r["hops"]] == [3, 1]


def test_last_hop_filter_repeats():
    # One filter, two hops: hop 2 also only follows 'regulates', so nothing new.
    r = FakeGenerator().expand_neighbourhood(
        request(max_hops=2, hops=[{"edge_types": ["regulates"], "direction": "out", "limit": 500}]))
    assert r["hops"][1]["edge_count"] == 0


def test_visited_nodes_not_re_expanded_but_edges_kept():
    # g1 -paralog_of- g2 links two hop-1 nodes: the edge is returned at hop 2,
    # neither node is re-added.
    r = FakeGenerator().expand_neighbourhood(request(max_hops=2, hops=[
        {"edge_types": ["regulates"], "direction": "out", "limit": 500},
        {"edge_types": ["paralog_of"], "direction": "both", "limit": 500},
    ]))
    assert r["hops"][1] == {"hop": 2, "node_count": 0, "edge_count": 1, "truncated": False, "ranked_by": None}
    assert node_ids(r)["gene G2"] == 1


def test_hop_limit_truncates():
    r = FakeGenerator().expand_neighbourhood(
        request(hops=[{"edge_types": ["regulates"], "direction": "out", "limit": 2}]))
    assert r["edge_count"] == 2 and r["truncated"] is True and r["hops"][0]["truncated"] is True


def test_per_node_limit_ignored_for_single_seed():
    # per_node_limit=1 would cut hop 1 to one edge; with only the seed in the
    # frontier the hop limit applies instead.
    r = FakeGenerator().expand_neighbourhood(
        request(per_node_limit=1, hops=[{"edge_types": ["regulates"], "direction": "out", "limit": 500}]))
    assert r["edge_count"] == 3 and r["truncated"] is False


def test_missing_seed():
    r = FakeGenerator().expand_neighbourhood(request(seed={"type": "gene", "id": "NOPE"}))
    assert r["seed"]["found"] is False and r["nodes"] == [] and r["hops"] == []


def test_ids_are_parameters_not_interpolated():
    gen = FakeGenerator()
    gen.expand_neighbourhood(request(seed={"type": "gene", "id": "x' OR 1=1 //"}))
    seed_query, params = gen.queries[0]
    assert "OR 1=1" not in seed_query and params["id"] == "x' OR 1=1 //"


def test_properties_off_keeps_only_name():
    r = FakeGenerator().expand_neighbourhood(request(properties=False))
    seed = next(n["data"] for n in r["nodes"] if n["data"]["hop"] == 0)
    assert seed == {"id": "gene G0", "type": "gene", "hop": 0, "name": "seed"}


def test_hop_callback_called_per_hop():
    seen = []
    FakeGenerator().expand_neighbourhood(request(max_hops=2), on_hop_complete=seen.append)
    assert [h["hop"] for h in seen] == [1, 2]


def test_validate_unknown_types():
    errors = FakeGenerator().validate_neighbourhood_request(
        request(seed={"type": "gnee", "id": "G0"},
                hops=[{"edge_types": ["regulatez"], "node_types": ["anatomyy"]}]), "fly")
    assert len(errors) == 3


def test_validate_unknown_edge_properties():
    errors = FakeGenerator().validate_neighbourhood_request(
        request(hops=[{"order_by": "scor", "where": [{"property": "evidnce", "op": "=", "value": "IMP"}]}]), "fly")
    assert errors == ["hops[0]: unknown edge property for fly: 'evidnce'",
                      "hops[0]: unknown edge property for fly: 'scor'"]


def hop_query(**hop):
    return FakeGenerator()._neighbourhood_hop_query({"limit": 10, **hop})


def test_unranked_hop_has_no_order():
    cypher, params = hop_query(edge_types=["regulates"])
    assert "ORDER BY" not in cypher and "order_key" not in params


def test_ranked_hop_orders_inner_and_outer_nulls_last():
    cypher, params = hop_query(order_by="score")
    assert params["order_key"] == "score"
    assert "toFloat(r[$order_key])" in cypher
    # per-node (inside CALL) and across the hop (outer), nulls last
    assert cypher.count("ORDER BY CASE WHEN rank IS NULL THEN 1 ELSE 0 END, rank DESC") == 2
    cypher, _ = hop_query(order_by="score", order="asc")
    assert "rank ASC" in cypher


def test_where_conditions_are_parameterised():
    cypher, params = hop_query(where=[
        {"property": "score", "op": ">=", "value": 5},
        {"property": "evidence", "op": "in", "value": ["IMP", "IDA"]},
        {"property": "evidence_type", "op": "=", "value": "small_scale_evidence"},
        {"property": "DIOPT_score", "op": "!=", "value": 1},
        {"property": "source", "op": "not_in", "value": ["STRING"]},
    ])
    assert "toFloat(r[$wk0]) >= $wv0" in cypher
    assert "toString(r[$wk1]) IN $wv1" in cypher
    assert "toString(r[$wk2]) = $wv2" in cypher
    assert "toFloat(r[$wk3]) <> $wv3" in cypher
    assert "NOT toString(r[$wk4]) IN $wv4" in cypher
    assert params["wk1"] == "evidence" and params["wv1"] == ["IMP", "IDA"]
    # property names and values never appear in the query text
    for name in ("score", "evidence", "small_scale_evidence", "STRING"):
        assert name not in cypher


def test_node_types_and_where_combined_with_and():
    cypher, params = hop_query(node_types=["anatomy"], where=[{"property": "score", "op": ">", "value": 1}])
    assert "WHERE any(l IN labels(m) WHERE l IN $node_types) AND toFloat(r[$wk0]) > $wv0" in cypher
    assert params["node_types"] == ["anatomy"]


def test_ranked_by_reported_in_hop_summary():
    r = FakeGenerator().expand_neighbourhood(
        request(hops=[{"edge_types": ["regulates"], "direction": "out", "limit": 500, "order_by": "score"}]))
    assert r["hops"][0]["ranked_by"] == "score"


@pytest.mark.parametrize("cond", [
    {"property": "score", "op": ">=", "value": "high"},       # numeric op, text value
    {"property": "score", "op": "in", "value": "IMP"},        # 'in' needs a list
    {"property": "score", "op": "in", "value": []},
    {"property": "score", "op": "=", "value": ["a", "b"]},    # '=' needs one value
    {"property": "score", "op": "~=", "value": 1},
    {"property": "r.score) OR 1=1 //", "op": "=", "value": 1},
])
def test_edge_condition_rejects(cond):
    with pytest.raises(ValidationError):
        NeighbourhoodRequest(seed={"type": "gene", "id": "x"}, hops=[{"where": [cond]}])


def test_order_by_rejects_bad_name():
    with pytest.raises(ValidationError):
        NeighbourhoodRequest(seed={"type": "gene", "id": "x"}, hops=[{"order_by": "score DESC; //"}])


def test_unsafe_label_rejected_by_generator():
    with pytest.raises(ValueError):
        FakeGenerator()._neighbourhood_hop_query({"edge_types": ["a]-() DETACH DELETE n //"]})


@pytest.mark.parametrize("body", [
    {"seed": {"type": "gene", "id": "x"}, "max_hops": 9},
    {"seed": {"type": "gene", "id": "x"}, "species": "mouse"},
    {"seed": {"type": "gene) DELETE n", "id": "x"}},
    {"seed": {"type": "gene", "id": ""}},
    {"seed": {"type": "gene", "id": "x"}, "hops": [{"direction": "sideways"}]},
    {"seed": {"type": "gene", "id": "x"}, "hops": [{"edge_types": ["bad type"]}]},
    {"seed": {"type": "gene", "id": "x"}, "hops": [{"limit": 0}]},
    {"seed": {"type": "gene", "id": "x"}, "hops": []},
])
def test_request_model_rejects(body):
    with pytest.raises(ValidationError):
        NeighbourhoodRequest(**body)


def test_request_model_defaults():
    body = NeighbourhoodRequest(seed={"type": "gene", "id": "FBGN0004647"})
    assert body.species == "human" and body.max_hops == 1
    assert body.hops[0].direction == "both" and body.hops[0].limit == 500


def test_synonyms_not_returned():
    node = FakeNode("e9", "gene", "G9", gene_name="nine", synonym='["a", "b"]', synonyms='["c"]', chr="X")
    data = FakeGenerator()._neighbourhood_node(node, 1, properties=True)
    assert "synonym" not in data and "synonyms" not in data
    assert data["chr"] == "X" and data["name"] == "nine"


def test_vocabulary_cache_expires(monkeypatch):
    calls = []

    class CountingGenerator(CypherQueryGenerator):
        def __init__(self):
            pass

        def run_query(self, query_code, species="human", query_type=None, **kwargs):
            calls.append(query_code)
            return []

    gen = CountingGenerator()
    clock = [1000.0]
    monkeypatch.setattr("app.services.cypher_generator.time.monotonic", lambda: clock[0])
    gen._neighbourhood_vocabulary("fly")
    gen._neighbourhood_vocabulary("fly")
    assert len(calls) == 3                      # labels, rel types, property keys: read once
    clock[0] += gen._NEIGHBOURHOOD_VOCAB_TTL_S + 1
    gen._neighbourhood_vocabulary("fly")
    assert len(calls) == 6                      # re-read after the TTL


def test_transaction_timeout_is_not_retried():
    from app.lib.db_resilience import FailureClassifier, FailureKind

    class TimedOut(Exception):
        code = "Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration"

    exc = TimedOut("The transaction has not completed within the timeout specified ... timed out")
    assert FailureClassifier.classify(exc) == FailureKind.PERMANENT

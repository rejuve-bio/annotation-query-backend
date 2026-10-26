"""Cost check, slow-queue routing and backend logic support (no database needed).

Run: python -m pytest tests/unit/test_query_cost.py --noconftest
"""
import pytest

from app.core.config import settings
from app.lib.query_cost import REFUSE, RUN, SLOW, assess_query_cost, needs_cost_check, too_broad_message


def node(node_id, node_type, properties=None, id_=""):
    return {"node_id": node_id, "id": id_, "type": node_type, "properties": properties or {}}


def pred(pid, ptype, source, target):
    return {"predicate_id": pid, "type": ptype, "source": source, "target": target}


class FakeBackend:
    def __init__(self, *estimates):
        self.estimates = list(estimates)
        self.calls = 0

    def estimate_rows(self, query, species="human"):
        self.calls += 1
        return self.estimates.pop(0)


BROAD = {"nodes": [node("n0", "gene", {"gene_type": "protein_coding"}), node("n1", "gene")],
         "predicates": [pred("p0", "coexpressed with", "n0", "n1")]}


@pytest.fixture(autouse=True)
def limits(monkeypatch):
    monkeypatch.setattr(settings, "QUERY_COST_CHECK_ENABLED", True)
    monkeypatch.setattr(settings, "QUERY_COST_SOFT_LIMIT", 5_000_000)
    monkeypatch.setattr(settings, "QUERY_COST_HARD_LIMIT", 30_000_000)


# --- when the check runs ----------------------------------------------------

def test_single_node_requests_skip_the_check():
    assert not needs_cost_check({"nodes": [node("n0", "gene", {"gene_name": "TP53"})], "predicates": []})


def test_requests_anchored_by_one_id_skip_the_check():
    request = {"nodes": [node("n0", "gene", id_="ENSG00000141510"), node("n1", "transcript")],
               "predicates": [pred("p0", "transcribed to", "n0", "n1")]}
    assert not needs_cost_check(request)


def test_comma_separated_ids_still_get_checked():
    request = {"nodes": [node("n0", "gene", id_="ENSG1, ENSG2"), node("n1", "transcript")],
               "predicates": [pred("p0", "transcribed to", "n0", "n1")]}
    assert needs_cost_check(request)


def test_multi_node_and_logic_requests_get_checked():
    assert needs_cost_check(BROAD)
    assert needs_cost_check({"nodes": [node("n0", "gene")], "predicates": [], "logic": {"operator": "AND", "children": []}})


# --- decisions ----------------------------------------------------------------

@pytest.mark.parametrize("estimates, action", [
    ((3_508_213, 78_691), RUN),          # regex-filtered gene -> process & tissue (estimate floor)
    ((11_023_898, 11_023_898), SLOW),    # human coexpression
    ((37_375_099, 37_375_099), REFUSE),  # SNPs on a chromosome -> gene
    ((1_000, 40_000_000), REFUSE),       # the count query alone can trigger it
])
def test_decision_from_the_peak_estimate(estimates, action):
    decision = assess_query_cost(FakeBackend(*estimates), ["result", "count", "labels"], "human", BROAD)
    assert decision.action == action and decision.estimated_rows == max(estimates)


def test_only_result_and_total_count_queries_are_explained():
    backend = FakeBackend(10, 10, 10)
    assess_query_cost(backend, ["result", "count", "labels"], "human", BROAD)
    assert backend.calls == 2


def test_failed_estimate_never_blocks_a_query():
    assert assess_query_cost(FakeBackend(None), ["result", "count"], "human", BROAD).action == RUN


def test_backend_without_estimates_runs():
    assert assess_query_cost(object(), ["result", "count"], "human", BROAD).action == RUN


def test_check_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "QUERY_COST_CHECK_ENABLED", False)
    backend = FakeBackend(99_000_000, 99_000_000)
    assert assess_query_cost(backend, ["result", "count"], "human", BROAD).action == RUN
    assert backend.calls == 0


def test_too_broad_message_gives_the_estimate_and_a_hint():
    message = too_broad_message(37_375_099)
    assert "37,375,099" in message and "Add a filter" in message


# --- slow-queue routing -------------------------------------------------------

def test_slow_predicate_types_match_request_spelling():
    from app.workers.task_handler import is_slow_query
    assert is_slow_query(BROAD)  # "coexpressed with" (space) is in the slow set as coexpressed_with


def test_three_predicates_go_to_the_slow_queue():
    from app.workers.task_handler import is_slow_query
    request = {"nodes": [node("n0", "gene", {"gene_name": "N"}), node("n1", "biological_process"),
                         node("n2", "molecular_function"), node("n3", "transcript")],
               "predicates": [pred("p0", "involved in", "n0", "n1"), pred("p1", "enables", "n0", "n2"),
                              pred("p2", "transcribed to", "n0", "n3")]}
    assert is_slow_query(request)
    request["predicates"] = request["predicates"][:2]
    request["nodes"] = request["nodes"][:3]
    assert not is_slow_query(request)


def test_or_between_predicates_goes_to_the_slow_queue():
    from app.workers.task_handler import is_slow_query
    request = {"nodes": [node("n0", "gene", {"gene_name": "N"}), node("n1", "biological_process"), node("n2", "molecular_function")],
               "predicates": [pred("p0", "involved in", "n0", "n1"), pred("p1", "enables", "n0", "n2")],
               "logic": {"operator": "AND", "children": [{"operator": "OR", "predicates": ["p0", "p1"]}]}}
    assert is_slow_query(request)


# --- which backends accept logic ----------------------------------------------

def test_only_cypher_supports_logic():
    from app.services.cypher_generator import CypherQueryGenerator
    from app.services.metta_generator import MeTTa_Query_Generator
    from app.services.mork_generator import MorkQueryGenerator
    assert CypherQueryGenerator.supports_logic is True
    assert MeTTa_Query_Generator.supports_logic is False
    assert getattr(MorkQueryGenerator, "supports_logic", False) is False


def test_an_id_on_a_not_or_or_alternative_does_not_skip_the_check():
    not_request = {"nodes": [node("n0", "gene", {"chr": "chr1"}), node("n1", "biological_process", id_="GO_0008150")],
                   "predicates": [pred("p0", "involved in", "n0", "n1")],
                   "logic": {"operator": "AND", "children": [{"operator": "NOT", "predicates": ["p0"]}]}}
    assert needs_cost_check(not_request) is True
    or_request = {"nodes": [node("n0", "gene", {"chr": "chr1"}), node("n1", "biological_process", id_="GO_0008150"),
                            node("n2", "molecular_function")],
                  "predicates": [pred("p0", "involved in", "n0", "n1"), pred("p1", "enables", "n0", "n2")],
                  "logic": {"operator": "AND", "children": [{"operator": "OR", "predicates": ["p0", "p1"]}]}}
    assert needs_cost_check(or_request) is True
    plain = {"nodes": [node("n0", "gene"), node("n1", "biological_process", id_="GO_0008150")],
             "predicates": [pred("p0", "involved in", "n0", "n1")]}
    assert needs_cost_check(plain) is False                  # the id fixes every returned row

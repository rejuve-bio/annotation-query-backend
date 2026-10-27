"""Optional chat thread_id on annotations: validation, storage, reuse per thread and reads.

Run: python -m pytest tests/unit/test_thread_id.py --noconftest
"""
import datetime
import json
import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException

from app.api.api_v1.endpoints import query as endpoint
from app.constants import TaskStatus
from app.core.config import settings
from app.lib.query_cost import RUN
from app.lib.thread_id import parse_thread_id

THREAD_A = "8d2f0c1e-4b7a-4c39-9e21-5f6a7b8c9d0e"
THREAD_B = str(uuid.uuid4())
REQUESTS = {"nodes": [{"node_id": "n1", "id": "", "type": "gene", "properties": {"gene_name": "APOE"}}],
            "predicates": []}


# --- validation ---------------------------------------------------------------

def test_missing_thread_id_is_none():
    assert parse_thread_id(None) is None


def test_uuid4_is_accepted_and_lowercased():
    assert parse_thread_id(THREAD_A) == THREAD_A
    assert parse_thread_id(THREAD_A.upper()) == THREAD_A


@pytest.mark.parametrize("value", ["", "not-a-uuid", str(uuid.uuid1()), THREAD_A.replace("-", ""),
                                   "{%s}" % THREAD_A, 42, ["x"]])
def test_anything_but_a_uuid4_is_rejected(value):
    with pytest.raises(ValueError):
        parse_thread_id(value)


# --- POST /query ----------------------------------------------------------------

class FakeAnnotations:
    """AnnotationStorageService stand-in holding annotations as SimpleNamespaces."""

    def __init__(self, *docs):
        self.docs = list(docs)

    def save(self, annotation):
        doc = SimpleNamespace(id=f"a{len(self.docs) + 1}", user_id=annotation["current_user_id"],
                              thread_id=annotation.get("thread_id"), answer=annotation.get("answer"),
                              status=annotation.get("status"),
                              query_fingerprint=annotation.get("query_fingerprint"), saved=annotation)
        self.docs.append(doc)
        return doc.id

    def get_by_fingerprint(self, fingerprint):
        return next((d for d in self.docs if d.query_fingerprint == fingerprint
                     and d.status == TaskStatus.COMPLETE.value), None)

    def get_user_annotation_in_thread(self, fingerprint, user_id, thread_id):
        return next((d for d in self.docs if d.query_fingerprint == fingerprint and d.user_id == user_id
                     and d.thread_id == thread_id and d.status == TaskStatus.COMPLETE.value), None)


class FakeRedis:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def lock(self, *args, **kwargs):
        return nullcontext()

    def get(self, key):
        return self.data.get(key)

    def setex(self, key, ttl, value):
        self.data[key] = value


class FakeBackend:
    supports_logic = True

    def parse_id(self, requests):
        return requests

    def query_Generator(self, requests, node_map, limit, node_only):
        return ["MATCH (n) RETURN n", "COUNT", "LABELS"]


@pytest.fixture
def run_query(monkeypatch):
    """Call POST /query with fakes; returns (response, storage, queued handle_client_request calls)."""

    def run(body, storage, user_id="u1", source=None):
        queued = []
        monkeypatch.setattr(settings, "DEDUP_ENABLED", True)
        monkeypatch.setattr(endpoint, "AnnotationStorageService", storage)
        monkeypatch.setattr(endpoint, "UserStorageService", SimpleNamespace(get=lambda _id: None))
        monkeypatch.setattr(endpoint, "get_db_instance", lambda species: FakeBackend())
        monkeypatch.setattr(endpoint, "validate_request", lambda requests, schema, source: {"n1": {}})
        monkeypatch.setattr(endpoint, "assess_query_cost", lambda *a: SimpleNamespace(action=RUN))
        monkeypatch.setattr(endpoint, "handle_client_request",
                            lambda *a, **kw: queued.append(kw) or {"annotation_id": "queued"})
        response = endpoint.process_query(
            data=body, limit=None, properties=None, source=source, current_user_id=user_id,
            db_instance=None, llm=None, redis_client=FakeRedis(), schema_manager=SimpleNamespace(schema={}))
        return response, storage, queued

    return run


def fingerprint_of(run_query):
    """The fingerprint POST /query computes for REQUESTS (taken from a first, queued run)."""
    storage = FakeAnnotations()
    storage.get_by_fingerprint = lambda fp: storage.seen.append(fp)
    storage.seen = []
    run_query({"requests": json.loads(json.dumps(REQUESTS))}, storage)
    return storage.seen[0]


def body(thread_id=None):
    data = {"requests": json.loads(json.dumps(REQUESTS))}
    if thread_id is not None:
        data["thread_id"] = thread_id
    return data


def completed(fingerprint, user_id, thread_id, id_="orig"):
    return SimpleNamespace(id=id_, user_id=user_id, thread_id=thread_id, answer=None,
                           status=TaskStatus.COMPLETE.value, query_fingerprint=fingerprint,
                           query="MATCH (n) RETURN n", title="APOE", summary="s", node_count=1, edge_count=0,
                           node_types=["gene"], node_count_by_label=[], edge_count_by_label=[],
                           question=None, path_url="/graph.json", files=None)


def test_invalid_thread_id_is_a_400(run_query):
    with pytest.raises(HTTPException) as e:
        run_query(body("nope"), FakeAnnotations())
    assert e.value.status_code == 400
    assert "thread_id" in e.value.detail


def test_new_query_passes_thread_id_to_the_queued_annotation(run_query):
    _, _, queued = run_query(body(THREAD_A), FakeAnnotations())
    assert queued[0]["thread_id"] == THREAD_A


def test_query_without_thread_id_queues_none(run_query):
    _, _, queued = run_query(body(), FakeAnnotations())
    assert queued[0]["thread_id"] is None


def test_same_query_same_thread_returns_the_users_annotation(run_query):
    fp = fingerprint_of(run_query)
    storage = FakeAnnotations(completed(fp, "u1", THREAD_A))
    response, storage, _ = run_query(body(THREAD_A), storage)
    assert response == {"annotation_id": "orig"}
    assert len(storage.docs) == 1


def test_same_query_other_thread_gets_its_own_annotation_over_the_same_results(run_query):
    fp = fingerprint_of(run_query)
    storage = FakeAnnotations(completed(fp, "u1", THREAD_A))
    response, storage, queued = run_query(body(THREAD_B), storage)
    new = storage.docs[-1]
    assert response == {"annotation_id": new.id} and new.id != "orig"
    assert new.thread_id == THREAD_B and new.saved["path_url"] == "/graph.json"
    assert queued == []     # reused, not recomputed


def test_same_query_in_a_thread_then_outside_any_thread_gets_its_own_annotation(run_query):
    fp = fingerprint_of(run_query)
    storage = FakeAnnotations(completed(fp, "u1", THREAD_A))
    response, storage, _ = run_query(body(), storage)
    assert response["annotation_id"] != "orig"
    assert storage.docs[-1].thread_id is None


def test_without_threads_a_repeat_still_returns_the_users_annotation(run_query):
    fp = fingerprint_of(run_query)
    storage = FakeAnnotations(completed(fp, "u1", None))
    response, storage, _ = run_query(body(), storage)
    assert response == {"annotation_id": "orig"}


def test_other_users_result_is_reused_under_the_callers_thread(run_query):
    fp = fingerprint_of(run_query)
    storage = FakeAnnotations(completed(fp, "u2", THREAD_A))
    response, storage, _ = run_query(body(THREAD_B), storage, user_id="u1")
    new = storage.docs[-1]
    assert response == {"annotation_id": new.id}
    assert (new.user_id, new.thread_id) == ("u1", THREAD_B)


def test_question_on_a_reused_result_stores_the_thread_id(run_query, monkeypatch):
    fp = fingerprint_of(run_query)
    storage = FakeAnnotations(completed(fp, "u1", THREAD_A))
    data = body(THREAD_B)
    data["requests"]["question"] = "what is APOE?"
    monkeypatch.setattr(endpoint, "AnnotationStorageService", storage)
    response = endpoint.process_query(
        data=data, limit=None, properties=None, source=None, current_user_id="u1", db_instance=None,
        llm=SimpleNamespace(generate_summary=lambda *a: "an answer"), redis_client=FakeRedis(),
        schema_manager=SimpleNamespace(schema={}))
    assert storage.docs[-1].thread_id == THREAD_B
    assert response == {"annotation_id": storage.docs[-1].id}


# --- reads ----------------------------------------------------------------------

def history_row(**extra):
    now = datetime.datetime(2026, 1, 1)
    return {"_id": "a1", "request": REQUESTS, "title": "APOE", "node_count": 1, "edge_count": 0,
            "node_types": ["gene"], "status": "COMPLETE", "species": "human", "data_source": "all",
            "created_at": now, "updated_at": now, **extra}


def test_history_returns_thread_id_or_null(monkeypatch):
    monkeypatch.setattr(endpoint.AnnotationStorageService, "get_all",
                        lambda user_id, page: [history_row(thread_id=THREAD_A), history_row()])
    rows = endpoint.process_user_history(page_number=1, current_user_id="u1")
    assert [r["thread_id"] for r in rows] == [THREAD_A, None]


@pytest.mark.parametrize("thread_id", [THREAD_A, None])
def test_annotation_detail_returns_thread_id_or_null(monkeypatch, thread_id):
    doc = SimpleNamespace(
        id="a1", user_id="u1", participant_user_ids=[], request=REQUESTS, query="q", title="APOE",
        summary=None, question=None, answer=None, node_count=None, edge_count=None,
        node_count_by_label=None, edge_count_by_label=None, status="COMPLETE", path_url=None,
        species="human", data_source="all", files=None, retrieval_duration=None,
        processing_duration=None, summary_duration=None, total_duration=None, graph_error_message=None,
        count_error_message=None, label_count_error_message=None, thread_id=thread_id)
    monkeypatch.setattr(settings, "JWT_SECRET", "test-secret")
    monkeypatch.setattr(endpoint.AnnotationStorageService, "get_by_id", lambda _id: doc)
    monkeypatch.setattr(endpoint.AnnotationStorageService, "get_user_annotation", lambda _id, user: doc)
    monkeypatch.setattr(endpoint.SharedAnnotationStorageService, "get", lambda query: None)
    redis = FakeRedis({"a1": json.dumps({"graph": {"nodes": [], "edges": []}})})
    token = jwt.encode({"user_id": "u1"}, "test-secret", algorithm="HS256")
    response = endpoint.get_annotation_by_id(id="a1", token=None, limit=None, properties=None, source=None,
                                             auth_header=token, redis_client=redis)
    assert response["thread_id"] == thread_id


# --- storage ----------------------------------------------------------------------

def test_save_keeps_thread_id_and_the_reused_graph(monkeypatch):
    """Copies made by dedup must keep path_url/files, or they lose the graph when Redis expires."""
    from app.persistence import annotation_storage_service as storage_module

    saved = {}

    class FakeAnnotation:
        def __init__(self, **kwargs):
            saved.update(kwargs)

        def save(self):
            return "new-id"

    monkeypatch.setattr(storage_module, "Annotation", FakeAnnotation)
    annotation_id = storage_module.AnnotationStorageService.save({
        "current_user_id": "u1", "request": REQUESTS, "query": "q", "title": "APOE",
        "node_types": ["gene"], "status": TaskStatus.COMPLETE.value, "thread_id": THREAD_A,
        "path_url": "/app/public/graph/orig.json", "files": [{"name": "nodes.tsv"}]})
    assert annotation_id == "new-id"
    assert (saved["thread_id"], saved["path_url"], saved["files"]) == (
        THREAD_A, "/app/public/graph/orig.json", [{"name": "nodes.tsv"}])


def test_save_without_graph_fields_stores_none(monkeypatch):
    from app.persistence import annotation_storage_service as storage_module

    saved = {}
    monkeypatch.setattr(storage_module, "Annotation",
                        type("FakeAnnotation", (), {"__init__": lambda self, **kw: saved.update(kw),
                                                    "save": lambda self: "id"}))
    storage_module.AnnotationStorageService.save({
        "current_user_id": "u1", "request": REQUESTS, "query": "q", "title": "APOE", "node_types": ["gene"]})
    assert saved["thread_id"] is None and saved["path_url"] is None and saved["files"] is None

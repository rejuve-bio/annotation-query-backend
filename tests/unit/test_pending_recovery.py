"""GET /annotation/{id} recovery of PENDING annotations whose graph is already on disk."""
import json
from types import SimpleNamespace

import jwt
import pytest

from app.api.api_v1.endpoints import query as endpoint
from app.constants import TaskStatus
from app.core.config import settings


class FakeState:
    def __init__(self, graph_done=None):
        self.hash = {} if graph_done is None else {"graph_done": graph_done}

    def hget(self, key, field):
        return self.hash.get(field)


class NoCache:
    def get(self, key):
        return None


@pytest.fixture
def get_pending(monkeypatch, tmp_path):
    """GET a PENDING annotation (counts set, graph file on disk, Redis cache expired)."""

    def run(graph_done):
        graph_file = tmp_path / "a1.json"
        graph_file.write_text(json.dumps({"nodes": [{"id": "old"}], "edges": []}))
        doc = SimpleNamespace(
            id="a1", user_id="u1", participant_user_ids=[], request={"nodes": [], "predicates": []},
            query="q", title="t", summary=None, question=None, answer=None, node_count=1, edge_count=0,
            node_count_by_label=[], edge_count_by_label=[], status=TaskStatus.PENDING.value,
            path_url=str(graph_file), species="human", data_source="all", files=None,
            retrieval_duration=None, processing_duration=None, summary_duration=None, total_duration=None,
            graph_error_message=None, count_error_message=None, label_count_error_message=None, thread_id=None)
        completed = []
        monkeypatch.setattr(settings, "JWT_SECRET", "test-secret")
        monkeypatch.setattr(endpoint, "redis_state", FakeState(graph_done))
        monkeypatch.setattr(endpoint.AnnotationStorageService, "get_by_id", lambda _id: doc)
        monkeypatch.setattr(endpoint.AnnotationStorageService, "get_user_annotation", lambda _id, user: doc)
        monkeypatch.setattr(endpoint.AnnotationStorageService, "complete_if_pending",
                            lambda _id, data: completed.append(data))
        monkeypatch.setattr(endpoint.SharedAnnotationStorageService, "get", lambda query: None)
        token = jwt.encode({"user_id": "u1"}, "test-secret", algorithm="HS256")
        response = endpoint.get_annotation_by_id(id="a1", token=None, limit=None, properties=None, source=None,
                                                 auth_header=token, redis_client=NoCache())
        return response, completed

    return run


@pytest.mark.parametrize("graph_done", [b"0", "0", 0])
def test_rerun_still_rebuilding_the_graph_stays_pending(get_pending, graph_done):
    response, completed = get_pending(graph_done)
    assert response["status"] == TaskStatus.PENDING.value
    assert "nodes" not in response and completed == []


@pytest.mark.parametrize("graph_done", [b"1", None])
def test_graph_written_but_summary_never_ran_is_recovered(get_pending, graph_done):
    response, completed = get_pending(graph_done)
    assert response["status"] == TaskStatus.COMPLETE.value
    assert response["nodes"] == [{"id": "old"}] and len(completed) == 1


def test_state_lookup_failure_falls_back_to_recovery(get_pending, monkeypatch):
    def broken(key, field):
        raise ConnectionError("redis down")
    response, _ = get_pending(None)
    monkeypatch.setattr(endpoint.redis_state, "hget", broken)
    assert endpoint._graph_rebuild_in_progress("a1") is False

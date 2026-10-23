from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

from app.api import deps
from app.api.api_v1.endpoints import query as query_endpoint
from tests.lib.header_generator import generate_headers


def test_hypothesis_query_returns_graph_nodes(client, monkeypatch):
    """The current FastAPI route returns graph nodes for hypothesis queries."""
    graph_nodes = [{"data": {"id": "ensg00000101349", "type": "gene"}}]
    db_instance = Mock()
    db_instance.parse_id.side_effect = lambda request: request
    db_instance.query_Generator.return_value = (
        "MATCH (n) RETURN n",
        "MATCH (n) RETURN count(n)",
        "MATCH (n) RETURN labels(n)",
    )
    db_instance.run_query.return_value = [object()]
    db_instance.parse_and_serialize.return_value = {
        "nodes": graph_nodes,
        "edges": [],
    }
    redis_client = SimpleNamespace(lock=lambda *args, **kwargs: nullcontext())

    monkeypatch.setitem(client.app.dependency_overrides, deps.get_db_instance, lambda: db_instance)
    monkeypatch.setitem(client.app.dependency_overrides, deps.get_redis_client, lambda: redis_client)
    monkeypatch.setitem(client.app.dependency_overrides, deps.get_llm_handler, lambda: Mock())
    monkeypatch.setattr(query_endpoint, "get_db_instance", lambda species: db_instance)
    monkeypatch.setattr(query_endpoint.UserStorageService, "get", lambda user_id: None)
    monkeypatch.setattr(
        query_endpoint.AnnotationStorageService,
        "get_by_fingerprint",
        lambda fingerprint: None,
    )

    response = client.post(
        "/query?source=hypothesis",
        headers=generate_headers(),
        json={
            "requests": {
                "nodes": [
                    {
                        "node_id": "n1",
                        "id": "ENSG00000101349",
                        "type": "gene",
                        "properties": {},
                    }
                ],
                "predicates": [],
            }
        },
    )

    assert response.status_code == 200
    assert response.json() == {"nodes": graph_nodes}
    db_instance.run_query.assert_called_once_with("MATCH (n) RETURN n")

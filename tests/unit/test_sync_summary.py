"""POST /query?source=ai-assistant summarizes with the counts the summarizer needs."""
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.api.api_v1.endpoints import query as endpoint
from app.lib.query_cost import RUN
from app.services.llm_handler import LLMHandler

REQUESTS = {"nodes": [{"node_id": "n1", "id": "", "type": "gene", "properties": {"gene_name": "APOE"}}],
            "predicates": []}
COUNTS = {"node_count": 1, "edge_count": 0,
          "node_count_by_label": [{"label": "gene", "count": 1}], "edge_count_by_label": []}


class FakeModel:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return f"llm reply {len(self.prompts)}"


class Backend:
    supports_logic = True

    def parse_id(self, requests):
        return requests

    def query_Generator(self, requests, node_map, limit, node_only):
        return ["MATCH (n) RETURN n", "COUNT", "LABELS"]

    def run_query(self, query, species=None):
        return [{}]

    def parse_and_serialize(self, result, schema, components, result_type):
        if result_type == "graph":
            return {"nodes": [{"data": {"id": "gene x", "type": "gene", "gene_name": "APOE"}}], "edges": []}
        return dict(COUNTS)


class Redis:
    def lock(self, *args, **kwargs):
        return nullcontext()

    def get(self, key):
        return None

    def setex(self, key, ttl, value):
        pass


@pytest.fixture
def ask(monkeypatch):
    """Run a synchronous ai-assistant query with the real summarizer over a fake model."""

    def run(question):
        saved = []
        monkeypatch.setattr(endpoint, "AnnotationStorageService", SimpleNamespace(
            get_by_fingerprint=lambda fp: None, save=lambda a: saved.append(a) or "a1"))
        monkeypatch.setattr(endpoint, "UserStorageService", SimpleNamespace(get=lambda _id: None))
        monkeypatch.setattr(endpoint, "get_db_instance", lambda species: Backend())
        monkeypatch.setattr(endpoint, "validate_request", lambda requests, schema, source: {"n1": {}})
        monkeypatch.setattr(endpoint, "assess_query_cost", lambda *a: SimpleNamespace(action=RUN))
        llm = LLMHandler.__new__(LLMHandler)
        llm.model = FakeModel()
        llm.generate_title = lambda *a: "APOE"
        requests = json.loads(json.dumps(REQUESTS))
        if question:
            requests["question"] = question
        response = endpoint.process_query(
            data={"requests": requests}, limit=None, properties=None, source="ai-assistant",
            current_user_id="u1", db_instance=None, llm=llm, redis_client=Redis(),
            schema_manager=SimpleNamespace(schema={}, full_schema_representation={}))
        return response, saved[0], llm.model.prompts

    return run


def test_summary_is_generated_not_the_too_big_fallback(ask):
    response, saved, prompts = ask(None)
    assert saved["summary"] == "llm reply 1"
    assert prompts


def test_question_gets_an_answer_using_the_label_counts(ask):
    response, saved, prompts = ask("what is APOE?")
    assert response["answer"] == saved["answer"] == "llm reply 2"
    assert saved["summary"] == "llm reply 1"
    assert "'label': 'gene', 'count': 1" in prompts[-1]

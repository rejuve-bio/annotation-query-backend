"""Neighbourhood job lifecycle: Redis state, result saving, deletes and socket rooms."""

import asyncio
from types import SimpleNamespace

import pytest

from app.api.api_v1.endpoints import neighbourhood as endpoint
from app.constants import TaskStatus
from app.events import socket_event
from app.workers import neighbourhood_task as task

RESULT = {"seed": {"found": True}, "hops": [], "node_count": 1, "edge_count": 0, "truncated": False}


class FakeRedis:
    def __init__(self):
        self.data, self.ttl = {}, {}

    def hset(self, key, field, value):
        self.data.setdefault(key, {})[field] = value

    def hget(self, key, field):
        return self.data.get(key, {}).get(field)

    def expire(self, key, seconds):
        self.ttl[key] = seconds


class FakeStorage:
    """NeighbourhoodStorageService stand-in; `deleted_after_update` simulates a DELETE racing completion."""

    def __init__(self, job, deleted_after_update=False, write_error=None):
        self.job, self.updates, self.cleaned = job, [], []
        self.deleted_after_update, self.write_error = deleted_after_update, write_error

    def get_by_id(self, job_id):
        return self.job

    def update(self, job_id, data):
        self.updates.append(data)
        if self.deleted_after_update and data.get("status") == TaskStatus.COMPLETE.value:
            self.job = None

    def append_hop(self, job_id, summary):
        pass

    def write_result(self, job_id, result):
        if self.write_error:
            raise self.write_error
        return f"/results/{job_id}.json"

    def delete_result_if_unused(self, path):
        self.cleaned.append(path)


@pytest.fixture
def run_job(monkeypatch):
    def run(storage):
        import datetime
        redis, events = FakeRedis(), []
        monkeypatch.setattr(task, "redis_state", redis)
        monkeypatch.setattr(task, "NeighbourhoodStorageService", storage)
        monkeypatch.setattr(task, "_publish", lambda job_id, status, **extra: events.append(status))
        db = SimpleNamespace(expand_neighbourhood=lambda *a, **k: RESULT)
        monkeypatch.setattr(task, "get_db_instance", lambda species: db)
        task.init_job_state("j1")
        task.neighbourhood_task.run("j1")
        return redis, events
    return run


def pending_job():
    import datetime
    return SimpleNamespace(status=TaskStatus.PENDING.value, created_at=datetime.datetime.now(),
                           species="human", request={})


def test_job_state_expires_while_queued_and_soon_after_completion(run_job):
    storage = FakeStorage(pending_job())
    redis, events = run_job(storage)
    assert events == [TaskStatus.COMPLETE.value]
    assert storage.updates[-1]["status"] == TaskStatus.COMPLETE.value
    assert redis.ttl["annotation:j1"] == task.FINISHED_STATE_TTL_S


def test_init_and_cancel_keep_state_long_enough_for_a_queued_job(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(task, "redis_state", redis)
    task.init_job_state("j2")
    assert redis.ttl["annotation:j2"] == task.JOB_STATE_TTL_S > task.TASK_STALE_SECS
    task.cancel_job("j2")
    assert redis.hget("annotation:j2", "status") == TaskStatus.CANCELLED.value
    assert redis.ttl["annotation:j2"] == task.JOB_STATE_TTL_S


def test_a_result_that_cannot_be_saved_fails_the_job(run_job):
    storage = FakeStorage(pending_job(), write_error=OSError("disk full"))
    redis, events = run_job(storage)
    assert events == [TaskStatus.FAILED.value]
    assert storage.updates[-1] == {"status": TaskStatus.FAILED.value, "error": "Could not save the neighbourhood result"}
    assert redis.ttl["annotation:j1"] == task.FINISHED_STATE_TTL_S


def test_a_job_deleted_while_saving_leaves_no_file_and_no_completion(run_job):
    storage = FakeStorage(pending_job(), deleted_after_update=True)
    _, events = run_job(storage)
    assert events == []
    assert storage.cleaned == ["/results/j1.json"]


def join(monkeypatch, room, annotation=None, job=None, user="u1"):
    entered = []
    monkeypatch.setitem(socket_event._authenticated_users, "sid", user)
    monkeypatch.setattr(socket_event.AnnotationStorageService, "get_by_id", lambda _id: annotation)
    monkeypatch.setattr(socket_event.NeighbourhoodStorageService, "get_by_id", lambda _id: job)
    monkeypatch.setattr(socket_event.sio, "enter_room", lambda sid, r: _async(entered.append(r)))
    monkeypatch.setattr(socket_event.sio, "emit", lambda *a, **k: _async(None))
    monkeypatch.setattr(socket_event, "get_annotation_redis", lambda r: None)
    asyncio.run(socket_event.on_join("sid", {"room": room}))
    return entered


async def _noop():
    return None


def _async(_):
    return _noop()


def test_socket_rooms_need_an_existing_room_owned_by_the_user(monkeypatch):
    assert join(monkeypatch, "j1", job=SimpleNamespace(user_id="u1")) == ["j1"]
    assert join(monkeypatch, "j1", job=SimpleNamespace(user_id="u2")) == []
    assert join(monkeypatch, "gone") == []     # deleted job or unknown id


def test_reused_result_deleted_meanwhile_runs_the_job_instead(monkeypatch, tmp_path):
    queued, updates = [], []
    done = SimpleNamespace(result_path=str(tmp_path / "gone.json"), seed={}, hops=[],
                           node_count=1, edge_count=0, truncated=False)
    storage = SimpleNamespace(
        get_by_fingerprint=lambda user, fp: None, count_active=lambda user: 0,
        get_completed_by_fingerprint=lambda fp: done, save=lambda doc: "new-job",
        update=lambda job_id, data: updates.append(data))
    monkeypatch.setattr(endpoint, "NeighbourhoodStorageService", storage)
    monkeypatch.setattr(endpoint, "get_db_instance",
                        lambda species: SimpleNamespace(validate_neighbourhood_request=lambda r, s: []))
    monkeypatch.setattr(endpoint, "init_job_state", lambda job_id: None)
    monkeypatch.setattr(endpoint.neighbourhood_task, "apply_async", lambda **kw: queued.append(kw))
    body = endpoint.NeighbourhoodRequest(seed={"type": "gene", "id": "G0"})
    response = endpoint.create_neighbourhood_job(body, current_user_id="u1")
    assert response == {"job_id": "new-job", "status": TaskStatus.PENDING.value, "reused": False}
    assert updates[-1]["status"] == TaskStatus.PENDING.value and updates[-1]["result_path"] is None
    assert queued and queued[0]["args"] == ["new-job"]
    (tmp_path / "gone.json").write_text("{}")
    queued.clear()
    response = endpoint.create_neighbourhood_job(body, current_user_id="u1")
    assert response["status"] == TaskStatus.COMPLETE.value and response["reused"] is True and not queued

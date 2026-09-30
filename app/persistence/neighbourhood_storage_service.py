import datetime
import json
from pathlib import Path

from app.constants import TaskStatus, TASK_STALE_SECS
from app.models.neighbourhood_job import NeighbourhoodJob

# Shared by the API and the Celery workers (same `.:/app` mount), and outside
# the statically served app/public directory so results are only reachable
# through the ownership-checked endpoint.
RESULT_DIR = Path(__file__).resolve().parents[2] / "public" / "neighbourhood"


def _live_statuses():
    """COMPLETE jobs, or PENDING ones young enough that a worker may still run them."""
    fresh_after = datetime.datetime.now() - datetime.timedelta(seconds=TASK_STALE_SECS)
    return {"$or": [
        {"status": TaskStatus.COMPLETE.value},
        {"status": TaskStatus.PENDING.value, "created_at": {"$gt": fresh_after}},
    ]}


class NeighbourhoodStorageService():
    def __init__(self):
        pass

    @staticmethod
    def save(job):
        now = datetime.datetime.now()
        data = NeighbourhoodJob(
            user_id=job["user_id"],
            request=job["request"],
            species=job["species"],
            fingerprint=job["fingerprint"],
            status=TaskStatus.PENDING.value,
            hops=[],
            created_at=now,
            updated_at=now,
        )
        return data.save()

    @staticmethod
    def get_by_id(id):
        try:
            return NeighbourhoodJob.find_by_id(id)
        except Exception:
            # Malformed ObjectId — treat the same as "not found"
            return None

    @staticmethod
    def get_all(user_id, page_number):
        docs = NeighbourhoodJob.find({"user_id": user_id}).sort(
            '_id', -1).skip((page_number - 1) * 10).limit(10)
        return [NeighbourhoodJob.parse(doc) for doc in docs]

    @staticmethod
    def count_active(user_id):
        fresh_after = datetime.datetime.now() - datetime.timedelta(seconds=TASK_STALE_SECS)
        return len(list(NeighbourhoodJob.find({
            "user_id": user_id, "status": TaskStatus.PENDING.value,
            "created_at": {"$gt": fresh_after}})))

    @staticmethod
    def get_by_fingerprint(user_id, fingerprint):
        """The user's newest completed or still-running job for this exact request."""
        jobs = NeighbourhoodJob.find({
            "user_id": user_id,
            "fingerprint": fingerprint,
            **_live_statuses(),
        }).sort('_id', -1).limit(1)
        doc = next(iter(jobs), None)
        return NeighbourhoodJob.parse(doc) if doc is not None else None

    @staticmethod
    def get_completed_by_fingerprint(fingerprint):
        """Any user's completed job for this request — the result is not user-specific."""
        jobs = NeighbourhoodJob.find({
            "fingerprint": fingerprint,
            "status": TaskStatus.COMPLETE.value,
        }).sort('_id', -1).limit(1)
        doc = next(iter(jobs), None)
        return NeighbourhoodJob.parse(doc) if doc is not None else None

    @staticmethod
    def update(id, data):
        data = {**data, "updated_at": datetime.datetime.now()}
        NeighbourhoodJob.update({"_id": id}, {"$set": data}, many=False)

    @staticmethod
    def append_hop(id, hop_summary):
        NeighbourhoodJob.update(
            {"_id": id},
            {"$push": {"hops": hop_summary}, "$set": {"updated_at": datetime.datetime.now()}},
            many=False)

    @staticmethod
    def delete(id):
        NeighbourhoodJob.delete({"_id": id})

    @staticmethod
    def write_result(job_id, result):
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        path = RESULT_DIR / f"{job_id}.json"
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(result, f)
        tmp.replace(path)   # atomic, so readers never see a half-written file
        return str(path)

    @staticmethod
    def read_result(result_path):
        path = Path(result_path).resolve()
        path.relative_to(RESULT_DIR)    # raises ValueError if outside RESULT_DIR
        with open(path, "r") as f:
            return json.load(f)

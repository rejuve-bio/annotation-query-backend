import datetime as dt
import json
import logging

from app.api.deps import get_db_instance, get_redis_client
from app.constants import TaskStatus, TASK_STALE_SECS
from app.error import TaskCancelledException
from app.events import RedisStopEvent
from app.persistence import NeighbourhoodStorageService
from .celery_app import celery_app, redis_state

logger = logging.getLogger(__name__)

redis_client = get_redis_client()

NEIGHBOURHOOD_QUEUE = "fast"


def _publish(job_id, status, **extra):
    # The socket bridge in app.main routes events to the room named by
    # 'annotation_id', so the job id goes there too.
    event = {"annotation_id": job_id, "job_id": job_id, "type": "neighbourhood",
             "status": status, **extra}
    redis_client.publish("socket_event", json.dumps(event))


def init_job_state(job_id):
    """Redis status key read by RedisStopEvent, so a job can be cancelled mid-run."""
    redis_state.hset(f"annotation:{job_id}", "status", TaskStatus.PENDING.value)


def cancel_job(job_id):
    redis_state.hset(f"annotation:{job_id}", "status", TaskStatus.CANCELLED.value)


def _fail(job_id, message):
    NeighbourhoodStorageService.update(job_id, {"status": TaskStatus.FAILED.value, "error": message})
    _publish(job_id, TaskStatus.FAILED.value, error=message)


INDEX_QUEUE = "slow"
# Longer than a full build (~45 min), so a crashed build is retried later.
INDEX_BUILD_GUARD_S = 4 * 3600


def _index_guard_key(species):
    return f"mork_neighbourhood_index_build:{species}"


def request_index_build(species):
    """Queue a MORK neighbourhood index build once; repeated calls do nothing while one is pending."""
    if redis_state.set(_index_guard_key(species), 1, nx=True, ex=INDEX_BUILD_GUARD_S):
        build_index_task.apply_async(args=[species], queue=INDEX_QUEUE)


@celery_app.task(name="neighbourhood.build_mork_index")
def build_index_task(species):
    try:
        index = getattr(get_db_instance(species), "neighbourhood_index", None)
        if index is not None:
            index.build()
    except Exception:
        logger.exception("[neighbourhood] MORK index build for %s failed", species)
    finally:
        redis_state.delete(_index_guard_key(species))


@celery_app.task(name="neighbourhood.expand")
def neighbourhood_task(job_id):
    job = NeighbourhoodStorageService.get_by_id(job_id)
    if job is None or job.status != TaskStatus.PENDING.value:
        return   # deleted, cancelled, or already finished

    age = (dt.datetime.now() - job.created_at).total_seconds()
    if age > TASK_STALE_SECS:
        logger.warning("[neighbourhood] Dropping stale job %s (%.0fs old)", job_id, age)
        _fail(job_id, "Job expired before a worker picked it up")
        return

    def on_hop_complete(summary):
        NeighbourhoodStorageService.append_hop(job_id, summary)
        _publish(job_id, TaskStatus.PENDING.value, hop=summary)

    try:
        db_instance = get_db_instance(job.species)
        result = db_instance.expand_neighbourhood(
            job.request, species=job.species,
            stop_event=RedisStopEvent(job_id, redis_state),
            on_hop_complete=on_hop_complete,
        )
    except TaskCancelledException:
        NeighbourhoodStorageService.update(job_id, {"status": TaskStatus.CANCELLED.value})
        _publish(job_id, TaskStatus.CANCELLED.value)
        return
    except Exception:
        logger.exception("[neighbourhood] Job %s failed", job_id)
        _fail(job_id, "Neighbourhood expansion failed")
        return

    if NeighbourhoodStorageService.get_by_id(job_id) is None:
        return   # deleted while running — don't leave an orphaned result file
    result_path = NeighbourhoodStorageService.write_result(job_id, result)
    NeighbourhoodStorageService.update(job_id, {
        "status": TaskStatus.COMPLETE.value,
        "result_path": result_path,
        "seed": result["seed"],
        "hops": result["hops"],
        "node_count": result["node_count"],
        "edge_count": result["edge_count"],
        "truncated": result["truncated"],
    })
    _publish(job_id, TaskStatus.COMPLETE.value,
             node_count=result["node_count"], edge_count=result["edge_count"])

import datetime
import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from meilisearch.errors import MeilisearchError, MeilisearchTimeoutError
from redis.exceptions import RedisError

from app.api.auth import require_reindex_permission
from app.api.deps import get_current_user, get_db_instance, get_meili_client, get_redis_client
from app.services.search_service import LABEL_NAME_PROPERTY, fetch_and_index, index_is_populated, search_entities

logger = logging.getLogger(__name__)
router = APIRouter()

_INDEX_LOCK = "annotation:search:index:lock"
_INDEX_RESULT = "annotation:search:index:last"
_INDEX_LEASE_SECONDS = 3600


def _release_index_lock(lock):
    try:
        lock.release()
    except RedisError:
        logger.exception("Could not release the search indexing lock")


def _run_indexing(db_instance, meili_client, redis_client, lock):
    release_lease = True
    try:
        result = fetch_and_index(db_instance, meili_client, renew_lease=lock.reacquire)
        summary = {
            "total_indexed": result["total_indexed"],
            "error_count": len(result["errors"]),
        }
    except MeilisearchTimeoutError:
        # Meilisearch may still be processing the submitted task. Leave the
        # lease in place until it expires so a new job cannot overlap it.
        release_lease = False
        logger.exception("Timed out waiting for a search indexing task")
        summary = {"error": "Indexing task timed out"}
    except Exception:
        logger.exception("Search indexing failed")
        summary = {"error": "Indexing failed"}

    try:
        lock.reacquire()
        redis_client.set(_INDEX_RESULT, json.dumps({
            "last_run": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "last_result": summary,
        }))
    except RedisError:
        logger.exception("Could not record the search indexing result")
    finally:
        if release_lease:
            _release_index_lock(lock)


@router.post("/index", dependencies=[Depends(require_reindex_permission)])
def trigger_indexing(
    background_tasks: BackgroundTasks,
    force: bool = Query(default=False, description="Re-index even if the index has data"),
    current_user_id: str = Depends(get_current_user),
    meili_client=Depends(get_meili_client),
    db_instance=Depends(get_db_instance),
    redis_client=Depends(get_redis_client),
):
    if not hasattr(db_instance, "fetch_nodes_for_index"):
        raise HTTPException(status_code=503, detail="Indexing requires the Neo4j backend")

    lock = redis_client.lock(_INDEX_LOCK, timeout=_INDEX_LEASE_SECONDS, thread_local=False)
    try:
        if not lock.acquire(blocking=False):
            return JSONResponse(status_code=202, content={"status": "in_progress"})
    except RedisError:
        raise HTTPException(status_code=503, detail="Indexing unavailable") from None

    queued = False
    try:
        if not force and index_is_populated(meili_client):
            result = redis_client.get(_INDEX_RESULT)
            return {
                "status": "skipped",
                "last_run": json.loads(result)["last_run"] if result else None,
            }
        background_tasks.add_task(_run_indexing, db_instance, meili_client, redis_client, lock)
        queued = True
    except (MeilisearchError, RedisError):
        raise HTTPException(status_code=503, detail="Indexing unavailable") from None
    finally:
        if not queued:
            _release_index_lock(lock)

    logger.info("Search re-index requested by administrator %s", current_user_id)
    return JSONResponse(status_code=202, content={"status": "started"})


@router.get("/index/status", dependencies=[Depends(require_reindex_permission)])
def indexing_status(redis_client=Depends(get_redis_client)):
    try:
        in_progress = bool(redis_client.exists(_INDEX_LOCK))
        result = redis_client.get(_INDEX_RESULT)
    except RedisError:
        raise HTTPException(status_code=503, detail="Index status unavailable") from None
    status = json.loads(result) if result else {"last_run": None, "last_result": None}
    return {"in_progress": in_progress, **status}


@router.get("")
def search(
    q: str = Query(..., description="Search term (fuzzy matched against name)"),
    species: str = Query(..., description="'human' or 'fly'"),
    label: Optional[str] = Query(
        default=None,
        description="Node label to filter by e.g. 'gene', 'protein', 'pathway'",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user_id: str = Depends(get_current_user),
    meili_client=Depends(get_meili_client),
):
    """
    Search the knowledge graph index.

    Flow:
      1. Filter by species
      2. Filter by label (optional)
      3. Fuzzy search on name
    """
    if species not in ("human", "fly"):
        raise HTTPException(
            status_code=400,
            detail="species must be 'human' or 'fly'",
        )

    if label and label not in LABEL_NAME_PROPERTY:
        raise HTTPException(status_code=400, detail="Unknown search label")

    try:
        results = search_entities(
            client=meili_client,
            query=q,
            species=species,
            label=label,
            limit=limit,
            offset=offset,
        )
        return results
    except Exception as e:
        logger.error(f"Search error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "Search failed. Is Meilisearch running?",
                "timestamp": datetime.datetime.utcnow().isoformat(),
            },
        )

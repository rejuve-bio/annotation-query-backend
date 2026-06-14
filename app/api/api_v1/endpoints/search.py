import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse
import datetime

from app.api.deps import get_current_user, get_meili_client, get_db_instance
from app.services.search_service import (
    fetch_and_index,
    index_is_populated,
    search_entities,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# track background indexing state in memory
_indexing_state = {
    "in_progress": False,
    "last_run": None,
    "last_result": None,
}


def _run_indexing(neo4j_generator, meili_client):
    """Called in a background task."""
    global _indexing_state
    _indexing_state["in_progress"] = True
    try:
        result = fetch_and_index(neo4j_generator, meili_client)
        _indexing_state["last_result"] = result
        _indexing_state["last_run"] = datetime.datetime.utcnow().isoformat()
        logger.info(f"[]Indexing complete: {result['total_indexed']} docs")
    except Exception as e:
        logger.error(f"[Error] Indexing failed: {e}")
        _indexing_state["last_result"] = {"error": str(e)}
    finally:
        _indexing_state["in_progress"] = False


@router.post("/index")
def trigger_indexing(
    background_tasks: BackgroundTasks,
    force: bool = Query(
        default=False,
        description="Set to true to re-index even if index already has data",
    ),
    meili_client=Depends(get_meili_client),
    db_instance=Depends(get_db_instance),
):
    """
    Trigger Meilisearch indexing from Neo4j.

    - Skips automatically if the index is already populated (unless force=true).
    - Runs in the background so the request returns immediately.
    - Only one indexing job runs at a time.
    """
    if _indexing_state["in_progress"]:
        return JSONResponse(
            status_code=202,
            content={
                "status": "in_progress",
                "message": "Indexing is already running.",
            },
        )

    if not force and index_is_populated(meili_client):
        return JSONResponse(
            status_code=200,
            content={
                "status": "skipped",
                "message": "Index already populated. Use ?force=true to re-index.",
                "last_run": _indexing_state["last_run"],
            },
        )

    background_tasks.add_task(_run_indexing, db_instance, meili_client)

    return JSONResponse(
        status_code=202,
        content={
            "status": "started",
            "message": "Indexing started in the background.",
        },
    )


@router.get("/index/status")
def indexing_status():
    """Return the current state of the indexing job."""
    return {
        "in_progress": _indexing_state["in_progress"],
        "last_run": _indexing_state["last_run"],
        "last_result": _indexing_state["last_result"],
    }


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
                "detail": str(e),
                "timestamp": datetime.datetime.utcnow().isoformat(),
            },
        )

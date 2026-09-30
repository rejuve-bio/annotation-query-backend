import hashlib
import json
import logging
from typing import Annotated, List, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query as FQuery, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from app.api.deps import get_current_user, get_db_instance
from app.constants import (
    TaskStatus,
    NEIGHBOURHOOD_MAX_HOPS,
    NEIGHBOURHOOD_MAX_HOP_LIMIT,
    NEIGHBOURHOOD_MAX_PER_NODE_LIMIT,
    NEIGHBOURHOOD_MAX_ACTIVE_JOBS_PER_USER,
)
from app.persistence import NeighbourhoodStorageService
from app.workers.neighbourhood_task import (
    NEIGHBOURHOOD_QUEUE, cancel_job, init_job_state, neighbourhood_task,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Node labels / relationship types are interpolated into queries by some
# backends, so they are restricted to plain identifiers up front.
TypeName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=100)]


class Seed(BaseModel):
    type: TypeName
    id: str = Field(min_length=1, max_length=256)


Scalar = Union[float, int, str]


class EdgeCondition(BaseModel):
    """A filter on an edge property, e.g. {"property": "score", "op": ">=", "value": 5}."""
    property: TypeName
    op: Literal[">=", ">", "<=", "<", "=", "!=", "in", "not_in"]
    value: Union[Scalar, List[Annotated[str, Field(max_length=200)]]]

    @model_validator(mode="after")
    def value_matches_op(self):
        if self.op in ("in", "not_in"):
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"'{self.op}' needs a non-empty list of values")
            if len(self.value) > 100:
                raise ValueError(f"'{self.op}' accepts at most 100 values")
        elif isinstance(self.value, list):
            raise ValueError(f"'{self.op}' needs a single value, not a list")
        elif self.op in (">=", ">", "<=", "<") and not isinstance(self.value, (int, float)):
            raise ValueError(f"'{self.op}' needs a numeric value")
        return self


class HopFilter(BaseModel):
    edge_types: List[TypeName] = Field(default_factory=list, max_length=50)
    direction: Literal["out", "in", "both"] = "both"
    node_types: List[TypeName] = Field(default_factory=list, max_length=50)
    limit: int = Field(500, ge=1, le=NEIGHBOURHOOD_MAX_HOP_LIMIT)
    # Edge-property conditions, all of which must hold.
    where: List[EdgeCondition] = Field(default_factory=list, max_length=10)
    # Numeric edge property to rank by, so a truncated hop keeps the top
    # edges instead of an arbitrary subset.
    order_by: Optional[TypeName] = None
    order: Literal["desc", "asc"] = "desc"


class NeighbourhoodRequest(BaseModel):
    species: Literal["human", "fly"] = "human"
    seed: Seed
    max_hops: int = Field(1, ge=1, le=NEIGHBOURHOOD_MAX_HOPS)
    # hops[i] filters hop i+1; the last entry repeats for any remaining hops.
    hops: List[HopFilter] = Field(default_factory=lambda: [HopFilter()],
                                  min_length=1, max_length=NEIGHBOURHOOD_MAX_HOPS)
    per_node_limit: int = Field(50, ge=1, le=NEIGHBOURHOOD_MAX_PER_NODE_LIMIT)
    properties: bool = True


def _fingerprint(request: dict) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


def _job_summary(job):
    return {
        "job_id": str(job.id),
        "status": job.status,
        "species": job.species,
        "request": job.request,
        "seed": job.seed,
        "hops": job.hops or [],
        "node_count": job.node_count,
        "edge_count": job.edge_count,
        "truncated": job.truncated,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _get_owned_job(job_id, current_user_id):
    job = NeighbourhoodStorageService.get_by_id(job_id)
    # 404 rather than 403 for someone else's job, so ids cannot be probed.
    if job is None or str(job.user_id) != str(current_user_id):
        raise HTTPException(status_code=404, detail="Neighbourhood job not found")
    return job


@router.post("/neighbourhood", status_code=status.HTTP_202_ACCEPTED)
def create_neighbourhood_job(
    body: NeighbourhoodRequest,
    current_user_id: str = Depends(get_current_user),
):
    request = body.model_dump(exclude={"species"})
    species = body.species
    fingerprint = _fingerprint({"species": species, **request})

    # Same user re-submitting the same request (refresh, double click):
    # hand back the job they already have instead of queueing another.
    existing = NeighbourhoodStorageService.get_by_fingerprint(current_user_id, fingerprint)
    if existing is not None:
        return {"job_id": str(existing.id), "status": existing.status, "reused": True}

    try:
        errors = get_db_instance(species).validate_neighbourhood_request(request, species)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception:
        logger.exception("[neighbourhood] Could not validate request against %s graph", species)
        raise HTTPException(status_code=503, detail="Graph database unavailable")
    if errors:
        raise HTTPException(status_code=400, detail=errors)

    if NeighbourhoodStorageService.count_active(current_user_id) >= NEIGHBOURHOOD_MAX_ACTIVE_JOBS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"At most {NEIGHBOURHOOD_MAX_ACTIVE_JOBS_PER_USER} neighbourhood jobs can run at once",
        )

    # Another user already ran this exact request — the graph is not
    # user-specific, so reuse their result without touching the database.
    done = NeighbourhoodStorageService.get_completed_by_fingerprint(fingerprint)
    job_id = str(NeighbourhoodStorageService.save({
        "user_id": str(current_user_id), "request": request,
        "species": species, "fingerprint": fingerprint,
    }))
    if done is not None and done.result_path:
        NeighbourhoodStorageService.update(job_id, {
            "status": TaskStatus.COMPLETE.value, "result_path": done.result_path,
            "seed": done.seed, "hops": done.hops, "node_count": done.node_count,
            "edge_count": done.edge_count, "truncated": done.truncated,
        })
        return {"job_id": job_id, "status": TaskStatus.COMPLETE.value, "reused": True}

    try:
        init_job_state(job_id)
        neighbourhood_task.apply_async(args=[job_id], queue=NEIGHBOURHOOD_QUEUE)
    except Exception:
        # Never leave a PENDING job that no worker will run — it would also
        # count against the user's active-job cap forever.
        logger.exception("[neighbourhood] Could not queue job %s", job_id)
        NeighbourhoodStorageService.update(job_id, {
            "status": TaskStatus.FAILED.value, "error": "Could not queue job"})
        raise HTTPException(status_code=503, detail="Job queue unavailable")
    return {"job_id": job_id, "status": TaskStatus.PENDING.value, "reused": False}


@router.get("/neighbourhood")
def list_neighbourhood_jobs(
    page_number: int = FQuery(1, ge=1),
    current_user_id: str = Depends(get_current_user),
):
    jobs = NeighbourhoodStorageService.get_all(str(current_user_id), page_number)
    return {"jobs": [_job_summary(job) for job in jobs], "page_number": page_number}


@router.get("/neighbourhood/{job_id}")
def get_neighbourhood_job(
    job_id: str,
    current_user_id: str = Depends(get_current_user),
):
    job = _get_owned_job(job_id, current_user_id)
    response = _job_summary(job)
    if job.status == TaskStatus.COMPLETE.value and job.result_path:
        try:
            response.update(NeighbourhoodStorageService.read_result(job.result_path))
        except (OSError, ValueError):
            logger.exception("[neighbourhood] Result file missing for job %s", job_id)
            return JSONResponse(status_code=500, content={
                "status": "error", "message": "Result for this job is no longer available"})
    return response


@router.delete("/neighbourhood/{job_id}")
def delete_neighbourhood_job(
    job_id: str,
    current_user_id: str = Depends(get_current_user),
):
    job = _get_owned_job(job_id, current_user_id)
    if job.status == TaskStatus.PENDING.value:
        cancel_job(job_id)   # a running task stops at its next check
    NeighbourhoodStorageService.delete(job_id)
    return {"job_id": job_id, "deleted": True}

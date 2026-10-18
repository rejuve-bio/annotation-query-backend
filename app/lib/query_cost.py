"""
Cost check before a query runs.

Neo4j can estimate how many rows a query will produce without running it
(EXPLAIN). Queries estimated above a hard limit are refused, those above a
soft limit go to the slow queue, so a structurally huge query (e.g. millions
of SNPs joined to genes) does not reach the database through the fast path.

The estimate is coarse: Neo4j cannot see how selective a regex property
filter is, so "gene_name = TP53" and "gene_type = protein_coding" get the
same estimate (~3.5M for gene -> process & tissue on the human graph). The
limits therefore sit well above that floor and mainly catch big node types
and dense relationships. They are settings, so they can be tuned without a
release.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

RUN, SLOW, REFUSE = "run", "slow", "refuse"


@dataclass
class CostDecision:
    action: str                      # RUN, SLOW or REFUSE
    estimated_rows: Optional[int] = None


def needs_cost_check(request):
    """Only multi-node requests can blow up; a node fixed by one id keeps the query small."""
    if not request.get("predicates") and not request.get("logic"):
        return False
    for node in request.get("nodes", []):
        node_id = node.get("id")
        if isinstance(node_id, str) and node_id and "," not in node_id:
            return False
    return True


def assess_query_cost(db_instance, queries, species, request):
    """
    Decide whether the generated queries may run, should go to the slow
    queue, or must be refused. Never blocks a query because the check itself
    failed: no estimate means RUN.
    """
    if not settings.QUERY_COST_CHECK_ENABLED or not needs_cost_check(request):
        return CostDecision(RUN)
    estimate = getattr(db_instance, "estimate_rows", None)
    if estimate is None:
        return CostDecision(RUN)

    peaks = []
    for query in queries[:2]:          # result query and total-count query
        rows = estimate(query, species)
        if rows is None:
            return CostDecision(RUN)
        peaks.append(rows)
    peak = max(peaks)

    if peak > settings.QUERY_COST_HARD_LIMIT:
        return CostDecision(REFUSE, peak)
    if peak > settings.QUERY_COST_SOFT_LIMIT:
        return CostDecision(SLOW, peak)
    return CostDecision(RUN, peak)


def too_broad_message(estimated_rows):
    return (
        f"This query is too broad (about {estimated_rows:,} rows estimated). "
        "Add a filter, such as an id or a property value, or reduce the number of relationships."
    )

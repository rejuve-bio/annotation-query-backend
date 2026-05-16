"""
Intelligent failure detection and classification system for Neo4j connections.
Provides:
  - FailureClassifier  – classifies exceptions as transient or permanent
  - RetryPolicy        – configures back-off strategy
  - QueryTimeoutConfig – configures per-query-type timeouts with graceful degradation
  - ResilientDriver    – wraps a Neo4j driver with auto-reconnect + timeout logic
  - resilient_query    – decorator that applies retry logic to any query method
"""

from __future__ import annotations

import logging
import time
import functools
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

from neo4j import GraphDatabase
from neo4j.exceptions import (
    ServiceUnavailable,
    SessionExpired,
    TransientError,
    AuthError,
    ClientError,
    CypherSyntaxError,
    CypherTypeError,
    ConstraintError,
    DatabaseError,
)

from app.error import TaskCancelledException

logger = logging.getLogger(__name__)



# 1. Failure classification

class FailureKind(Enum):
    TRANSIENT = auto()   # Worth retrying (network blip, overload, lock timeout)
    PERMANENT = auto()   # Not worth retrying (bad credentials, bad query, …)
    UNKNOWN = auto()   # Cannot determine – treat conservatively as transient


# Neo4j status-code prefixes that signal a transient condition
_TRANSIENT_STATUS_PREFIXES = (
    "Neo.TransientError",
    "Neo.ClientError.Transaction.DeadlockDetected",
    "Neo.ClientError.Transaction.LockClientStopped",
)

# Neo4j status-code prefixes that signal a permanent condition
_PERMANENT_STATUS_PREFIXES = (
    "Neo.ClientError.Security",          # auth / permission failures
    "Neo.ClientError.Schema",            # constraint / index mismatches
    "Neo.ClientError.Statement.SyntaxError",
    "Neo.ClientError.Statement.TypeError",
    "Neo.ClientError.Statement.EntityNotFound",
    "Neo.ClientError.Statement.ParameterMissing",
)

# Python exception types that map directly to a kind
_TRANSIENT_EXCEPTION_TYPES = (
    ServiceUnavailable,
    SessionExpired,
    TransientError,
    ConnectionError,
    TimeoutError,
    OSError,
)

_PERMANENT_EXCEPTION_TYPES = (
    AuthError,
    CypherSyntaxError,
    CypherTypeError,
    ConstraintError,
)


class FailureClassifier:
    """Classifies a raw exception into TRANSIENT, PERMANENT, or UNKNOWN."""

    @staticmethod
    def classify(exc: Exception) -> FailureKind:
        # check status code on Neo4j errors first
        status_code: Optional[str] = getattr(exc, "code", None)
        if status_code:
            for prefix in _TRANSIENT_STATUS_PREFIXES:
                if status_code.startswith(prefix):
                    return FailureKind.TRANSIENT
            for prefix in _PERMANENT_STATUS_PREFIXES:
                if status_code.startswith(prefix):
                    return FailureKind.PERMANENT

        # fall back to Python type hierarchy 
        if isinstance(exc, _TRANSIENT_EXCEPTION_TYPES):
            return FailureKind.TRANSIENT
        if isinstance(exc, _PERMANENT_EXCEPTION_TYPES):
            return FailureKind.PERMANENT

        #  heuristic: look for network-related message keywords 
        msg = str(exc).lower()
        transient_keywords = ("connection refused", "timed out", "broken pipe",
                              "reset by peer", "unreachable", "unavailable",
                              "pool is closed", "failed to establish")
        permanent_keywords = ("unauthorized", "forbidden", "authentication",
                              "syntax error", "invalid cypher")
        if any(k in msg for k in transient_keywords):
            return FailureKind.TRANSIENT
        if any(k in msg for k in permanent_keywords):
            return FailureKind.PERMANENT

        return FailureKind.UNKNOWN


# 2. Retry policy

@dataclass
class RetryPolicy:
    """
    Controls how many times to retry and how long to wait between attempts.

    Attributes
    ----------
    max_attempts:
        Total number of *attempts* (including the first). 1 means no retry.
    base_delay_s:
        Initial sleep duration in seconds before the first retry.
    max_delay_s:
        Upper cap on any individual sleep interval.
    backoff_factor:
        Multiplier applied to the previous delay on each successive retry
        (exponential back-off when > 1).
    jitter:
        When True, adds a small random component to each delay to reduce
        thundering-herd effects under concurrent load.
    retry_on_unknown:
        When True, UNKNOWN failures are treated like TRANSIENT and retried.
    """
    max_attempts: int = 5
    base_delay_s: float = 0.5
    max_delay_s: float = 30.0
    backoff_factor: float = 2.0
    jitter: bool  = True
    retry_on_unknown: bool = True

    def should_retry(self, kind: FailureKind, attempt: int) -> bool:
        """Return True if another attempt is warranted."""
        if attempt >= self.max_attempts:
            return False
        if kind == FailureKind.PERMANENT:
            return False
        if kind == FailureKind.UNKNOWN and not self.retry_on_unknown:
            return False
        return True

    def delay_for(self, attempt: int) -> float:
        """Compute the sleep duration before *attempt* (0-indexed)."""
        import random
        delay = min(self.base_delay_s * (self.backoff_factor ** attempt),
                    self.max_delay_s)
        if self.jitter:
            delay *= (0.75 + random.random() * 0.5)   # ±25 % jitter
        return delay



# 3. Query types and timeout configuration

class QueryType(str, Enum):
    """
    Logical categories for queries.  Used to look up the appropriate timeout
    in QueryTimeoutConfig.

    Assign a query_type when calling run_with_retry(); if omitted the
    DEFAULT bucket is used which has no timeout (indefinite).
    """
    DEFAULT = "default"      # No timeout – preserves original behaviour
    GRAPH = "graph"        # Full node+edge graph fetch
    COUNT = "count"        # Aggregation / count queries
    LIST = "list"    # Gene-list vs gene-list queries
    LOAD = "load"         # Dataset loading (cypher file ingestion)
    SCHEMA = "schema"       # Schema / metadata introspection queries


class QueryTimeoutError(Exception):
    """Raised when a query exceeds its configured timeout."""
    def __init__(self, query_type: QueryType, timeout_s: float):
        self.query_type = query_type
        self.timeout_s = timeout_s
        super().__init__(
            f"Query of type '{query_type.value}' exceeded timeout of {timeout_s}s"
        )


@dataclass
class QueryTimeoutConfig:
    """
    Per-query-type timeout settings with graceful degradation support.

    All timeouts default to None (indefinite) so existing behaviour is
    completely preserved unless you explicitly set a value.

    Attributes
    ----------
    timeouts:
        Mapping of QueryType → timeout in seconds.  None means no limit.
    fallback_results:
        Mapping of QueryType → a static value returned when that query type
        times out instead of raising.  When absent for a timed-out type,
        QueryTimeoutError is raised.
    warn_threshold_s:
        If set, a WARNING is logged whenever a query takes longer than this
        many seconds, regardless of whether it ultimately times out.
    """
    timeouts: dict[QueryType, Optional[float]] = field(default_factory=dict)
    fallback_results: dict[QueryType, object] = field(default_factory=dict)
    warn_threshold_s: Optional[float] = None

    def timeout_for(self, query_type: QueryType) -> Optional[float]:
        """Return the timeout (seconds) for *query_type*, or None if indefinite."""
        return self.timeouts.get(query_type, None)

    def fallback_for(self, query_type: QueryType) -> tuple[bool, object]:
        """
        Return (has_fallback, fallback_value) for *query_type*.
        When has_fallback is False, a timeout should raise QueryTimeoutError.
        """
        if query_type in self.fallback_results:
            return True, self.fallback_results[query_type]
        return False, None


# Default instance – all timeouts are indefinite, no fallbacks.
# Import and mutate this in your app startup if you want to set limits:
#
#   from app.services.db_resilience import DEFAULT_TIMEOUT_CONFIG, QueryType
#   DEFAULT_TIMEOUT_CONFIG.timeouts[QueryType.COUNT] = 30.0
#   DEFAULT_TIMEOUT_CONFIG.timeouts[QueryType.GRAPH] = 120.0
#
DEFAULT_TIMEOUT_CONFIG = QueryTimeoutConfig()


# 4. Resilient driver

class ResilientDriver:
    """
    Thread-safe Neo4j driver wrapper with automatic reconnection,
    per-query-type timeouts, and graceful degradation.

    Drop-in replacement for ``GraphDatabase.driver(…)``.  Exposes the same
    ``.session()`` context-manager and ``.close()`` interface, plus a
    ``.run_with_retry()`` helper used by ``CypherQueryGenerator.run_query``.
    """

    def __init__(
        self,
        uri: str,
        auth: tuple[str, str],
        retry_policy: Optional[RetryPolicy] = None,
        timeout_config: Optional[QueryTimeoutConfig] = None,
        *,
        driver_kwargs: Optional[dict] = None,
    ):
        self._uri = uri
        self._auth = auth
        self._policy = retry_policy or RetryPolicy()
        self._timeout_config = timeout_config or DEFAULT_TIMEOUT_CONFIG
        self._driver_kwargs = driver_kwargs or {}

        self._lock = threading.Lock()
        self._driver = None
        self._closed = False

        self._connect()   # eager initial connection

    def _connect(self) -> None:
        """(Re-)create the underlying Neo4j driver."""
        if self._closed:
            raise RuntimeError("ResilientDriver has been permanently closed.")
        logger.info("Connecting to Neo4j at %s …", self._uri)
        self._driver = GraphDatabase.driver(
            self._uri, auth=self._auth, **self._driver_kwargs
        )
        logger.info("Connected to Neo4j at %s.", self._uri)

    def _reconnect(self) -> None:
        """Close the stale driver and open a fresh one (called inside lock)."""
        try:
            if self._driver is not None:
                self._driver.close()
        except Exception:
            pass
        self._driver = None
        self._connect()

    def _run_query_in_thread(
        self,
        query_code: str,
        stop_event,
        result_holder: list,
        exc_holder: list,
    ) -> None:
        """
        Worker target: runs the query and stores results or exception in the
        shared holders so the calling thread can inspect them after join().
        """
        try:
            results = []
            with self.session() as session:
                result = session.run(query_code)
                for record in result:
                    if stop_event is not None and stop_event.is_set():
                        raise TaskCancelledException()
                    results.append(record)
            result_holder.append(results)
        except Exception as exc:
            exc_holder.append(exc)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def session(self, **kwargs):
        """Return a Neo4j session from the current driver."""
        with self._lock:
            if self._driver is None:
                self._connect()
            return self._driver.session(**kwargs)

    def close(self) -> None:
        """Permanently close the driver – no further reconnection."""
        with self._lock:
            self._closed = True
            if self._driver is not None:
                self._driver.close()
                self._driver = None
        logger.info("ResilientDriver closed for %s.", self._uri)

    def run_with_retry(
        self,
        query_code: str,
        stop_event=None,
        query_type: QueryType = QueryType.DEFAULT,
    ):
        """
        Execute *query_code* against this driver, retrying transient failures
        with exponential back-off and automatic reconnection as needed.

        If a timeout is configured for *query_type* (via QueryTimeoutConfig),
        each attempt is run in a daemon thread and abandoned after the
        deadline.  On timeout:
          - If a fallback is configured for the query type, it is returned.
          - Otherwise QueryTimeoutError is raised (treated as transient so
            it will be retried up to max_attempts times).

        Default timeout is None (indefinite) for all query types, which
        preserves the original blocking behaviour exactly.

        Parameters
        ----------
        query_code:
            The Cypher query string.
        stop_event:
            Optional ``threading.Event``; if set, the loop is aborted and
            ``TaskCancelledException`` is raised immediately.
        query_type:
            Logical category of the query, used to look up the timeout and
            fallback in QueryTimeoutConfig.

        Returns
        -------
        list
            All records returned by the query, or the configured fallback
            value if the query timed out and a fallback is set.

        Raises
        ------
        TaskCancelledException
            When *stop_event* is set.
        QueryTimeoutError
            When the query exceeds its timeout and no fallback is configured,
            after all retry attempts are exhausted.
        Exception
            The last exception raised after all retry attempts are exhausted,
            or any PERMANENT failure on the first occurrence.
        """

        timeout_s = self._timeout_config.timeout_for(query_type)
        last_exc: Optional[Exception] = None

        for attempt in range(self._policy.max_attempts):
            # Honour cancellation at the start of every attempt
            if stop_event is not None and stop_event.is_set():
                raise TaskCancelledException()

            start_time = time.monotonic()

            try:
                if timeout_s is None:
                    # No timeout: use lazy loading
                    results = []
                    with self.session() as session:
                        result = session.run(query_code)
                        for record in result:
                            if stop_event is not None and stop_event.is_set():
                                raise TaskCancelledException()
                            results.append(record)
                else:
                    # Timeout path: run query in a daemon thread 
                    result_holder: list = []
                    exc_holder: list = []

                    worker = threading.Thread(
                        target=self._run_query_in_thread,
                        args=(query_code, stop_event, result_holder, exc_holder),
                        daemon=True,
                    )
                    worker.start()
                    worker.join(timeout=timeout_s)

                    if worker.is_alive():
                        # Thread is still running — the query timed out
                        elapsed = time.monotonic() - start_time
                        logger.warning(
                            "Query [%s] timed out after %.2fs (limit=%.2fs), attempt %d/%d",
                            query_type.value,
                            elapsed,
                            timeout_s,
                            attempt + 1,
                            self._policy.max_attempts,
                        )
                        has_fallback, fallback_value = self._timeout_config.fallback_for(query_type)
                        if has_fallback:
                            logger.info(
                                "Returning fallback result for timed-out query [%s].",
                                query_type.value,
                            )
                            return fallback_value
                        # Treat as a transient error so retry logic applies
                        raise QueryTimeoutError(query_type, timeout_s)

                    # Thread finished — check for exceptions
                    if exc_holder:
                        raise exc_holder[0]

                    results = result_holder[0] if result_holder else []

                # Slow-query warning (fires regardless of timeout setting) ──
                elapsed = time.monotonic() - start_time
                warn_threshold = self._timeout_config.warn_threshold_s
                if warn_threshold is not None and elapsed >= warn_threshold:
                    logger.warning(
                        "Slow query [%s] completed in %.2fs (warn threshold=%.2fs)",
                        query_type.value,
                        elapsed,
                        warn_threshold,
                    )

                return results

            except TaskCancelledException:
                raise

            except Exception as exc:
                last_exc = exc

                # QueryTimeoutError is transient by design
                if isinstance(exc, QueryTimeoutError):
                    kind = FailureKind.TRANSIENT
                else:
                    kind = FailureClassifier.classify(exc)

                logger.warning(
                    "Query attempt %d/%d failed [%s – %s]: %s",
                    attempt + 1,
                    self._policy.max_attempts,
                    kind.name,
                    type(exc).__name__,
                    exc,
                )

                if not self._policy.should_retry(kind, attempt + 1):
                    logger.error(
                        "Non-retryable failure (%s). Aborting query.", kind.name
                    )
                    raise

                # For connectivity failures, try to reconnect before sleeping
                if kind in (FailureKind.TRANSIENT, FailureKind.UNKNOWN) and \
                        isinstance(exc, (ServiceUnavailable, SessionExpired,
                                         ConnectionError, OSError)):
                    with self._lock:
                        try:
                            logger.info("Attempting to reconnect …")
                            self._reconnect()
                        except Exception as reconnect_exc:
                            logger.warning(
                                "Reconnection failed: %s. Will retry after delay.",
                                reconnect_exc,
                            )

                delay = self._policy.delay_for(attempt)
                logger.info(
                    "Retrying in %.2f s (attempt %d/%d) …",
                    delay,
                    attempt + 2,
                    self._policy.max_attempts,
                )
                time.sleep(delay)

        raise last_exc   # type: ignore[misc]

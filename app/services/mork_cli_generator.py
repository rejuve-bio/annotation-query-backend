import os
import re
import sys
import atexit
import subprocess
import threading
import time
import hashlib
import uuid
from pathlib import Path
from functools import lru_cache
from collections import OrderedDict
from app.lib.mork_values import normalize_mork_value
from app.lib.logic import LogicValidationError
from app.services.mork_generator import MorkQueryGenerator
from app.services.mork_program import MorkJoinCompiler
from app.services.mork_output import parse_mork_output, serialize_mork_atom, flatten_mork_value, parse_mork_counts
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-process container registry
# ---------------------------------------------------------------------------
# One long-running mork:latest container is kept alive per dataset_path per
# worker process.  Queries are sent via `docker exec` (~100 ms overhead)
# instead of `docker run` (~1-2 s overhead).  All threads within one process
# share the same session; concurrent access is serialised by a per-session
# lock.

_session_registry: dict = {}
_registry_lock = threading.Lock()


_keep_containers_on_exit: bool = False


def set_keep_containers_on_exit(value: bool = True) -> None:
    """Called by Celery pool workers so containers survive process restart."""
    global _keep_containers_on_exit
    _keep_containers_on_exit = value


def _repair_mork_sexpr(line: str) -> str:
    """
    Repair truncated string literals in MORK S-expression output.

    MORK without interning limits symbols to 63 bytes. String literals longer than
    63 bytes get truncated before the closing quotation mark, producing malformed
    MeTTa syntax like `(node description (...) "A long text...))` without the closing `"`.
    This detects an unclosed string literal and inserts the closing quote before
    the outer closing parentheses.
    """
    stripped = line.strip()
    if not stripped:
        return line

    in_quote = False
    open_parens_outside_quotes = 0
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and in_quote and i + 1 < len(line):
            i += 2
            continue
        if ch == '"':
            in_quote = not in_quote
        elif not in_quote:
            if ch == "(":
                open_parens_outside_quotes += 1
            elif ch == ")":
                open_parens_outside_quotes = max(0, open_parens_outside_quotes - 1)
        i += 1

    if in_quote:
        idx = len(line)
        parens_found = 0
        while idx > 0 and parens_found < open_parens_outside_quotes:
            idx -= 1
            if line[idx] == ")":
                parens_found += 1
            elif line[idx] not in (" ", "\t", "\r", "\n"):
                idx += 1
                break
        return line[:idx] + '"' + line[idx:]
    return line


def _repair_mork_output(raw: str) -> str:
    return "\n".join(_repair_mork_sexpr(line) for line in raw.splitlines())


class _MorkSession:
    """Manages one long-running mork:latest container for a dataset path."""

    MORK_BIN = "/app/MORK/target/release/mork"

    _ALIVE_TTL = 5.0

    def __init__(self, dataset_path: str):
        self._path = dataset_path
        self._uid_gid = f"{os.getuid()}:{os.getgid()}"
        self._cid: str | None = None
        self._lock = threading.Lock()
        self._last_alive_check: float = 0.0
        self._dataset_id = hashlib.md5(dataset_path.encode()).hexdigest()[:8]

    def _alive(self) -> bool:
        if not self._cid:
            return False
        now = time.monotonic()
        if now - self._last_alive_check < self._ALIVE_TTL:
            return True
        r = subprocess.run(
            ["docker", "inspect", "--format={{.State.Running}}", self._cid],
            capture_output=True, text=True,
        )
        alive = r.returncode == 0 and r.stdout.strip() == "true"
        if alive:
            self._last_alive_check = now
        return alive

    def _recover(self) -> bool:
        """Reconnect to an existing container left by a previous worker process."""
        project = os.environ.get("COMPOSE_PROJECT_NAME", "")
        filters = [
            "--filter", "label=mork.worker=1",
            "--filter", f"label=mork.dataset={self._dataset_id}",
        ]
        if project:
            filters += ["--filter", f"label=mork.project={project}"]
        r = subprocess.run(
            ["docker", "ps", "-q", *filters],
            capture_output=True, text=True,
        )
        # docker ps -q may return multiple IDs (one per line); take the first
        cid = r.stdout.strip().split("\n")[0].strip()
        if cid:
            self._cid = cid
            self._last_alive_check = time.monotonic()
            logger.info(f"[MORK] Recovered container {cid[:12]} for {self._path}")
            return True
        return False

    def _start(self):
        labels = ["--label", "mork.worker=1", "--label", f"mork.dataset={self._dataset_id}"]
        project = os.environ.get("COMPOSE_PROJECT_NAME")
        if project:
            labels += ["--label", f"mork.project={project}"]
        try:
            r = subprocess.run([
                "docker", "run", "-d", "--rm",
                "-u", self._uid_gid,
                *labels,
                "-v", f"{self._path}:{self._path}:rw",
                "-v", "/dev/shm:/dev/shm",
                "-w", self._path,
                "mork:latest",
                "tail", "-f", "/dev/null",   # keeps container alive
            ], capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to start mork:latest container. "
                f"Build it with: docker build --network host -f app/services/mork/Dockerfile.mork -t mork:latest .\n"
                f"Docker stderr: {e.stderr.strip()}"
            ) from e
        self._cid = r.stdout.strip()

    def exec_query(self, query_file_name: str):
        with self._lock:
            if not self._alive():
                self._start()
            try:
                return subprocess.run([
                    "docker", "exec", self._cid,
                    self.MORK_BIN, "run", query_file_name,
                ], capture_output=True, text=True, check=True)
            except subprocess.CalledProcessError:
                # Invalidate TTL cache; if the container actually died within the
                # TTL window, restart and retry once to preserve self-healing.
                self._last_alive_check = 0.0
                if not self._alive():
                    self._start()
                    return subprocess.run([
                        "docker", "exec", self._cid,
                        self.MORK_BIN, "run", query_file_name,
                    ], capture_output=True, text=True, check=True)
                raise

    def run_program(self, query_file_name: str, timeout_s: int, stop_event=None) -> str:
        """Run a MORK program with a time limit; stop_event cancels it. Returns stdout."""
        with self._lock:
            if not self._alive():
                self._start()
            proc = subprocess.Popen([
                "docker", "exec", self._cid,
                "timeout", "--signal=KILL", str(int(timeout_s)), self.MORK_BIN, "run", query_file_name,
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            while True:
                try:
                    out, err = proc.communicate(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    if stop_event is not None and stop_event.is_set():
                        # Killing the docker exec client leaves MORK running
                        # inside the container, so kill it there by its file.
                        subprocess.run(["docker", "exec", self._cid, "pkill", "-KILL", "-f", query_file_name],
                                       capture_output=True)
                        proc.kill()
                        proc.communicate()
                        from app.error import TaskCancelledException
                        raise TaskCancelledException()
        if proc.returncode == 137:
            raise TimeoutError(f"MORK program exceeded {timeout_s} s")
        if proc.returncode != 0:
            raise RuntimeError(f"MORK program failed: {err.strip()[-2000:]}")
        return out

    def stop(self):
        if self._cid:
            subprocess.run(["docker", "stop", self._cid], capture_output=True)
            self._cid = None


def _get_session(dataset_path: str) -> _MorkSession:
    key = str(Path(dataset_path).resolve())
    with _registry_lock:
        if key not in _session_registry:
            session = _MorkSession(key)
            session._recover()  # reuse container if a previous worker left one running
            _session_registry[key] = session
        return _session_registry[key]


def run_mork_program(dataset_path, program: str, timeout_s: int, stop_event=None):
    """Run a complete MORK program against a dataset and return its atoms."""
    query_file = Path("/dev/shm") / f"query_{uuid.uuid4().hex}.metta"
    fd = os.open(query_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(program)
        out = _get_session(str(dataset_path)).run_program(str(query_file), timeout_s, stop_event)
    finally:
        query_file.unlink(missing_ok=True)
    body = out.split("result:", 1)[1] if "result:" in out else ""
    return parse_mork_output(_repair_mork_output(body))


def _cleanup_sessions():
    if _keep_containers_on_exit:
        # Pool worker exiting due to max_tasks_per_child — keep containers alive
        # so the next worker process can recover them without a cold ACT reload.
        logger.info("[MORK] Pool worker exiting; containers kept alive for next worker")
        return
    for session in list(_session_registry.values()):
        session.stop()


atexit.register(_cleanup_sessions)

import signal as _signal

def _make_signal_handler(sig: int):
    _prev = _signal.getsignal(sig)
    def _handler(signum: int, frame) -> None:
        try:
            _cleanup_sessions()
        except Exception:
            logger.exception("Error during MORK session cleanup")
        finally:
            if callable(_prev):
                _prev(signum, frame)
            elif _prev == _signal.SIG_IGN:
                return
            else:
                _signal.signal(sig, _signal.SIG_DFL)
                os.kill(os.getpid(), sig)
    return _handler

_signals_registered = False

def _register_cleanup_signals() -> None:
    """Register SIGTERM/SIGINT handlers that stop MORK containers on shutdown.

    Idempotent — safe to call from both the module-level guard and from a
    process-startup hook (e.g. FastAPI lifespan, Celery worker_init signal).
    Must be called from the main thread.

    Note: the module-level call below only fires when the module is first imported
    from the main thread.  When first imported via the FastAPI sync-dependency
    threadpool path (app.api.deps._make_mork_cli_generator) the guard is skipped
    and the module is then cached — so handlers are never installed for that
    worker process on that import path.  The lifespan call in app/main.py covers
    this gap.  atexit(_cleanup_sessions) still runs on normal (sys.exit) shutdown.
    """
    global _signals_registered
    if _signals_registered:
        return
    _signal.signal(_signal.SIGTERM, _make_signal_handler(_signal.SIGTERM))
    _signal.signal(_signal.SIGINT,  _make_signal_handler(_signal.SIGINT))
    _signals_registered = True


if threading.current_thread() is threading.main_thread():
    _register_cleanup_signals()


# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_property_schema():
    from app.services.schema_data import SchemaManager

    config = Path(__file__).resolve().parents[2] / 'config'
    # Reuse the app's schema construction without the API dependency's config
    # merging. The metadata is read once per process, never once per request.
    return SchemaManager(
        human_schema_config_path=str(config / 'human_schema/human_full_schema_config.yaml'),
        biocypher_config_path=str(config / 'biocypher_config.yaml'),
        human_datasources_config_path=str(config / 'human_schema/data_source_schemas'),
        fly_schema_config_path=str(config / 'fly_base_schema/dmel_full_schema_config.yaml'),
        fly_datasources_config_path=str(config / 'fly_base_schema/data_source_schemas'),
    ).full_schema_representation


class MorkCLIQueryGenerator(MorkQueryGenerator):
    supports_logic = True
    _COUNT_CACHE_SIZE = 128

    def __init__(self, dataset_path, act_filename="annotation.act", species="human"):
        super().__init__(dataset_path=None)
        self.dataset_path = Path(dataset_path)
        self.act_filename = act_filename
        self.species = species
        self._count_results = OrderedDict()
        self._count_lock = threading.Lock()
        self._neighbourhood_index = None

    @property
    def space(self):
        dataset_id = hashlib.md5(str(self.dataset_path.resolve()).encode()).hexdigest()[:8]
        return f"mork_{dataset_id}"

    def _link_act(self):
        """Point /dev/shm/<space>.act at the dataset's ACT (MORK reads ACTs from there)."""
        act_file = self.dataset_path / self.act_filename
        shm_act = Path("/dev/shm") / f"{self.space}.act"
        if not shm_act.exists() or act_file.stat().st_mtime > shm_act.stat().st_mtime:
            temp_shm = Path("/dev/shm") / f"{shm_act.name}.tmp.{uuid.uuid4().hex}"
            os.symlink(act_file.resolve(), temp_shm)
            os.replace(temp_shm, shm_act)

    def run_program(self, program, timeout_s, stop_event=None):
        self._link_act()
        return run_mork_program(self.dataset_path, program, timeout_s, stop_event)

    @property
    def neighbourhood_index(self):
        if self._neighbourhood_index is None:
            from app.services.mork_neighbourhood_index import NeighbourhoodIndex
            self._neighbourhood_index = NeighbourhoodIndex(
                self.dataset_path, self.act_filename, self.space, self.run_program)
        return self._neighbourhood_index

    def query_Generator(self, requests, node_map, limit=None, node_only=False):
        dataset_id = hashlib.md5(str(self.dataset_path.resolve()).encode()).hexdigest()[:8]
        result_id = self.generate_id()
        try:
            compiler = MorkJoinCompiler(requests, f"mork_{dataset_id}", result_id, self._safe_atom)
            program = compiler.compile(properties=True, schema=_get_property_schema().get(self.species, {}),
                                       counts=True, limit=limit)
        except ValueError as exc:
            raise LogicValidationError(str(exc)) from None
        # Keep the four-part query format serializable for the Celery workers.
        return [((program,), (), 'query', result_id),
                ((), (), 'total_count', result_id),
                ((), (), 'label_count', result_id)]

    def _serialize_metta_value(self, value):
        return normalize_mork_value(value)

    def _act_sources(self, target_space, patterns):
        # Callers may supply conjunctive patterns in one string. ACT accepts
        # exactly one expression per source.
        return " ".join(
            f"(ACT {target_space} {serialize_mork_atom(pattern)})"
            for pattern in parse_mork_output(patterns)
        )

    def _run_single_pattern(self, pattern_str, template_str):
        """Run a MORK pattern query and return atoms as nested tuples."""
        dataset_id = hashlib.md5(str(self.dataset_path.resolve()).encode()).hexdigest()[:8]
        target_space = f"mork_{dataset_id}"
        act_file = self.dataset_path / self.act_filename
        shm_act = Path("/dev/shm") / f"{target_space}.act"

        if not shm_act.exists() or (act_file.stat().st_mtime > shm_act.stat().st_mtime):
            try:
                temp_shm = Path("/dev/shm") / f"{shm_act.name}.tmp.{uuid.uuid4().hex}"
                os.symlink(act_file.resolve(), temp_shm)
                os.replace(temp_shm, shm_act)
            except Exception as e:
                if not shm_act.exists():
                    logger.warning(f"SHM Symlink update failed: {e}")

        sources = self._act_sources(target_space, pattern_str)
        metta_query = f'(exec 0 (I {sources}) (, {template_str}))'
        query_file = Path("/dev/shm") / f"query_{uuid.uuid4().hex}.metta"
        try:
            fd = os.open(query_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(metta_query)
            session = _get_session(str(self.dataset_path))
            result = session.exec_query(str(query_file))
            raw = result.stdout
            actual = raw.split("result:", 1)[1].strip() if "result:" in raw else raw.strip()
            if not actual:
                return []
            repaired = _repair_mork_output(actual)
            try:
                return parse_mork_output(repaired)
            except Exception as e:
                logger.warning(f"Failed to parse MORK output: {e}\nRaw: {actual}")
                return []
        except subprocess.CalledProcessError as e:
            logger.error(f"MORK single-pattern error: {e.stderr}")
            raise RuntimeError(f"MORK query failed: {e.stderr.strip()}") from e
        finally:
            if query_file.exists():
                try:
                    query_file.unlink()
                except Exception:
                    pass

    def is_ready(self):
        act_file = self.dataset_path / self.act_filename
        return act_file.exists()

    def connect(self):
        return None

    def parse_and_serialize(self, input, schema, graph_components, result_type):
        if result_type != 'graph':
            raw = [item for item in input if not isinstance(item, dict)]
            counts = parse_mork_counts(raw)
            if counts is None:
                graph = self._graph_result(raw, schema, graph_components)
                counts = {key: graph[key] for key in (
                    'node_count', 'edge_count', 'node_count_by_label', 'edge_count_by_label')}
            for item in input:
                if isinstance(item, dict):
                    counts.update({key: item[key] for key in counts if key in item})
            return counts
        return self._graph_result(input, schema, graph_components)

    def _graph_result(self, inputs, schema, graph_components):
        from .mork import get_count_by_label

        nodes, edges, properties = {}, {}, []
        species_schema = schema.get(self.species, {})
        node_schema, edge_schema = species_schema.get('nodes', {}), species_schema.get('edges', {})

        def add_node(term):
            if term not in nodes:
                node_type, identifier = term
                nodes[term] = {'id': f'{node_type} {identifier}', 'type': node_type}
            return nodes[term]['id']

        for atoms in inputs:
            for atom in atoms:
                if len(atom) != 2 or not isinstance(atom[1], tuple):
                    continue
                payload = atom[1]
                if atom[0] == 'tmp' and payload and payload[0] in ('node', 'edge'):
                    properties.append(payload)
                elif len(payload) == 2 and all(isinstance(part, str) for part in payload):
                    add_node(payload)
                elif (len(payload) == 3 and all(isinstance(part, tuple) and len(part) == 2
                                               for part in payload[1:])):
                    label, source, target = payload
                    key = (label, source, target)
                    if key not in edges:
                        edges[key] = {'id': self.generate_id(),
                                      'edge_id': f'{source[0]}_{label}_{target[0]}', 'label': label,
                                      'source': add_node(source), 'target': add_node(target)}

        named_properties = {'gene_name', 'transcript_name', 'protein_name', 'pathway_name', 'term_name'}
        for payload in properties:
            if len(payload) != 4:
                continue
            kind, name, subject, value = payload
            if kind == 'node':
                if subject not in nodes or name not in node_schema.get(subject[0], {}).get('properties', {}):
                    continue
                if name in ('synonym', 'synonyms', 'accessions'):
                    continue
                value = flatten_mork_value(value)
                if graph_components.get('properties', True) and name not in ('id', 'type'):
                    nodes[subject][name] = value
                if name in named_properties:
                    nodes[subject]['name'] = value
            elif kind == 'edge':
                if subject not in edges or name not in edge_schema.get(subject[0], {}).get('properties', {}):
                    continue
                if name == '_exists':
                    continue
                value = flatten_mork_value(value)
                if isinstance(value, list):
                    value = ' '.join(value)
                edges[subject]['source_data' if name == 'source' else name] = value

        for node in nodes.values():
            node.setdefault('name', node['id'])
        graph = {'nodes': [{'data': node} for node in nodes.values()],
                 'edges': [{'data': edge} for edge in edges.values()]}
        graph.update(parse_mork_counts(inputs) or get_count_by_label(graph))
        return graph

    def run_query(self, query, stop_event=None, species='human'):
        start_time = time.time()
        pattern_tuple, template_tuple, query_type, result_id = query

        if query_type in ('total_count', 'label_count') and not pattern_tuple:
            # Synchronous callers ask for counts after the graph on this same
            # instance. Workers use the graph task's Redis metadata instead.
            with self._count_lock:
                if result_id not in self._count_results:
                    raise RuntimeError('MORK counts require the graph query to run first on this instance')
                self._count_results.move_to_end(result_id)
                return [list(self._count_results[result_id])]

        pattern_str = " ".join(pattern_tuple)
        template_str = " ".join(template_tuple)

        dataset_id = hashlib.md5(str(self.dataset_path.resolve()).encode()).hexdigest()[:8]
        target_space = f"mork_{dataset_id}"

        act_file = self.dataset_path / self.act_filename
        shm_act = Path("/dev/shm") / f"{target_space}.act"

        if not act_file.exists():
            message = (
                f"Missing ACT file: {act_file}. "
                "Run 'python scripts/build_act.py' to generate it."
            )
            logger.error(message)
            raise FileNotFoundError(message)

        if not shm_act.exists() or (act_file.stat().st_mtime > shm_act.stat().st_mtime):
            try:
                temp_shm = Path("/dev/shm") / f"{shm_act.name}.tmp.{uuid.uuid4().hex}"
                os.symlink(act_file.resolve(), temp_shm)
                os.replace(temp_shm, shm_act)
            except Exception as e:
                if not shm_act.exists():
                    logger.warning(f"SHM Symlink update failed: {e}")

        if len(pattern_tuple) == 1 and not template_tuple:
            metta_query = pattern_tuple[0]
        else:
            sources = self._act_sources(target_space, pattern_str)
            metta_query = f'(exec 0 (I {sources}) (, {template_str}))'
        
        query_id = uuid.uuid4().hex
        query_file = Path("/dev/shm") / f"query_{query_id}.metta"

        try:
            fd = os.open(query_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(metta_query)


            try:
                session = _get_session(str(self.dataset_path))
                result = session.exec_query(str(query_file))
                raw_output = result.stdout
            except subprocess.CalledProcessError as e:
                logger.error(f"MORK exec error: {e.stderr}")
                raise RuntimeError(f"MORK query failed: {e.stderr.strip()}") from e

            if "result:" in raw_output:
                actual_result = raw_output.split("result:", 1)[1].strip()
            else:
                actual_result = raw_output.strip()

            metta_result = parse_mork_output(_repair_mork_output(actual_result))
            counts = [atom for atom in metta_result if atom and atom[0] == f'{result_id}_cnt']
            with self._count_lock:
                self._count_results[result_id] = counts
                self._count_results.move_to_end(result_id)
                while len(self._count_results) > self._COUNT_CACHE_SIZE:
                    self._count_results.popitem(last=False)
            
            duration = (time.time() - start_time) * 1000
            logger.info("Query executed", extra={"query": str(query), "duration_ms": duration, "status": "success"})
            
            return [metta_result]
        finally:
            if query_file.exists():
                try:
                    query_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete temp query file {query_file}: {e}")

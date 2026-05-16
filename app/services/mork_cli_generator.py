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
from app.services.mork_generator import MorkQueryGenerator
from hyperon import MeTTa
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

class MorkCLIQueryGenerator(MorkQueryGenerator):
    def __init__(self, dataset_path, act_filename="annotation.act", species="human"):
        super().__init__(dataset_path=None)
        self.dataset_path = Path(dataset_path)
        self.act_filename = act_filename
        self.species = species
        self.metta = MeTTa()

    def _run_single_pattern(self, pattern_str, template_str):
        """Run one single-pattern MORK query and return raw MeTTa atoms."""
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

        metta_query = f'(exec 0 (I (ACT {target_space} {pattern_str})) (, {template_str}))'
        query_file = Path("/dev/shm") / f"query_{uuid.uuid4().hex}.metta"
        try:
            fd = os.open(query_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(metta_query)
            session = _get_session(str(self.dataset_path))
            result = session.exec_query(str(query_file))
            raw = result.stdout
            actual = raw.split("result:", 1)[1].strip() if "result:" in raw else raw.strip()
            return self.metta.parse_all(actual)
        except subprocess.CalledProcessError as e:
            logger.error(f"MORK single-pattern error: {e.stderr}")
            raise RuntimeError(f"MORK query failed: {e.stderr.strip()}") from e
        finally:
            if query_file.exists():
                try:
                    query_file.unlink()
                except Exception:
                    pass

    def prepare_query_input(self, inputs, schema):
        """
        Batch-optimized: runs one MORK query per (node_type, property) pair
        instead of one per (node, property). Reduces docker exec calls from
        N×P to T×P where T = number of unique node types (typically 1-3).
        """
        from .metta.metta_seralizer import metta_seralizer
        result = []
        for atoms in inputs:
            if not atoms:
                continue
            tuples = metta_seralizer(atoms)
            for t in tuples:
                if t and t[0] == 'tmp':
                    t = t[1:]
                if len(t) == 2:
                    src_type, src_id = t
                    result.append({"source": f"{src_type} {src_id}"})
                elif len(t) == 5:
                    predicate, src_type, src_id, tgt_type, tgt_id = t
                    result.append({
                        "predicate": predicate,
                        "source": f"{src_type} {src_id}",
                        "target": f"{tgt_type} {tgt_id}",
                    })

        if not result:
            return "()", [[]], []

        to_be_removed = {'synonyms', 'accessions'}
        merged_atoms = []

        # --- Node properties: hybrid batch/per-node based on type population size ---
        from app.constants import BATCH_MAX_TYPE_SIZE, BATCH_NODE_THRESHOLD
        from app import graph_info as _graph_info
        _type_counts = {e['name']: e['count'] for e in _graph_info.get('top_entities', [])}

        nodes_by_type: dict[str, set] = {}
        for item in result:
            for role in ('source', 'target'):
                node_str = item.get(role)
                if not node_str:
                    continue
                parts = node_str.split(' ', 1)
                if len(parts) == 2:
                    node_type, node_id = parts
                    nodes_by_type.setdefault(node_type, set()).add(node_id)

        for node_type, node_ids in nodes_by_type.items():
            props = schema.get(self.species, {}).get('nodes', {}).get(node_type, {}).get('properties', {})
            total = _type_counts.get(node_type, 0)
            use_batch = total < BATCH_MAX_TYPE_SIZE and len(node_ids) >= BATCH_NODE_THRESHOLD

            if use_batch:
                _id_re = re.compile(rf'\({re.escape(node_type)} ([^\)]+)\)')
                for prop in props:
                    if prop in to_be_removed:
                        continue
                    pattern  = f'({prop} ({node_type} $n) $v)'
                    template = f'(tmp (node {prop} ({node_type} $n) $v))'
                    for atom in self._run_single_pattern(pattern, template):
                        m = _id_re.search(str(atom))
                        if m and m.group(1) in node_ids:
                            merged_atoms.append(atom)
            else:
                for node_id in node_ids:
                    node_str = f'{node_type} {node_id}'
                    for prop in props:
                        if prop in to_be_removed:
                            continue
                        var = self.generate_id()
                        pattern  = f'({prop} ({node_str}) ${var})'
                        template = f'(tmp (node {prop} ({node_str}) ${var}))'
                        merged_atoms.extend(self._run_single_pattern(pattern, template))

        # --- Edge properties: per-edge (few edges, unchanged) ---
        seen_edges: set = set()
        for item in result:
            if 'predicate' not in item or 'target' not in item:
                continue
            predicate = item['predicate']
            source    = item['source']
            target    = item['target']
            edge_key  = (predicate, source, target)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            edge_props = schema.get(self.species, {}).get('edges', {}).get(predicate, {}).get('properties', {})
            for prop in edge_props:
                var = self.generate_id()
                pattern  = f'({prop} ({predicate} ({source}) ({target})) ${var})'
                template = f'(tmp (edge {prop} ({predicate} ({source}) ({target})) ${var}))'
                merged_atoms.extend(self._run_single_pattern(pattern, template))

        dummy_query = ((), (), 'query')
        return dummy_query, [merged_atoms], result

    def is_ready(self):
        act_file = self.dataset_path / self.act_filename
        return act_file.exists()

    def connect(self):
        return None

    def parse_and_serialize(self, input, schema, graph_components, result_type):
        if result_type != 'graph':
            return super().parse_and_serialize(input, schema, graph_components, result_type)

        from .mork import get_total_counts, get_count_by_label
        from .metta import metta_seralizer

        query, result, prev_result = self.prepare_query_input(input, schema)
        tuples = metta_seralizer(result[0])

        if not tuples:
            nodes, edges = self.parse_and_seralize_no_properties(prev_result)
            meta_data = get_total_counts({"nodes": nodes, "edges": edges})
            meta_data.update(get_count_by_label({"nodes": nodes, "edges": edges}))
            return {
                "nodes": nodes, "edges": edges,
                "node_count": meta_data.get('node_count', 0),
                "edge_count": meta_data.get('edge_count', 0),
                "node_count_by_label": meta_data.get('node_count_by_label', []),
                "edge_count_by_label": meta_data.get('edge_count_by_label', []),
            }

        parsed = self.parse_and_serialize_properties(result, graph_components, result_type)

        if not prev_result:
            return parsed

        changed = False

        # Patch missing edges: process_result_graph only creates edges from
        # (tmp (edge ...)) atoms, which exist only when the schema has edge
        # properties.  Reconstruct any edge absent from the property result.
        existing_edge_keys = {
            (e['data']['label'], e['data']['source'], e['data']['target'])
            for e in parsed.get('edges', [])
        }
        for item in prev_result:
            if 'predicate' not in item or 'target' not in item:
                continue
            key = (item['predicate'], item['source'], item['target'])
            if key in existing_edge_keys:
                continue
            existing_edge_keys.add(key)
            src_label = item['source'].split(' ')[0]
            tgt_label = item['target'].split(' ')[0]
            parsed.setdefault('edges', []).append({"data": {
                "id": self.generate_id(),
                "edge_id": f"{src_label}_{item['predicate']}_{tgt_label}",
                "label": item['predicate'],
                "source": item['source'],
                "target": item['target'],
            }})
            changed = True

        # Patch missing nodes: any source/target referenced in prev_result that
        # has no property atoms (e.g. schema gap, no MORK data) won't appear in
        # the property-based node list — add it as a minimal node.
        existing_node_ids = {n['data']['id'] for n in parsed.get('nodes', [])}
        for item in prev_result:
            for role in ('source', 'target'):
                node_str = item.get(role)
                if not node_str or node_str in existing_node_ids:
                    continue
                existing_node_ids.add(node_str)
                node_type = node_str.split(' ')[0]
                parsed.setdefault('nodes', []).append({"data": {
                    "id": node_str,
                    "type": node_type,
                }})
                changed = True

        if changed:
            meta = get_total_counts({"nodes": parsed['nodes'], "edges": parsed['edges']})
            meta.update(get_count_by_label({"nodes": parsed['nodes'], "edges": parsed['edges']}))
            parsed['node_count'] = meta.get('node_count', 0)
            parsed['edge_count'] = meta.get('edge_count', 0)
            parsed['node_count_by_label'] = meta.get('node_count_by_label', [])
            parsed['edge_count_by_label'] = meta.get('edge_count_by_label', [])

        return parsed

    def _resolve_chained_patterns(self, pattern_tuple, template_tuple, query_obj, start_time):
        """
        Resolve an arbitrary multi-predicate query against ACT (which only supports
        single-pattern matching).

        Algorithm:
          1. Separate property-filter patterns (not in template) from predicate patterns.
          2. Phase 1 – run each property pattern to collect concrete node IDs; keep ALL
             matches as a list (bindings: var -> [val, ...]).
          3. Phase 2 – topological worklist: repeatedly pick any predicate whose input
             variables are already bound, expand all combinations of those values, run one
             MORK query per combination, collect result atoms AND capture new output-var
             values so downstream predicates can use them.
          4. Return the union of all collected result atoms.

        This handles linear chains (A→B→C), branching (A→B and A→C), and arbitrary DAGs.
        """
        import re
        import itertools

        def extract_vars(s):
            return set(re.findall(r'\$(\w+)', s))

        def capture_var_values(pat, var):
            atoms = self._run_single_pattern(pat, f'(captured_{var} ${var})')
            vals = []
            for atom in atoms:
                if hasattr(atom, 'get_children'):
                    ch = atom.get_children()
                    if len(ch) >= 2 and hasattr(ch[1], 'get_name'):
                        v = ch[1].get_name()
                        if v not in vals:
                            vals.append(v)
            return vals

        # Map predicate-body string → full template string
        body_to_tmpl = {}
        for t in template_tuple:
            m = re.match(r'^\s*\(\S+\s+(.+)\)\s*$', t.strip(), re.DOTALL)
            if m:
                body_to_tmpl[m.group(1).strip()] = t.strip()

        property_pats  = [p for p in pattern_tuple if p.strip() not in body_to_tmpl]
        predicate_pats = [p for p in pattern_tuple if p.strip() in body_to_tmpl]

        # Phase 1: resolve property-filter variables (bindings: var -> list[str])
        bindings = {}
        for prop in property_pats:
            for var in extract_vars(prop):
                if var in bindings:
                    continue
                vals = capture_var_values(prop.strip(), var)
                if vals:
                    bindings[var] = vals

        if not bindings and property_pats:
            duration = (time.time() - start_time) * 1000
            logger.info("Query executed", extra={"query": str(query_obj), "duration_ms": duration, "status": "no_match"})
            return [[]]

        # Pre-compute which vars appear in more than one predicate (need chaining)
        var_pred_count = {}
        for p in predicate_pats:
            for v in extract_vars(p):
                var_pred_count[v] = var_pred_count.get(v, 0) + 1
        chained_vars = {v for v, c in var_pred_count.items() if c > 1}

        # B4 constants: cap binding lists and Cartesian product size
        _MAX_BINDING_VALS = int(os.environ.get("MAX_BINDING_VALS", "1000"))
        _MAX_COMBOS       = int(os.environ.get("MAX_COMBOS", "50000"))

        # Phase 2: topological worklist
        resolved_vars = set(bindings.keys())
        remaining     = list(predicate_pats)
        all_atoms     = []
        _atom_cap     = False

        for _ in range(len(predicate_pats) ** 2 + 1):
            if not remaining or _atom_cap:
                break
            deferred = []
            progress = False

            for pred_pat in remaining:
                vars_in_pat = extract_vars(pred_pat)
                input_vars  = vars_in_pat & resolved_vars
                output_vars = vars_in_pat - resolved_vars

                if not input_vars and vars_in_pat:
                    # Only defer if another unprocessed pattern with resolved
                    # inputs shares our vars (meaning it will produce them for us).
                    # Patterns whose vars are all new outputs (e.g. a predicate
                    # starting from a concrete node ID) should run immediately.
                    produces_our_vars = any(
                        (extract_vars(other) & vars_in_pat)
                        and (extract_vars(other) & resolved_vars)
                        for other in remaining if other != pred_pat
                    )
                    if produces_our_vars:
                        deferred.append(pred_pat)
                        continue

                tmpl           = body_to_tmpl[pred_pat.strip()]
                input_var_list = sorted(input_vars)

                # B4: cap each binding list before building the Cartesian product
                for v in input_var_list:
                    if len(bindings[v]) > _MAX_BINDING_VALS:
                        logger.warning(f"[MORK] Capping binding ${v}: {len(bindings[v])} → {_MAX_BINDING_VALS}")
                        bindings[v] = bindings[v][:_MAX_BINDING_VALS]

                combos = (
                    list(itertools.product(*[bindings[v] for v in input_var_list]))
                    if input_var_list else [()]
                )
                if len(combos) > _MAX_COMBOS:
                    logger.warning(f"[MORK] Combo cap: {len(combos)} → {_MAX_COMBOS}")
                    combos = combos[:_MAX_COMBOS]

                new_vals = {v: [] for v in output_vars}

                for combo in combos:
                    subst_pat  = pred_pat.strip()
                    subst_tmpl = tmpl
                    # Sort longest var name first to prevent $n1 clobbering $n10
                    for var, val in sorted(zip(input_var_list, combo), key=lambda x: -len(x[0])):
                        subst_pat  = re.sub(r'\$' + re.escape(var) + r'(?!\w)', val, subst_pat)
                        subst_tmpl = re.sub(r'\$' + re.escape(var) + r'(?!\w)', val, subst_tmpl)

                    atoms = self._run_single_pattern(subst_pat, subst_tmpl)
                    all_atoms.extend(atoms)

                    # B5: early exit if atom count hits the hard cap
                    if len(all_atoms) >= 200_000:
                        logger.warning(f"[MORK] Early atom exit: {len(all_atoms)} atoms reached cap")
                        _atom_cap = True
                        break

                    # Capture output vars that feed into downstream predicates
                    for out_var in output_vars:
                        if out_var not in chained_vars:
                            continue
                        for v in capture_var_values(subst_pat, out_var):
                            if v not in new_vals[out_var]:
                                new_vals[out_var].append(v)

                for var, vals in new_vals.items():
                    if vals:
                        existing = bindings.get(var, [])
                        bindings[var] = existing + [v for v in vals if v not in existing]
                        resolved_vars.add(var)

                progress = True

            remaining = deferred
            if not progress:
                break

        duration = (time.time() - start_time) * 1000
        logger.info("Query executed", extra={"query": str(query_obj), "duration_ms": duration, "status": "success"})
        return [all_atoms]

    def run_query(self, query, stop_event=None, species='human'):
        start_time = time.time()
        pattern_tuple, template_tuple, query_type, _ = query

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

        if len(pattern_tuple) == 1:
            act_pattern = pattern_tuple[0]
            template_body = template_str
            metta_query = f'(exec 0 (I (ACT {target_space} {act_pattern})) (, {template_body}))'
        else:
            return self._resolve_chained_patterns(pattern_tuple, template_tuple, query, start_time)
        
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

            metta_result = self.metta.parse_all(actual_result)
            
            duration = (time.time() - start_time) * 1000
            logger.info("Query executed", extra={"query": str(query), "duration_ms": duration, "status": "success"})
            
            return [metta_result]
        finally:
            if query_file.exists():
                try:
                    query_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete temp query file {query_file}: {e}")
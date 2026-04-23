import os
import sys
import re
import atexit
import subprocess
import threading
import time
import hashlib
import uuid
from pathlib import Path
from app.services.mork_generator import MorkQueryGenerator
from hyperon import MeTTa
from app import perf_logger

# ---------------------------------------------------------------------------
# Fallback lookup helpers
# ---------------------------------------------------------------------------

def _is_direct_id_pattern(pattern_str):
    """True when pattern is '(type bare_identifier)' with no nested parens."""
    return bool(re.fullmatch(r'\(\S+\s+\S+\)', pattern_str.strip()))


def _make_name_fallback(pattern_str, template_str):
    """
    Rewrite a direct-ID pattern to a name-property pattern:
      (type ID)  →  (type_name (type $_fb_fallback) ID)
    Returns (None, None) if the pattern doesn't match the expected shape.
    """
    m = re.fullmatch(r'\((\S+)\s+(\S+)\)', pattern_str.strip())
    if not m:
        return None, None
    node_type, node_id = m.group(1), m.group(2)
    var = "$_fb_fallback"
    new_pattern = f"({node_type}_name ({node_type} {var}) {node_id})"
    new_template = template_str.replace(f"({node_type} {node_id})", f"({node_type} {var})")
    return new_pattern, new_template


def _make_id_fallback(pattern_str, template_str):
    """
    Rewrite a name-property pattern to a direct-ID pattern:
      (type_name (type $var) VALUE)  →  (type VALUE)
    Returns (None, None) if the pattern doesn't match the expected shape.
    """
    m = re.fullmatch(r'\((\S+)_name\s+\((\S+)\s+(\S+)\)\s+(\S+)\)', pattern_str.strip())
    if not m:
        return None, None
    node_type, value = m.group(2), m.group(4)
    new_pattern = f"({node_type} {value})"
    new_template = template_str
    return new_pattern, new_template


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


class _MorkSession:
    """Manages one long-running mork:latest container for a dataset path."""

    MORK_BIN = "/app/MORK/target/release/mork"

    def __init__(self, dataset_path: str):
        self._path = dataset_path
        self._uid_gid = f"{os.getuid()}:{os.getgid()}"
        self._cid: str | None = None
        self._lock = threading.Lock()

    def _alive(self) -> bool:
        if not self._cid:
            return False
        r = subprocess.run(
            ["docker", "inspect", "--format={{.State.Running}}", self._cid],
            capture_output=True, text=True,
        )
        return r.returncode == 0 and r.stdout.strip() == "true"

    def _start(self):
        r = subprocess.run([
            "docker", "run", "-d", "--rm",
            "-u", self._uid_gid,
            "-v", f"{self._path}:{self._path}:rw",
            "-v", "/dev/shm:/dev/shm",
            "-w", self._path,
            "mork:latest",
            "tail", "-f", "/dev/null",   # keeps container alive
        ], capture_output=True, text=True, check=True)
        self._cid = r.stdout.strip()

    def exec_query(self, query_file_name: str):
        with self._lock:
            if not self._alive():
                self._start()
            return subprocess.run([
                "docker", "exec", self._cid,
                self.MORK_BIN, "run", query_file_name,
            ], capture_output=True, text=True, check=True)

    def stop(self):
        if self._cid:
            subprocess.run(["docker", "stop", self._cid], capture_output=True)
            self._cid = None


def _get_session(dataset_path: str) -> _MorkSession:
    key = str(Path(dataset_path).resolve())
    with _registry_lock:
        if key not in _session_registry:
            _session_registry[key] = _MorkSession(key)
        return _session_registry[key]


def _cleanup_sessions():
    for session in list(_session_registry.values()):
        session.stop()


atexit.register(_cleanup_sessions)


# ---------------------------------------------------------------------------

class MorkCLIQueryGenerator(MorkQueryGenerator):
    def __init__(self, dataset_path, act_filename="annotation.act"):
        super().__init__(dataset_path=None)
        self.dataset_path = Path(dataset_path)
        self.act_filename = act_filename
        self.metta = MeTTa()

    def _run_single_pattern(self, pattern_str, template_str, _is_fallback=False):
        """Run one single-pattern MORK query and return raw MeTTa atoms.

        If the primary query returns no results, automatically retries in the
        opposite direction (direct-ID ↔ name-property) once.
        """
        from app import app
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
                    app.logger.warning(f"SHM Symlink update failed: {e}")

        metta_query = f'(exec 0 (I (ACT {target_space} {pattern_str})) (, {template_str}))'
        query_file = self.dataset_path / f"query_{uuid.uuid4().hex}.metta"
        try:
            with open(query_file, "w") as f:
                f.write(metta_query)
            session = _get_session(str(self.dataset_path))
            result = session.exec_query(query_file.name)
            raw = result.stdout
            actual = raw.split("result:", 1)[1].strip() if "result:" in raw else raw.strip()
            atoms = self.metta.parse_all(actual)
        except subprocess.CalledProcessError as e:
            from app import app as flask_app
            flask_app.logger.error(f"MORK single-pattern error: {e.stderr}")
            return []
        finally:
            if query_file.exists():
                try:
                    query_file.unlink()
                except Exception:
                    pass

        # Symmetric fallback: if primary returned nothing, try the other direction
        if not atoms and not _is_fallback:
            if _is_direct_id_pattern(pattern_str):
                fb_p, fb_t = _make_name_fallback(pattern_str, template_str)
            else:
                fb_p, fb_t = _make_id_fallback(pattern_str, template_str)
            if fb_p:
                app.logger.info(f"[MORK fallback] '{pattern_str}' → '{fb_p}'")
                atoms = self._run_single_pattern(fb_p, fb_t, _is_fallback=True)

        return atoms

    def prepare_query_input(self, inputs, schema):
        """
        ACT files do not support conjunction patterns.
        Run one query per property and merge the atom results instead of
        issuing a single (,  prop1  prop2 ...) conjunction.
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
        seen_nodes = set()

        for item in result:
            for role in ('source', 'target'):
                node_str = item.get(role)
                if not node_str or node_str in seen_nodes:
                    continue
                seen_nodes.add(node_str)
                node_type = node_str.split(' ')[0]
                props = schema.get('human', {}).get('nodes', {}).get(node_type, {}).get('properties', {})
                for prop in props:
                    if prop in to_be_removed:
                        continue
                    var = self.generate_id()
                    pattern  = f'({prop} ({node_str}) ${var})'
                    template = f'(tmp (node {prop} ({node_str}) ${var}))'
                    merged_atoms.extend(self._run_single_pattern(pattern, template))

            if 'predicate' in item and 'source' in item and 'target' in item:
                predicate = item['predicate']
                source    = item['source']
                target    = item['target']
                edge_props = schema.get('human', {}).get('edges', {}).get(predicate, {}).get('properties', {})
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
            perf_logger.info("Query executed", extra={"query": str(query_obj), "duration_ms": duration, "status": "no_match"})
            return [[]]

        # Pre-compute which vars appear in more than one predicate (need chaining)
        var_pred_count = {}
        for p in predicate_pats:
            for v in extract_vars(p):
                var_pred_count[v] = var_pred_count.get(v, 0) + 1
        chained_vars = {v for v, c in var_pred_count.items() if c > 1}

        # Phase 2: topological worklist
        resolved_vars = set(bindings.keys())
        remaining     = list(predicate_pats)
        all_atoms     = []

        for _ in range(len(predicate_pats) ** 2 + 1):
            if not remaining:
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
                combos = (
                    list(itertools.product(*[bindings[v] for v in input_var_list]))
                    if input_var_list else [()]
                )

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
        perf_logger.info("Query executed", extra={"query": str(query_obj), "duration_ms": duration, "status": "success"})
        return [all_atoms]

    def run_query(self, query, stop_event=None, species='human'):
        from app import app
        start_time = time.time()
        pattern_tuple, template_tuple, query_type = query

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
            app.logger.error(message)
            print(message, flush=True)
            raise FileNotFoundError(message)

        if not shm_act.exists() or (act_file.stat().st_mtime > shm_act.stat().st_mtime):
            try:
                temp_shm = Path("/dev/shm") / f"{shm_act.name}.tmp.{uuid.uuid4().hex}"
                os.symlink(act_file.resolve(), temp_shm)
                os.replace(temp_shm, shm_act)
            except Exception as e:
                if not shm_act.exists():
                    app.logger.warning(f"SHM Symlink update failed: {e}")

        if len(pattern_tuple) == 1:
            act_pattern = pattern_tuple[0]
            template_body = template_str
            metta_query = f'(exec 0 (I (ACT {target_space} {act_pattern})) (, {template_body}))'
        else:
            return self._resolve_chained_patterns(pattern_tuple, template_tuple, query, start_time)
        
        query_id = uuid.uuid4().hex
        query_file_name = f"query_{query_id}.metta"
        query_file = self.dataset_path / query_file_name
        
        try:
            with open(query_file, "w") as f:
                f.write(metta_query)
            

            try:
                session = _get_session(str(self.dataset_path))
                result = session.exec_query(query_file_name)
                raw_output = result.stdout
            except subprocess.CalledProcessError as e:
                app.logger.error(f"MORK exec error: {e.stderr}")
                return [[]]

            if "result:" in raw_output:
                actual_result = raw_output.split("result:", 1)[1].strip()
            else:
                actual_result = raw_output.strip()

            metta_result = self.metta.parse_all(actual_result)
            
            duration = (time.time() - start_time) * 1000
            perf_logger.info("Query executed", extra={"query": str(query), "duration_ms": duration, "status": "success"})
            
            return [metta_result]
        finally:
            if query_file.exists():
                try:
                    query_file.unlink()
                except Exception as e:
                    app.logger.warning(f"Failed to delete temp query file {query_file}: {e}")

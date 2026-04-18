import os
import subprocess
import sys
import time
import hashlib
import uuid
from pathlib import Path
from app.services.mork_generator import MorkQueryGenerator
from hyperon import MeTTa
from app import perf_logger

class MorkCLIQueryGenerator(MorkQueryGenerator):
    def __init__(self, dataset_path):
        super().__init__(dataset_path=None)
        self.dataset_path = Path(dataset_path)
        project_root = Path(__file__).resolve().parents[2]
        default_wrapper = project_root / "scripts" / "mork_docker_wrapper.py"
        if default_wrapper.exists():
            self.mork_bin = str(default_wrapper)
        else:
            raise RuntimeError("MORK docker wrapper not found.")
        self.metta = MeTTa()

    def _run_single_pattern(self, pattern_str, template_str):
        """Run one single-pattern MORK query and return raw MeTTa atoms."""
        from app import app
        dataset_id = hashlib.md5(str(self.dataset_path.resolve()).encode()).hexdigest()[:8]
        target_space = f"mork_{dataset_id}"
        act_file = self.dataset_path / "annotation.act"
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
            run_cmd = [sys.executable, self.mork_bin, "run", query_file.name]
            result = subprocess.run(run_cmd, capture_output=True, text=True,
                                    check=True, cwd=str(self.dataset_path))
            raw = result.stdout
            actual = raw.split("result:", 1)[1].strip() if "result:" in raw else raw.strip()
            return self.metta.parse_all(actual)
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
        act_file = self.dataset_path / "annotation.act"
        return act_file.exists()

    def connect(self):
        return None
        
    def run_query(self, query, stop_event=None, species='human'):
        from app import app
        start_time = time.time()
        pattern_tuple, template_tuple, query_type = query
        
        pattern_str = " ".join(pattern_tuple)
        template_str = " ".join(template_tuple)

        dataset_id = hashlib.md5(str(self.dataset_path.resolve()).encode()).hexdigest()[:8]
        target_space = f"mork_{dataset_id}"
        
        act_file = self.dataset_path / "annotation.act"
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
            # ACT does not support conjunction patterns.
            # Separate property-constraint patterns (not referenced in template)
            # from predicate patterns (referenced in template), resolve variable
            # bindings from property patterns first, then substitute into predicates.
            import re
            template_bodies = set()
            for t in template_tuple:
                m = re.match(r'^\s*\(\S+\s+(.+)\)\s*$', t.strip(), re.DOTALL)
                if m:
                    template_bodies.add(m.group(1).strip())

            property_pats = [p for p in pattern_tuple if p.strip() not in template_bodies]
            predicate_pats = [p for p in pattern_tuple if p.strip() in template_bodies]

            # Phase 1: resolve variable bindings from each property pattern
            bindings = {}  # var_name -> concrete value string
            for prop in property_pats:
                for var in re.findall(r'\$(\w+)', prop):
                    if var in bindings:
                        continue
                    capture_template = f'(captured_{var} ${var})'
                    atoms = self._run_single_pattern(prop.strip(), capture_template)
                    for atom in atoms:
                        if hasattr(atom, 'get_children'):
                            ch = atom.get_children()
                            if len(ch) >= 2 and hasattr(ch[1], 'get_name'):
                                bindings[var] = ch[1].get_name()
                                break  # take first match

            if not bindings and property_pats:
                # Property patterns matched nothing
                duration = (time.time() - start_time) * 1000
                perf_logger.info("Query executed", extra={"query": str(query), "duration_ms": duration, "status": "no_match"})
                return [[]]

            # Phase 2: substitute bindings into predicate patterns and templates
            all_atoms = []
            for pred_pat, tmpl in zip(predicate_pats, template_tuple):
                subst_pat = pred_pat.strip()
                subst_tmpl = tmpl.strip()
                for var, val in bindings.items():
                    subst_pat  = subst_pat.replace(f'${var}', val)
                    subst_tmpl = subst_tmpl.replace(f'${var}', val)
                all_atoms.extend(self._run_single_pattern(subst_pat, subst_tmpl))

            duration = (time.time() - start_time) * 1000
            perf_logger.info("Query executed", extra={"query": str(query), "duration_ms": duration, "status": "success"})
            return [all_atoms]
        
        query_id = uuid.uuid4().hex
        query_file_name = f"query_{query_id}.metta"
        query_file = self.dataset_path / query_file_name
        
        try:
            with open(query_file, "w") as f:
                f.write(metta_query)
            

            run_cmd = [sys.executable, self.mork_bin, "run", query_file_name]
            try:
                result = subprocess.run(run_cmd, capture_output=True, text=True, check=True, cwd=str(self.dataset_path))
                raw_output = result.stdout
            except subprocess.CalledProcessError as e:
                app.logger.error(f"MORK CLI Error Executing {run_cmd}: {e.stderr}")
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

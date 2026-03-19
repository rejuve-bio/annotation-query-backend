import os
import subprocess
import time
from pathlib import Path
from app.services.mork_generator import MorkQueryGenerator
from hyperon import MeTTa
from logger import init_logging

perf_logger = init_logging()

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

    def connect(self):
        return None
        
    def run_query(self, query, stop_event=None, species='human'):
        from app import app
        with app.config["annotation_lock"]:
            start_time = time.time()
            pattern_tuple, template_tuple, query_type = query
            
            pattern_str = " ".join(pattern_tuple)
            template_str = " ".join(template_tuple)

            target_space = "annotation"
            act_file = self.dataset_path / f"{target_space}.act"
            shm_act = Path("/dev/shm") / f"{target_space}.act"
            
            if not shm_act.exists() or (act_file.stat().st_mtime > shm_act.stat().st_mtime):
                try:
                    if shm_act.exists():
                        shm_act.unlink()
                    os.symlink(act_file.resolve(), shm_act)
                    print(f"Linked {act_file} to {shm_act}")
                except Exception as e:
                    print(f"SHM Symlink failed: {e}")
            
            if len(pattern_tuple) == 1:
                act_pattern = pattern_tuple[0]
                template_body = template_str
            else:
                act_pattern = f'(, {pattern_str})'
                template_body = template_str
            
            metta_query = f'(exec 0 (I (ACT {target_space} {act_pattern})) (, {template_body}))'
            
            query_file = self.dataset_path / "query.metta"
            with open(query_file, "w") as f:
                f.write(metta_query)
            
            print(f"Executing MeTTa Query: {metta_query}", flush=True)

            run_cmd = [self.mork_bin, "run", query_file.name]
            try:
                result = subprocess.run(run_cmd, capture_output=True, text=True, check=True, cwd=str(self.dataset_path))
                raw_output = result.stdout
            except subprocess.CalledProcessError as e:
                app.logger.error(f"MORK CLI Error Executing {run_cmd}: {e.stderr}")
                print(f"MORK CLI Error: {e.stderr}")
                return [[]]

            if "result:" in raw_output:
                actual_result = raw_output.split("result:", 1)[1].strip()
            else:
                actual_result = raw_output.strip()

            metta_result = self.metta.parse_all(actual_result)
            print(f"MORK Raw Output: {raw_output}", flush=True)
            print(f"MORK Parsed Result: {metta_result}", flush=True)
            
            duration = (time.time() - start_time) * 1000
            perf_logger.info("Query executed", extra={"query": str(query), "duration_ms": duration, "status": "success"})
            
            return [metta_result]

import os
import shutil
import subprocess

import pytest

from app.services.mork_cli_generator import MorkCLIQueryGenerator


def _docker_available():
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=10,
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def _require_env(var_name):
    value = os.getenv(var_name)
    if not value:
        pytest.skip(f"{var_name} is not set")
    return value


def test_mork_cli_runs_query():
    mork_data_dir = _require_env("MORK_DATA_DIR")
    if not _docker_available():
        pytest.skip("Docker is not available")

    generator = MorkCLIQueryGenerator(mork_data_dir)
    if not generator.is_ready():
        pytest.skip("annotation.act is missing; run scripts/build_act.py")

    node_type = "gene"
    node_id_value = "ENSG00000101349"
    if not node_id_value:
        pytest.skip("node id is not set")

    requests = {
        "nodes": [
            {
                "node_id": "n1",
                "id": node_id_value,
                "type": node_type,
                "properties": {},
            }
        ],
        "predicates": [],
    }

    requests = generator.parse_id(requests)
    node_map = {node["node_id"]: node for node in requests["nodes"]}

    queries = generator.query_Generator(requests, node_map, limit=None, node_only=False)
    result_query = queries[0]

    result = generator.run_query(result_query)

    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], list)

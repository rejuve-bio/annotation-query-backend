import os
import shutil
import subprocess

import pytest

from app import schema_manager
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


def _assert_node_schema(node_data, schema):
    node_type = node_data.get("type")
    if not node_type or node_type not in schema["nodes"]:
        return

    allowed = set(schema["nodes"][node_type].get("properties", {}).keys())
    allowed.update({"id", "type"})

    for key in node_data.keys():
        assert key in allowed


def _assert_edge_schema(edge_data, schema):
    edge_label = edge_data.get("label")
    if not edge_label or edge_label not in schema["edges"]:
        return

    allowed = set(schema["edges"][edge_label].get("properties", {}).keys())
    allowed.update({"edge_id", "label", "source", "target", "source_data"})

    for key in edge_data.keys():
        assert key in allowed


def test_mork_cli_response_shape(request_list):
    mork_data_dir = _require_env("MORK_DATA_DIR")
    if not _docker_available():
        pytest.skip("Docker is not available")

    generator = MorkCLIQueryGenerator(mork_data_dir)
    if not generator.is_ready():
        pytest.skip("annotation.act is missing; run scripts/build_act.py")

    species = os.getenv("MORK_TEST_SPECIES", "human")
    schema = schema_manager.full_schema_representation[species]

    request = generator.parse_id(request_list)
    node_map = {node["node_id"]: node for node in request["nodes"]}

    queries = generator.query_Generator(request, node_map, limit=None, node_only=False)
    result_query = queries[0]
    total_count_query = queries[1]
    count_by_label_query = queries[2]

    result = generator.run_query(result_query)

    graph_components = {
        "nodes": request["nodes"],
        "predicates": request.get("predicates", []),
        "properties": True,
    }

    graph_result = generator.parse_and_serialize(
        result,
        schema_manager.full_schema_representation,
        graph_components,
        result_type="graph",
    )

    assert isinstance(graph_result, dict)
    assert isinstance(graph_result.get("nodes"), list)
    assert isinstance(graph_result.get("edges"), list)

    nodes = graph_result.get("nodes", [])
    edges = graph_result.get("edges", [])

    for value in nodes[:10]:
        assert isinstance(value, dict)
        node_data = value.get("data", {})
        assert "id" in node_data
        assert "type" in node_data
        _assert_node_schema(node_data, schema)

    for value in edges[:10]:
        assert isinstance(value, dict)
        edge_data = value.get("data", {})
        assert "label" in edge_data
        assert "source" in edge_data
        assert "target" in edge_data
        _assert_edge_schema(edge_data, schema)

    total_count = generator.run_query(total_count_query)
    count_by_label = generator.run_query(count_by_label_query)
    count_result = [total_count[0], count_by_label[0]]

    meta_data = generator.parse_and_serialize(
        count_result,
        schema_manager.full_schema_representation,
        graph_components,
        result_type="count",
    )

    assert "node_count" in meta_data
    assert "edge_count" in meta_data
    assert "node_count_by_label" in meta_data
    assert "edge_count_by_label" in meta_data

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from openpyxl import load_workbook

from app.api.api_v1.endpoints import graph
from app.lib.utils import convert_to_excel


def test_workbook_preserves_node_and_edge_properties_as_text():
    formula_like_text = "=1+1"
    result = {
        "nodes": [
            {"data": {"id": "n1", "type": "example", "note": formula_like_text}},
        ],
        "edges": [
            {"data": {"source": "n1", "target": "n2", "note": formula_like_text}},
        ],
    }
    workbook = load_workbook(convert_to_excel(result))
    assert len(workbook.sheetnames) == 2
    for sheet in workbook:
        cells = [cell for row in sheet.iter_rows() for cell in row if cell.value == formula_like_text]
        assert len(cells) == 1
        assert cells[0].data_type == "s"


@pytest.mark.parametrize("backend", ["cypher", "metta", "mork", "mork_cli"])
def test_full_export_uses_backend_query_and_schema(monkeypatch, backend):
    species = "human"
    is_mork = backend in ("mork", "mork_cli")
    query = (("(example x)",), ("(result x)",), "query", "test-query")
    flat_schema = {"example": {}}
    full_schema = {species: {"nodes": {"example": {}}, "edges": {}}}
    schema_manager = SimpleNamespace(
        schema={species: flat_schema}, full_schema_representation=full_schema
    )
    request = {"nodes": ["example"], "predicates": []}
    annotation = SimpleNamespace(
        query=str(query) if is_mork else "backend query",
        species=species,
        request=request,
    )
    db = Mock(spec=["run_query", "parse_and_serialize"])
    db.parse_and_serialize.return_value = {
        "nodes": [{"data": {"id": "n1", "type": "example", "note": "kept"}}],
        "edges": [],
    }
    monkeypatch.setattr(graph.settings, "DATABASE_TYPE", {"type": backend})
    monkeypatch.setattr(graph, "get_downloadable_annotation", Mock(return_value=annotation))
    monkeypatch.setattr(graph, "get_db_instance", Mock(return_value=db))

    response = graph.download_full_annotation("test-id", "owner", schema_manager, Mock())

    assert response.headers["content-disposition"] == 'attachment; filename="annotation.xlsx"'
    db.run_query.assert_called_once_with(query if is_mork else annotation.query, species=species)
    db.parse_and_serialize.assert_called_once_with(
        db.run_query.return_value,
        full_schema if is_mork else flat_schema,
        {**request, "properties": True},
        result_type="graph",
    )

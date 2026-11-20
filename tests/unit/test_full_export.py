from openpyxl import load_workbook

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

"""MORK property encoding and ACT source arity (no database needed)."""

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from hyperon import MeTTa

from app.lib.mork_values import normalize_mork_value
from app.services import mork_cli_generator as mod
from app.services.mork_generator import MorkQueryGenerator


@pytest.mark.parametrize(("value", "expected"), [
    ("apoptotic process", "apoptotic_process"),
    ("  __DEAD/H (Asp-Glu-Ala-Asp/His) box__  ", "DEADH_Asp-Glu-Ala-AspHis_box"),
    ("A  B", "A__B"),
    ("a\tb\nc", "abc"),
    ("A -> B", "A_-_B"),
    ("GO: 0006915", "0006915"),
    ("prefix:local:part", "local:part"),
    ("v1.2-beta", "v1.2-beta"),
    ("TP53", "TP53"),
    ("tp53", "tp53"),
    ("Brca1", "Brca1"),
    ("α-beta", "-beta"),
    (True, "True"),
    (False, "False"),
    (123, "123"),
    (1.5, "1.5"),
    ("x" * 63, "x" * 63),
    ("x" * 64, "x" * 63),
    ("long value " * 10, ("long_value_" * 10)[:63]),
    (" https://example.org/a?b=c&d=e ", "https://example.org/a?b=c&d=e"),
    ("http://example.org/path", "http://example.org/path"),
    ("ftp://example.org/path", "ftp://example.org/path"),
    ("ftps://example.org/path", "ftps://example.org/path"),
    ("www.example.org/path", "www.example.org/path"),
    ("https://example.org/" + "x" * 100, ("https://example.org/" + "x" * 100)[:63]),
    ("https://example.org/x" + "é" * 40, "https://example.org/x" + "é" * 21),
])
def test_property_values_match_writer_rules(value, expected):
    assert normalize_mork_value(value) == expected


@pytest.mark.parametrize("value", [
    "", "   ", "()", "___", None, [], {},
    "https://example.org/(exec)", 'https://example.org/"value"',
    "https://example.org/a b", "https://example.org/a\\b",
    "https://example.org/" + "x" * 42 + "é",
])
def test_unrepresentable_values_are_rejected(value):
    with pytest.raises(ValueError, match="Invalid MORK property value"):
        normalize_mork_value(value)


@pytest.fixture
def gen(tmp_path, monkeypatch):
    instance = mod.MorkCLIQueryGenerator(tmp_path)
    (tmp_path / instance.act_filename).touch()
    # Keep the query and ACT links inside the test's temporary directory.
    monkeypatch.setattr(mod, "Path", lambda path: tmp_path if path == "/dev/shm" else Path(path))
    return instance


def node(node_id="n0", node_type="gene", properties=None, identifier=""):
    return {"node_id": node_id, "type": node_type, "id": identifier,
            "properties": properties or {}}


def capture_programs(monkeypatch):
    programs = []

    def execute(path):
        programs.append(Path(path).read_text())
        return SimpleNamespace(stdout="result:\n")

    monkeypatch.setattr(mod, "_get_session", lambda _: SimpleNamespace(exec_query=execute))
    return programs


@pytest.mark.parametrize("query_index", [0, 1, 2])
def test_multiple_properties_use_separate_conjunctive_act_sources(gen, monkeypatch, query_index):
    request = {"nodes": [node(properties={"gene_type": "protein_coding", "chr": "chr17"})],
               "predicates": []}
    original = copy.deepcopy(request)
    queries = gen.query_Generator(request, {"n0": request["nodes"][0]})
    programs = capture_programs(monkeypatch)

    gen.run_query(queries[query_index])

    program = MeTTa().parse_all(programs[0])[0]
    sources = program.get_children()[2].get_children()[1:]
    assert len(sources) == 2
    assert all(len(source.get_children()) == 3 for source in sources)
    assert "(gene_type (gene $n0) protein_coding)" in str(sources[0])
    assert "(chr (gene $n0) chr17)" in str(sources[1])
    assert request == original


def test_single_pattern_runner_preserves_property_conjunction(gen, monkeypatch):
    programs = capture_programs(monkeypatch)
    gen._run_single_pattern(
        "(gene_name (gene $n0) TP53) (chr (gene $n0) chr17)",
        "(captured_n0 $n0)",
    )
    program = MeTTa().parse_all(programs[0])[0]
    sources = program.get_children()[2].get_children()[1:]
    assert len(sources) == 2
    assert all(len(source.get_children()) == 3 for source in sources)


def test_values_are_normalized_in_node_and_predicate_queries(gen):
    source = node(properties={"term_name": "apoptotic process"}, node_type="biological_process")
    request = {"nodes": [source], "predicates": []}
    assert "apoptotic_process" in gen.query_Generator(request, {"n0": source})[0][0][0]

    gene = node("n1", properties={"gene_name": "DEAD/H (box)"})
    request = {"nodes": [gene, source], "predicates": [
        {"predicate_id": "p0", "type": "involved in", "source": "n1", "target": "n0"},
    ]}
    patterns = gen.query_Generator(request, {"n1": gene, "n0": source})[0][0]
    assert "DEADH_box" in patterns[0]
    assert "apoptotic_process" in " ".join(patterns)


def test_existing_identifier_case_is_preserved(gen):
    source = node(identifier="MixedCase_ID")
    query = gen.query_Generator({"nodes": [source], "predicates": []}, {"n0": source})[0]
    assert query[0] == ("(gene MixedCase_ID)",)


def test_http_value_serialization_is_unchanged():
    gen = MorkQueryGenerator.__new__(MorkQueryGenerator)
    assert gen._serialize_metta_value("apoptotic process") == '"apoptotic process"'

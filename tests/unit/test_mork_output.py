"""Tokenizer and graph serialization for native MORK output."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from hyperon import MeTTa

from app.services import mork_cli_generator as mod
from app.services.metta import metta_seralizer
from app.services.mork_output import parse_mork_output, serialize_mork_atom, flatten_mork_value


@pytest.mark.parametrize('text', [
    '(q (gene X))',
    '(q (transcribes_to (gene X) (transcript Y)))',
    '(tmp (node number (gene X) 42))',
    '(tmp (node flag (gene X) True))',
    '(tmp (node number (gene X) -1.25))',
    '(tmp (node description (gene X) "hello world"))',
    r'(tmp (node description (gene X) "a \"quoted\" word"))',
    r'(tmp (node description (gene X) "path\\part"))',
    '(tmp (node biological_context (gene X) (anatomy UBERON_1)))',
    '(q (gene X))\n(q (gene Y))',
    '(q\n (gene X)) (q (gene Y))',
    '(, (gene X) (transcript Y))',
])
def test_tokenizer_values_match_the_existing_serializer(text):
    atoms = parse_mork_output(text)
    flattened = [tuple(flatten_mork_value(child)) for atom in atoms for child in atom
                 if isinstance(child, tuple)]
    assert flattened == metta_seralizer(MeTTa().parse_all(text))
    assert parse_mork_output('\n'.join(serialize_mork_atom(atom) for atom in atoms)) == atoms


@pytest.mark.parametrize('text', [')', '(', '(q (gene X)', 'q', '(q "broken)', '(q) "broken'])
def test_malformed_output_is_rejected(text):
    with pytest.raises(ValueError, match='Invalid MORK output'):
        parse_mork_output(text)


def test_empty_output():
    assert parse_mork_output(' \n\t') == []


def test_truncated_string_repair_is_preserved():
    raw = '(tmp (node description (gene X) "a truncated string))'
    atoms = parse_mork_output(mod._repair_mork_output(raw))
    assert atoms == [('tmp', ('node', 'description', ('gene', 'X'), '"a truncated string"'))]


SCHEMA = {'human': {
    'nodes': {
        'gene': {'properties': {'gene_name': {}, 'description': {}, 'biological_context': {}, 'synonym': {}}},
        'transcript': {'properties': {'transcript_name': {}}},
        'protein': {'properties': {}},
    },
    'edges': {'transcribes_to': {'properties': {'score': {}, 'source': {}}}},
}}


@pytest.fixture
def gen(tmp_path, monkeypatch):
    gen = mod.MorkCLIQueryGenerator(tmp_path)
    (tmp_path / gen.act_filename).touch()
    monkeypatch.setattr(mod, 'Path', lambda path: tmp_path if path == '/dev/shm' else Path(path))
    monkeypatch.setattr(mod, '_get_property_schema', lambda: SCHEMA)
    monkeypatch.setattr(gen.metta, 'parse_all', lambda *args: pytest.fail('Hyperon output parsing'))
    monkeypatch.setattr(gen, '_run_single_pattern', lambda *args: pytest.fail('extra property query'))
    return gen


DUMP = '''
(q (transcribes_to (gene G1) (transcript T1)))
(q (translates_to (transcript T1) (protein P1)))
(tmp (node gene_name (gene G1) TP53))
(tmp (node description (gene G1) "keeps quoted text"))
(tmp (node biological_context (gene G1) (anatomy UBERON_1)))
(tmp (node synonym (gene G1) omitted))
(tmp (node undeclared (gene G1) omitted))
(tmp (node transcript_name (transcript T1) TP53-201))
(tmp (node gene_name (gene OUTSIDE) omitted))
(tmp (edge score (transcribes_to (gene G1) (transcript T1)) 0.5))
(tmp (edge source (transcribes_to (gene G1) (transcript T1)) evidence))
'''


def test_graph_keeps_topology_properties_names_and_schema_filtering(gen):
    graph = gen.parse_and_serialize([parse_mork_output(DUMP)], SCHEMA, {'properties': True}, 'graph')
    nodes = {node['data']['id']: node['data'] for node in graph['nodes']}
    edges = {edge['data']['label']: edge['data'] for edge in graph['edges']}
    assert graph['node_count'] == 3
    assert graph['edge_count'] == 2
    assert nodes['gene G1'] == {
        'id': 'gene G1', 'type': 'gene', 'name': 'TP53', 'gene_name': 'TP53',
        'description': '"keeps quoted text"', 'biological_context': ['anatomy', 'UBERON_1'],
    }
    assert nodes['transcript T1']['name'] == 'TP53-201'
    assert nodes['protein P1'] == {'id': 'protein P1', 'type': 'protein', 'name': 'protein P1'}
    assert edges['transcribes_to']['score'] == '0.5'
    assert edges['transcribes_to']['source'] == 'gene G1'
    assert edges['transcribes_to']['source_data'] == 'evidence'


def test_properties_false_keeps_display_names(gen):
    graph = gen.parse_and_serialize([parse_mork_output(DUMP)], SCHEMA, {'properties': False}, 'graph')
    gene = next(node['data'] for node in graph['nodes'] if node['data']['type'] == 'gene')
    assert gene == {'id': 'gene G1', 'type': 'gene', 'name': 'TP53'}


def test_missing_properties_and_empty_results_are_supported(gen):
    graph = gen.parse_and_serialize([parse_mork_output('(q (gene G1))')], {}, {}, 'graph')
    assert graph['nodes'] == [{'data': {'id': 'gene G1', 'type': 'gene', 'name': 'gene G1'}}]
    assert graph['node_count'] == 1
    empty = gen.parse_and_serialize([[]], SCHEMA, {}, 'graph')
    assert empty == {'nodes': [], 'edges': [], 'node_count': 0, 'edge_count': 0,
                     'node_count_by_label': [], 'edge_count_by_label': []}


def test_count_queries_can_use_tokenizer_results(gen):
    atoms = parse_mork_output(DUMP)
    counts = gen.parse_and_serialize([atoms, atoms], SCHEMA, {}, 'count')
    assert counts['node_count'] == 3
    assert counts['edge_count'] == 2


def test_query_and_serialization_use_one_process_and_no_hyperon(gen, monkeypatch):
    calls = []

    def execute(path):
        calls.append(Path(path).read_text())
        return SimpleNamespace(stdout='result:\n' + DUMP)

    monkeypatch.setattr(mod, '_get_session', lambda _: SimpleNamespace(exec_query=execute))
    req = {'nodes': [{'node_id': 'n0', 'type': 'gene', 'id': '', 'properties': {'gene_name': 'TP53'}}],
           'predicates': []}
    query = gen.query_Generator(req, {'n0': req['nodes'][0]})[0]
    output = gen.run_query(query)
    graph = gen.parse_and_serialize(output, SCHEMA, {'properties': True}, 'graph')
    assert graph['node_count'] == 3
    assert len(calls) == 1
    assert '(tmp (node gene_name ' in calls[0]
    assert '(tmp (node synonym ' not in calls[0]


def test_run_query_repairs_truncated_output_before_tokenizing(gen, monkeypatch):
    raw = '(q (gene G1))\n(tmp (node description (gene G1) "truncated))'
    monkeypatch.setattr(mod, '_get_session', lambda _: SimpleNamespace(
        exec_query=lambda _: SimpleNamespace(stdout='result:\n' + raw)))
    result = gen.run_query((('(gene G1)',), ('(q (gene G1))',), 'query', 'q'))
    graph = gen.parse_and_serialize(result, SCHEMA, {}, 'graph')
    assert graph['nodes'][0]['data']['description'] == '"truncated"'

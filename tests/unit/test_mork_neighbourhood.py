"""MORK neighbourhood expansion: programs run through the test interpreter."""

from types import SimpleNamespace

import pytest

from app.error import NeighbourhoodUnavailableError, TaskCancelledException
from app.services import mork_neighbourhood as mod
from app.services.mork_neighbourhood import MorkNeighbourhood
from test_mork_program import evaluate

FACTS = '''
(gene G1) (gene G2) (transcript T1) (transcript T2) (transcript T3) (protein P1)
(gene_name (gene G1) TP53) (gene_type (gene G1) protein_coding) (synonym (gene G1) P53)
(gene_name (gene G2) MDM2)
(transcript_name (transcript T1) TP53-201) (transcript_name (transcript T2) TP53-202)
(transcribes_to (gene G1) (transcript T1)) (transcribes_to (gene G1) (transcript T2))
(transcribes_to (gene G1) (transcript T3))
(regulates (gene G1) (gene G2))
(translates_to (transcript T1) (protein P1))
(source (transcribes_to (gene G1) (transcript T1)) GENCODE)
(evidence (regulates (gene G1) (gene G2)) IDA) (evidence (regulates (gene G1) (gene G2)) TAS)
'''

VOCABULARY = {
    'triples': [['gene', 'regulates', 'gene'], ['gene', 'transcribes_to', 'transcript'],
                ['transcript', 'translates_to', 'protein']],
    'node_types': ['gene', 'protein', 'transcript'],
    'node_properties': {'gene': ['gene_name', 'gene_type', 'synonym'], 'transcript': ['transcript_name']},
    'edge_properties': {'regulates': ['evidence'], 'transcribes_to': ['source']},
}


def backend(vocabulary=VOCABULARY):
    programs = []

    def run_program(program, timeout_s, stop_event=None):
        programs.append(program)
        return list(evaluate(program, FACTS))

    generator = SimpleNamespace(space='human', run_program=run_program,
                                neighbourhood_index=SimpleNamespace(vocabulary=lambda: vocabulary))
    nb = MorkNeighbourhood(generator, 'human')
    nb.programs = programs
    return nb


def request(seed='G1', seed_type='gene', max_hops=1, hops=None, per_node_limit=50, properties=True):
    return {'seed': {'type': seed_type, 'id': seed}, 'max_hops': max_hops,
            'hops': hops or [{'direction': 'out', 'limit': 500}],
            'per_node_limit': per_node_limit, 'properties': properties}


def nodes_of(result):
    return {n['data']['id']: n['data'] for n in result['nodes']}


def edges_of(result):
    return {(e['data']['source'], e['data']['label'], e['data']['target']): e['data'] for e in result['edges']}


def test_one_hop_returns_the_neo4j_shape_with_properties_and_names():
    result = backend().expand(request())
    assert result['seed'] == {'type': 'gene', 'id': 'G1', 'found': True, 'node_id': 'gene G1'}
    nodes = nodes_of(result)
    assert nodes['gene G1'] == {'id': 'gene G1', 'type': 'gene', 'hop': 0, 'gene_name': 'TP53',
                                'gene_type': 'protein_coding', 'name': 'TP53'}   # no synonym
    assert nodes['transcript T1']['name'] == 'TP53-201' and nodes['transcript T1']['hop'] == 1
    assert nodes['transcript T3']['name'] == 'transcript T3'   # no name property: id
    edges = edges_of(result)
    assert set(edges) == {('gene G1', 'transcribes_to', f'transcript {t}') for t in ('T1', 'T2', 'T3')} | {
        ('gene G1', 'regulates', 'gene G2')}
    assert edges[('gene G1', 'transcribes_to', 'transcript T1')] == {
        'source': 'gene G1', 'target': 'transcript T1', 'label': 'transcribes_to', 'hop': 1,
        'edge_id': 'gene_transcribes_to_transcript', 'source_data': 'GENCODE'}
    assert edges[('gene G1', 'regulates', 'gene G2')]['evidence'] == ['IDA', 'TAS']   # multi-valued
    assert result['node_count'] == 5 and result['edge_count'] == 4
    assert result['hops'] == [{'hop': 1, 'node_count': 4, 'edge_count': 4, 'truncated': False, 'ranked_by': None}]
    assert sorted((r['label'], r['count']) for r in result['node_count_by_label']) == [('gene', 2), ('transcript', 3)]


def test_programs_leave_no_helper_atoms():
    nb = backend()
    nb.expand(request())
    atoms = evaluate(nb.programs[0], FACTS)
    assert {atom[0] for atom in atoms} <= {'seed', 'out', 'np', 'ep'}


def test_missing_or_invalid_seed_is_not_found():
    for seed in ('NOPE', 'G1) (x', '$x'):
        result = backend().expand(request(seed=seed))
        assert result['seed']['found'] is False and result['nodes'] == [] and result['hops'] == []


def test_edge_and_node_type_filters():
    result = backend().expand(request(hops=[{'direction': 'out', 'limit': 500, 'edge_types': ['regulates']}]))
    assert set(edges_of(result)) == {('gene G1', 'regulates', 'gene G2')}
    result = backend().expand(request(hops=[{'direction': 'out', 'limit': 500, 'node_types': ['transcript']}]))
    assert {e[2] for e in edges_of(result)} == {'transcript T1', 'transcript T2', 'transcript T3'}


def test_hop_limit_truncates_and_marks_the_hop():
    result = backend().expand(request(hops=[{'direction': 'out', 'limit': 2}]))
    assert result['edge_count'] == 2 and result['truncated'] is True
    assert result['hops'][0]['truncated'] is True


def test_two_hops_expand_only_new_nodes_with_per_node_limit():
    hops = [{'direction': 'out', 'limit': 500, 'edge_types': ['transcribes_to']},
            {'direction': 'out', 'limit': 500}]
    result = backend().expand(request(max_hops=2, hops=hops, per_node_limit=1))
    edges = edges_of(result)
    assert ('transcript T1', 'translates_to', 'protein P1') in edges
    assert edges[('transcript T1', 'translates_to', 'protein P1')]['hop'] == 2
    assert nodes_of(result)['protein P1']['hop'] == 2
    assert [h['edge_count'] for h in result['hops']] == [3, 1]


def test_last_hop_filter_repeats_and_empty_frontier_stops():
    nb = backend()
    result = nb.expand(request(max_hops=3, hops=[{'direction': 'out', 'limit': 500, 'edge_types': ['transcribes_to']}]))
    # hop 2 repeats transcribes_to from transcripts: nothing, so hop 3 never runs
    assert [h['hop'] for h in result['hops']] == [1, 2] and len(nb.programs) == 2


def test_properties_false_keeps_only_names():
    nodes = nodes_of(backend().expand(request(properties=False)))
    assert nodes['gene G1'] == {'id': 'gene G1', 'type': 'gene', 'hop': 0, 'name': 'TP53'}
    assert 'source_data' not in edges_of(backend().expand(request(properties=False)))[
        ('gene G1', 'transcribes_to', 'transcript T1')]


def test_total_node_cap(monkeypatch):
    monkeypatch.setattr(mod, 'NEIGHBOURHOOD_MAX_TOTAL_NODES', 3)
    result = backend().expand(request())
    assert result['node_count'] == 3 and result['truncated'] is True


def test_validation_uses_the_vocabulary_and_neo4j_messages():
    hops = [{'direction': 'out', 'edge_types': ['nope'], 'node_types': ['cell'],
             'where': [{'property': 'score', 'op': '>=', 'value': 1}]}]
    errors = backend().validate({'seed': {'type': 'gen', 'id': 'x'}, 'hops': hops})
    assert errors[:4] == ["Unknown node type for human: 'gen'",
                          "hops[0]: unknown edge type for human: 'nope'",
                          "hops[0]: unknown node type for human: 'cell'",
                          "hops[0]: unknown edge property for human: 'score'"]
    assert backend().validate(request()) == []


def test_unsupported_parts_are_refused_for_now():
    errors = backend().validate(request(hops=[{'direction': 'both'}, {'direction': 'out', 'order_by': 'evidence'}]))
    assert any("direction 'both'" in e for e in errors) and any("'order_by'" in e for e in errors)


def test_index_not_ready_queues_a_build_and_reports_unavailable(monkeypatch):
    queued = []
    monkeypatch.setattr('app.workers.neighbourhood_task.request_index_build', queued.append)
    with pytest.raises(NeighbourhoodUnavailableError, match='being built'):
        backend(vocabulary=None).validate(request())
    assert queued == ['human']


def test_cancelled_before_a_hop():
    stop = SimpleNamespace(is_set=lambda: True)
    with pytest.raises(TaskCancelledException):
        backend().expand(request(), stop_event=stop)

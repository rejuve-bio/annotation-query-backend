"""MORK neighbourhood expansion: programs run through the test interpreter."""

from types import SimpleNamespace

import pytest

from app.error import NeighbourhoodUnavailableError, TaskCancelledException
from app.services import mork_neighbourhood as mod
from app.services.mork_neighbourhood import MorkNeighbourhood
from app.services.mork_neighbourhood_index import MISSING, READY, VOCABULARY_ONLY
from app.services.mork_output import parse_mork_output
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
(snp S1) (snp S2)
(closest_gene (snp S1) (gene G1)) (closest_gene (snp S2) (gene G1)) (closest_gene (snp S2) (gene G2))
(distance (closest_gene (snp S1) (gene G1)) 120)
(coexpressed_with (gene G1) (gene G2)) (coexpressed_with (gene G2) (gene G1))
(protein P2) (protein P3) (protein P4) (protein P5) (protein P6)
(interacts_with (protein P1) (protein P2)) (score (interacts_with (protein P1) (protein P2)) 0.9)
(interacts_with (protein P1) (protein P3)) (score (interacts_with (protein P1) (protein P3)) 0.4)
(interacts_with (protein P1) (protein P4))
(interacts_with (protein P1) (protein P5)) (score (interacts_with (protein P1) (protein P5)) 0.2)
(score (interacts_with (protein P1) (protein P5)) 0.8)
(interacts_with (protein P1) (protein P6)) (score (interacts_with (protein P1) (protein P6)) high)
(evidence (interacts_with (protein P1) (protein P2)) Inferred_from_IEA)
(evidence (interacts_with (protein P1) (protein P3)) TAS)
'''

VOCABULARY = {
    'triples': [['gene', 'coexpressed_with', 'gene'], ['gene', 'regulates', 'gene'],
                ['gene', 'transcribes_to', 'transcript'], ['snp', 'closest_gene', 'gene'],
                ['protein', 'interacts_with', 'protein'], ['transcript', 'translates_to', 'protein']],
    'node_types': ['gene', 'protein', 'snp', 'transcript'],
    'node_properties': {'gene': ['gene_name', 'gene_type', 'synonym'], 'transcript': ['transcript_name']},
    'edge_properties': {'closest_gene': ['distance'], 'interacts_with': ['evidence', 'score'],
                        'regulates': ['evidence'], 'transcribes_to': ['source']},
}


def reverse_spaces():
    """Each non-symmetric edge type stored target-first, as the index builds it."""
    spaces = {}
    for atom in parse_mork_output(FACTS):
        if len(atom) == 3 and all(isinstance(x, tuple) for x in atom[1:]) and atom[0] != 'coexpressed_with':
            name = f'rev_{atom[1][0]}_{atom[0]}_{atom[2][0]}'
            spaces[name] = spaces.get(name, '') + f'({atom[0]} ({atom[2][0]} {atom[2][1]}) ({atom[1][0]} {atom[1][1]}))\n'
    return spaces


def backend(vocabulary=VOCABULARY, status=READY):
    programs = []
    spaces = {'human': FACTS, **reverse_spaces()}

    def run_program(program, timeout_s, stop_event=None):
        programs.append(program)
        return list(evaluate(program, spaces))

    def reverse_space(triple):
        name = 'rev_' + '_'.join(triple)
        return name if status == READY and name in spaces else None

    index = SimpleNamespace(vocabulary=lambda: vocabulary, status=lambda: status, reverse_space=reverse_space)
    generator = SimpleNamespace(space='human', run_program=run_program, neighbourhood_index=index)
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
        ('gene G1', 'regulates', 'gene G2'), ('gene G1', 'coexpressed_with', 'gene G2')}
    assert edges[('gene G1', 'transcribes_to', 'transcript T1')] == {
        'source': 'gene G1', 'target': 'transcript T1', 'label': 'transcribes_to', 'hop': 1,
        'edge_id': 'gene_transcribes_to_transcript', 'source_data': 'GENCODE'}
    assert edges[('gene G1', 'regulates', 'gene G2')]['evidence'] == ['IDA', 'TAS']   # multi-valued
    assert result['node_count'] == 5 and result['edge_count'] == 5
    assert result['hops'] == [{'hop': 1, 'node_count': 4, 'edge_count': 5, 'truncated': False, 'ranked_by': None}]
    assert sorted((r['label'], r['count']) for r in result['node_count_by_label']) == [('gene', 2), ('transcript', 3)]


def test_programs_leave_no_helper_atoms():
    nb = backend()
    nb.expand(request())
    atoms = evaluate(nb.programs[0], {'human': FACTS, **reverse_spaces()})
    assert {atom[0] for atom in atoms} <= {'seed', 'out', 'np', 'ep', 'deg'}


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
             'where': [{'property': 'weight', 'op': '>=', 'value': 1}]}]
    errors = backend().validate({'seed': {'type': 'gen', 'id': 'x'}, 'hops': hops})
    assert errors[:4] == ["Unknown node type for human: 'gen'",
                          "hops[0]: unknown edge type for human: 'nope'",
                          "hops[0]: unknown node type for human: 'cell'",
                          "hops[0]: unknown edge property for human: 'weight'"]
    assert backend().validate(request()) == []


def test_incoming_edges_come_from_the_reverse_index_with_their_real_direction():
    result = backend().expand(request(hops=[{'direction': 'in', 'limit': 500}]))
    edges = edges_of(result)
    assert set(edges) == {('snp S1', 'closest_gene', 'gene G1'), ('snp S2', 'closest_gene', 'gene G1'),
                          ('gene G2', 'coexpressed_with', 'gene G1')}
    assert edges[('snp S1', 'closest_gene', 'gene G1')]['distance'] == '120'
    assert edges[('snp S1', 'closest_gene', 'gene G1')]['edge_id'] == 'snp_closest_gene_gene'


def test_both_directions_keep_symmetric_edges_as_two_edges():
    edges = edges_of(backend().expand(request(hops=[{'direction': 'both', 'limit': 500}])))
    assert ('gene G1', 'coexpressed_with', 'gene G2') in edges and ('gene G2', 'coexpressed_with', 'gene G1') in edges
    assert ('snp S2', 'closest_gene', 'gene G1') in edges and ('gene G1', 'regulates', 'gene G2') in edges


def test_incoming_respects_edge_and_node_types():
    edges = edges_of(backend().expand(request(hops=[{'direction': 'in', 'limit': 500, 'node_types': ['gene']}])))
    assert set(edges) == {('gene G2', 'coexpressed_with', 'gene G1')}


def test_seed_degree_counts_both_directions():
    result = backend().expand(request())
    assert result['seed_degree'] == [
        {'edge_type': 'transcribes_to', 'neighbour_type': 'transcript', 'direction': 'out', 'count': 3},
        {'edge_type': 'closest_gene', 'neighbour_type': 'snp', 'direction': 'in', 'count': 2},
        {'edge_type': 'coexpressed_with', 'neighbour_type': 'gene', 'direction': 'in', 'count': 1},
        {'edge_type': 'coexpressed_with', 'neighbour_type': 'gene', 'direction': 'out', 'count': 1},
        {'edge_type': 'regulates', 'neighbour_type': 'gene', 'direction': 'out', 'count': 1}]


@pytest.mark.parametrize('status', [VOCABULARY_ONLY, MISSING])
def test_every_request_is_refused_until_the_whole_index_is_built(monkeypatch, status):
    queued = []
    monkeypatch.setattr('app.workers.neighbourhood_task.request_index_build', queued.append)
    nb = backend(vocabulary=VOCABULARY if status == VOCABULARY_ONLY else None, status=status)
    for req in (request(), request(hops=[{'direction': 'in', 'limit': 500}])):
        with pytest.raises(NeighbourhoodUnavailableError, match='being built'):
            nb.validate(req)
        with pytest.raises(NeighbourhoodUnavailableError, match='being built'):
            nb.expand(req)
    assert queued and set(queued) == {'human'}


def test_cancelled_before_a_hop():
    stop = SimpleNamespace(is_set=lambda: True)
    with pytest.raises(TaskCancelledException):
        backend().expand(request(), stop_event=stop)


def ppi(hop, per_node_limit=50):
    return request(seed='P1', seed_type='protein', hops=[{'direction': 'out', 'limit': 500, **hop}],
                   per_node_limit=per_node_limit)


def targets(result):
    return [e[2].split()[1] for e in edges_of(result)]


@pytest.mark.parametrize('op, value, expected', [
    ('>=', 0.8, {'P2', 'P5'}),          # P5: any of its values (0.2, 0.8)
    ('<', 0.3, {'P5'}),
    ('=', 0.4, {'P3'}),
    ('!=', 0.9, {'P3', 'P5'}),          # missing (P4) and non-numeric (P6) never match
])
def test_numeric_where(op, value, expected):
    result = backend().expand(ppi({'where': [{'property': 'score', 'op': op, 'value': value}]}))
    assert set(targets(result)) == expected


@pytest.mark.parametrize('op, value, expected', [
    ('=', 'Inferred from IEA', {'P2'}),  # normalized like the stored values
    ('in', ['TAS', 'IDA'], {'P3'}),
    ('!=', 'TAS', {'P2'}),              # edges without evidence never match
    ('not_in', ['TAS', 'Inferred_from_IEA'], set()),
    ('=', 'x) (y', set()),               # cannot be a stored value
])
def test_string_where(op, value, expected):
    result = backend().expand(ppi({'where': [{'property': 'evidence', 'op': op, 'value': value}]}))
    assert set(targets(result)) == expected


def test_conditions_are_combined_with_and():
    result = backend().expand(ppi({'where': [{'property': 'score', 'op': '>=', 'value': 0.3},
                                             {'property': 'evidence', 'op': '=', 'value': 'TAS'}]}))
    assert targets(result) == ['P3']


def test_order_by_ranks_with_missing_values_last_and_truncates_to_the_best():
    desc = backend().expand(ppi({'order_by': 'score'}))
    assert [e['data']['target'] for e in desc['edges']][:3] == ['protein P2', 'protein P5', 'protein P3']
    assert {e['data']['target'] for e in desc['edges'][3:]} == {'protein P4', 'protein P6'}
    assert desc['hops'][0]['ranked_by'] == 'score'
    top = backend().expand(ppi({'order_by': 'score', 'order': 'asc', 'limit': 2}))
    assert targets(top) == ['P5', 'P3'] and top['truncated'] is True   # P5's best ascending value is 0.2


def test_order_by_with_where_and_per_node_limit_over_two_hops():
    hops = [{'direction': 'out', 'limit': 500, 'edge_types': ['transcribes_to']},
            {'direction': 'out', 'limit': 500, 'order_by': 'score'}]
    result = backend().expand(request(max_hops=2, hops=hops, per_node_limit=1))
    assert [h['edge_count'] for h in result['hops']] == [3, 1]


def test_too_many_candidates_for_a_filtered_hop(monkeypatch):
    from app.error import NeighbourhoodTooLargeError
    monkeypatch.setattr(mod, 'NEIGHBOURHOOD_MAX_CANDIDATES', 3)
    with pytest.raises(NeighbourhoodTooLargeError, match='more than 3 edges'):
        backend().expand(ppi({'order_by': 'score'}))
    assert backend().expand(ppi({}))['edge_count'] == 5   # plain hops are capped per node instead


def test_filtered_programs_leave_no_helper_atoms():
    nb = backend()
    nb.expand(ppi({'where': [{'property': 'score', 'op': '>=', 'value': 0.1},
                             {'property': 'evidence', 'op': 'not_in', 'value': ['x']}], 'order_by': 'score'}))
    atoms = evaluate(nb.programs[0], {'human': FACTS, **reverse_spaces()})
    assert {atom[0] for atom in atoms} <= {'seed', 'out', 'np', 'ep', 'deg', 'rank', 'candidates'}


def test_edges_from_earlier_hops_do_not_use_up_the_per_node_limit():
    # Hop 2 from T1 sees its edge back to G1 again (direction both). With a
    # per-node limit of 1 that edge must not take T1's only slot.
    hops = [{'direction': 'out', 'limit': 500, 'edge_types': ['transcribes_to']},
            {'direction': 'both', 'limit': 500}]
    nb = backend()
    result = nb.expand(request(max_hops=2, hops=hops, per_node_limit=1))
    assert ('transcript T1', 'translates_to', 'protein P1') in edges_of(result)
    assert result['hops'][1] == {'hop': 2, 'node_count': 1, 'edge_count': 1, 'truncated': False, 'ranked_by': None}
    assert '(head 3 (out (transcript T1)' in nb.programs[1]    # 1 + 1 + its one known edge

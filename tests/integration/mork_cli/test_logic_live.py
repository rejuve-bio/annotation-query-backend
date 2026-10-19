"""Human v6 boolean matrix, source facts, complete joins and value tables."""

import copy
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import pytest

pytestmark = [pytest.mark.mork_live, pytest.mark.skipif(
    os.environ.get('MORK_LIVE_TESTS') != '1', reason='set MORK_LIVE_TESTS=1 for native MORK')]

CASES = json.loads(Path(__file__).with_name('cases.json').read_text())


def counts(graph):
    return {'node_count': graph['node_count'], 'edge_count': graph['edge_count'],
            'node_count_by_label': {r['label']: r['count'] for r in graph['node_count_by_label']},
            'edge_count_by_label': {r['label']: r['count'] for r in graph['edge_count_by_label']}}


def source_genes(request, facts):
    from app.lib.mork_values import normalize_mork_value

    def values(name, options):
        options = options if isinstance(options, list) else [options]
        return {normalize_mork_value('chr' + str(v) if name == 'chr' and not str(v).startswith('chr') else v)
                for v in options}

    def prepare(group):
        if 'nodes' in group:
            return {'operator': group['operator'].upper(), 'properties': {
                name: values(name, options) for name, options in group['nodes']['properties'].items()}}
        return {'operator': group['operator'].upper(), 'children': [prepare(child) for child in group['children']]}

    def matches(group, props):
        if 'properties' in group:
            terms = [bool(props.get(name, set()) & options) for name, options in group['properties'].items()]
        else:
            terms = [matches(child, props) for child in group['children']]
        operator = group['operator']
        return all(terms) if operator == 'AND' else any(terms) if operator == 'OR' else not any(terms)

    node = request['nodes'][0]
    own = {name: values(name, value) for name, value in node.get('properties', {}).items()}
    logic = prepare(request['logic']) if request.get('logic') else None
    return {('gene', identifier) for identifier, props in facts.items()
            if (not node.get('id') or node['id'] == identifier)
            and all(props.get(name, set()) & options for name, options in own.items())
            and (logic is None or matches(logic, props))}


@pytest.mark.parametrize('case', CASES, ids=[c['name'] for c in CASES])
def test_logic_matrix(mork_backend, case):
    graph, _ = mork_backend.run(case['request'])
    assert counts(graph) == case['expected']
    nodes = {entry['data']['id']: entry['data'] for entry in graph['nodes']}
    assert len(nodes) == graph['node_count']
    assert dict(Counter(n['type'] for n in nodes.values())) == case['expected']['node_count_by_label']
    edges = {(e['data']['label'], e['data']['source'], e['data']['target']) for e in graph['edges']}
    assert len(edges) == graph['edge_count']
    assert dict(Counter(e[0] for e in edges)) == case['expected']['edge_count_by_label']


GENE_CASES = [c for c in CASES if len(c['request']['nodes']) == 1 and c['request']['nodes'][0]['type'] == 'gene']


@pytest.mark.parametrize('case', GENE_CASES, ids=[c['name'] for c in GENE_CASES])
def test_gene_logic_matches_source_facts(mork_backend, gene_facts, case):
    _, topology = mork_backend.run(case['request'])
    assert topology == source_genes(case['request'], gene_facts)


@pytest.mark.parametrize('operator, case_name, prop, real_values', [
    ('OR', 'S01_name_TP53_or_BRCA1', 'gene_name', ['TP53', 'BRCA1']),
    ('NOT', 'S02_chr21_not_lncRNA', 'gene_type', ['lncRNA']),
])
def test_hundred_values_match_source_facts(mork_backend, gene_facts, operator, case_name, prop, real_values):
    request = copy.deepcopy(next(c['request'] for c in CASES if c['name'] == case_name))
    request['logic'] = {'operator': operator, 'nodes': {'node_id': 'n0', 'properties': {
        prop: real_values + [f'NO_SUCH_VALUE_{i}' for i in range(100 - len(real_values))]}}}
    graph, topology = mork_backend.run(request)
    expected = source_genes(request, gene_facts)
    assert topology == expected
    assert graph['node_count'] == len(expected)
    assert '(join_' in mork_backend.calls[-1]['program'].split('(exec ', 1)[0]


def test_double_not_matches_source_facts(mork_backend, gene_facts):
    request = copy.deepcopy(next(c['request'] for c in CASES if c['name'] == 'S02_chr21_not_lncRNA'))
    request['logic'] = {'operator': 'NOT', 'children': [request['logic']]}
    graph, topology = mork_backend.run(request)
    assert topology == source_genes(request, gene_facts)
    assert graph['node_count'] == 591


@pytest.mark.parametrize('properties', [{'gene_name': 'TP53'}, {'chr': 'chr21'}], ids=['TP53', 'chr21'])
def test_chain_contains_only_complete_source_matches(mork_backend, gene_facts, properties):
    paths = [mork_backend.source_dir / 'gencode/gene/edges_gene_transcribes_to_transcript.metta',
             mork_backend.source_dir / 'uniprot/edges_transcript_translates_to_protein.metta']
    if not all(path.is_file() for path in paths):
        pytest.skip('gene/transcript/protein source edges are missing')
    request = copy.deepcopy(next(c['request'] for c in CASES if c['name'] == 'S10c_nolog_chain_TP53'))
    request['nodes'][0]['properties'] = properties
    candidates = {identifier for _, identifier in source_genes({'nodes': [request['nodes'][0]]}, gene_facts)}
    transcripts = defaultdict(set)
    transcribed = re.compile(r'^\(transcribes_to \(gene (\S+)\) \(transcript (\S+)\)\)\s*$')
    for line in paths[0].open():
        match = transcribed.match(line)
        if match and match[1] in candidates:
            transcripts[match[2]].add(match[1])
    expected = set()
    translated = re.compile(r'^\(translates_to \(transcript (\S+)\) \(protein (\S+)\)\)\s*$')
    for line in paths[1].open():
        match = translated.match(line)
        if match and match[1] in transcripts:
            transcript, protein = match.groups()
            expected.add(('translates_to', ('transcript', transcript), ('protein', protein)))
            expected.update(('transcribes_to', ('gene', gene), ('transcript', transcript))
                            for gene in transcripts[transcript])
    graph, topology = mork_backend.run(request)
    assert topology == expected
    assert graph['edge_count'] == len(expected)
    independent = mork_backend.raw([
        f'(ACT {mork_backend.space} ({name} (gene $g) {value}))' for name, value in properties.items()
    ] + [f'(ACT {mork_backend.space} (transcribes_to (gene $g) (transcript $t)))',
         f'(ACT {mork_backend.space} (translates_to (transcript $t) (protein $p)))'], [
        '(reference (transcribes_to (gene $g) (transcript $t)))',
        '(reference (translates_to (transcript $t) (protein $p)))'])
    assert topology == independent


@pytest.mark.parametrize('name', ['S07_pc21_BP_or_MF', 'S10_nolog_two_predicates_join', 'S02_chr21_not_lncRNA'])
def test_limit_keeps_complete_matches_for_limited_roots_and_full_counts(mork_backend, name):
    case = next(c for c in CASES if c['name'] == name)
    full, full_topology = mork_backend.run(case['request'])
    graph, topology = mork_backend.run(case['request'], limit=5)
    # Counts describe every match, as on Cypher; only the graph is limited.
    assert counts(graph) == counts(full) == case['expected']
    assert topology <= full_topology
    roots = {term for atom in topology for term in (atom[1:] if len(atom) == 3 else [atom])
             if term[0] == 'gene'}
    assert len(roots) == 5
    # Each kept gene keeps all of its complete matches.
    assert topology == {atom for atom in full_topology
                        if any(term in roots for term in (atom[1:] if len(atom) == 3 else [atom]))}

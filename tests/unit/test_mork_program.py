"""Staged MORK joins, evaluated against small in-memory fact sets."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.lib.logic import LogicValidationError
from app.services import mork_cli_generator as mod
from app.services.mork_program import MorkJoinCompiler
from app.services.mork_output import parse_mork_counts, parse_mork_output


def node(nid, typ, properties=None, identifier=''):
    return {'node_id': nid, 'type': typ, 'properties': properties or {}, 'id': identifier}


def predicate(source, target, typ, pid='p0'):
    return {'predicate_id': pid, 'source': source, 'target': target, 'type': typ}


def request(properties=None):
    return {'nodes': [node('n0', 'gene', properties or {'gene_name': 'TP53'}),
                      node('n1', 'transcript'), node('n2', 'protein')],
            'predicates': [predicate('n0', 'n1', 'transcribes to'),
                           predicate('n1', 'n2', 'translates to', 'p1')]}


def sexprs(text):
    return parse_mork_output(text)


def match(pattern, fact, bindings):
    if isinstance(pattern, str) and pattern.startswith('$'):
        if pattern in bindings:
            return bindings if bindings[pattern] == fact else None
        return {**bindings, pattern: fact}
    if isinstance(pattern, tuple) and isinstance(fact, tuple) and len(pattern) == len(fact):
        for left, right in zip(pattern, fact):
            bindings = match(left, right, bindings)
            if bindings is None:
                break
        return bindings
    return bindings if pattern == fact else None


def substitute(pattern, bindings):
    if isinstance(pattern, tuple):
        return tuple(substitute(child, bindings) for child in pattern)
    return bindings.get(pattern, pattern)


def evaluate(program, facts):
    """Interpret the ACT/BTM join and write/delete subset used by these programs."""
    stored = set(sexprs(facts))
    memory = set()
    for rule in sexprs(program):
        if rule[0] != 'exec':
            memory.add(rule)
            continue
        _, _, sources, sink = rule
        snapshot = set(memory)
        rows = [{}]
        for source in sources[1:]:
            pool, pattern = (stored, source[2]) if source[0] == 'ACT' else (snapshot, source[1])
            joined = []
            for row in rows:
                for fact in pool:
                    bound = match(pattern, fact, row)
                    if bound is not None:
                        joined.append(bound)
            rows = joined
        if sink[0] == 'O' and sink[1][0] == 'head':
            _, limit, template = sink[1]
            memory.update(sorted({substitute(template, row) for row in rows})[:int(limit)])
            continue
        if sink[0] == 'O' and sink[1][0] == 'count':
            for _, template, count_var, projection in sink[1:]:
                values = {substitute(projection, row) for row in rows}
                if values:
                    memory.add(substitute(template, {count_var: str(len(values))}))
            continue
        for row in rows:
            if sink[0] == ',':
                memory.update(substitute(out, row) for out in sink[1:])
            else:
                assert sink[0] == 'O' and sink[1][0] == '-'
                memory.discard(substitute(sink[1][1], row))
    return memory


def compile_request(req):
    gen = mod.MorkCLIQueryGenerator.__new__(mod.MorkCLIQueryGenerator)
    return MorkJoinCompiler(req, 'human', 'result', gen._safe_atom).compile()


def results(*edges):
    return {('result', sexprs(edge)[0]) for edge in edges}


CHAIN = '''
(gene_name (gene G1) TP53)
(transcribes_to (gene G1) (transcript T1))
(transcribes_to (gene G1) (transcript T2))
(transcribes_to (gene G2) (transcript T3))
(translates_to (transcript T1) (protein P1))
(translates_to (transcript T3) (protein P3))
'''


def test_chain_removes_dangling_upstream_edges_and_helpers():
    assert evaluate(compile_request(request()), CHAIN) == results(
        '(transcribes_to (gene G1) (transcript T1))',
        '(translates_to (transcript T1) (protein P1))',
    )


def test_failed_downstream_filter_returns_no_partial_graph():
    req = request()
    req['nodes'][2]['properties'] = {'protein_name': 'missing'}
    assert evaluate(compile_request(req), CHAIN) == set()


def test_branch_failure_removes_edges_on_other_branch():
    req = request({'gene_type': 'coding'})
    req['predicates'][1] = predicate('n0', 'n2', 'has protein', 'p1')
    facts = '''
    (gene_type (gene G1) coding) (gene_type (gene G2) coding)
    (transcribes_to (gene G1) (transcript T1))
    (transcribes_to (gene G2) (transcript T2))
    (has_protein (gene G2) (protein P2))
    '''
    assert evaluate(compile_request(req), facts) == results(
        '(transcribes_to (gene G2) (transcript T2))',
        '(has_protein (gene G2) (protein P2))',
    )


def test_filters_on_multiple_nodes_are_all_required():
    req = request()
    req['nodes'][1]['properties'] = {'kind': 'wanted'}
    assert evaluate(compile_request(req), CHAIN + '(kind (transcript T2) wanted)') == set()


def test_concrete_id_and_properties_are_both_required():
    req = request()
    req['nodes'][0]['id'] = 'G2'
    assert evaluate(compile_request(req), CHAIN + '(gene G2)') == set()
    req['nodes'][0]['properties'] = {}
    assert evaluate(compile_request(req), CHAIN + '(gene G2)') == results(
        '(transcribes_to (gene G2) (transcript T3))',
        '(translates_to (transcript T3) (protein P3))',
    )


def test_reverse_traversal_scans_act_before_target_membership():
    req = request()
    req['nodes'][0]['properties'] = {}
    req['nodes'][2]['properties'] = {'protein_name': 'wanted'}
    program = compile_request(req)
    assert evaluate(program, CHAIN + '(protein_name (protein P1) wanted)') == results(
        '(transcribes_to (gene G1) (transcript T1))',
        '(translates_to (transcript T1) (protein P1))',
    )
    expansions = [rule for rule in sexprs(program)
                  if any(src[0] == 'ACT' and src[2][0] in ('transcribes_to', 'translates_to')
                         for src in rule[2][1:])]
    assert len(expansions) == 2
    assert all(rule[2][1][0] == 'ACT' for rule in expansions)


def test_stage_locations_are_strictly_increasing_and_cleanup_is_last():
    rules = sexprs(compile_request(request()))
    assert [int(rule[1]) for rule in rules] == list(range(1, len(rules) + 1))
    first_delete = next(i for i, rule in enumerate(rules) if rule[3][0] == 'O')
    assert all(rule[3][0] == 'O' for rule in rules[first_delete:])


PROPERTY_SCHEMA = {
    'nodes': {
        'gene': {'properties': {'gene_name': {}, 'chr': {}, 'synonym': {}, 'synonyms': {}, 'accessions': {}}},
        'transcript': {'properties': {'transcript_name': {}, 'biological_context': {}}},
        'protein': {'properties': {}},
    },
    'edges': {'transcribes_to': {'properties': {'score': {}, 'source': {}}}},
}


def test_properties_are_restricted_to_final_nodes_and_edges():
    gen = mod.MorkCLIQueryGenerator.__new__(mod.MorkCLIQueryGenerator)
    program = MorkJoinCompiler(request(), 'human', 'result', gen._safe_atom).compile(
        properties=True, schema=PROPERTY_SCHEMA)
    facts = CHAIN + '''
    (chr (gene G1) chr17) (chr (gene G2) chr1)
    (synonym (gene G1) alias) (synonyms (gene G1) aliases) (accessions (gene G1) accession)
    (transcript_name (transcript T1) wanted) (transcript_name (transcript T2) dangling)
    (biological_context (transcript T1) (anatomy UBERON_1))
    (score (transcribes_to (gene G1) (transcript T1)) 0.5)
    (score (transcribes_to (gene G1) (transcript T2)) 0.8)
    (source (transcribes_to (gene G1) (transcript T1)) evidence)
    '''
    atoms = evaluate(program, facts)
    props = {atom for atom in atoms if atom[0] == 'tmp'}
    assert props == set(sexprs('''
    (tmp (node gene_name (gene G1) TP53))
    (tmp (node chr (gene G1) chr17))
    (tmp (node transcript_name (transcript T1) wanted))
    (tmp (node biological_context (transcript T1) (anatomy UBERON_1)))
    (tmp (edge score (transcribes_to (gene G1) (transcript T1)) 0.5))
    (tmp (edge source (transcribes_to (gene G1) (transcript T1)) evidence))
    '''))
    assert all(atom[0] in ('result', 'tmp') for atom in atoms)
    assert '($property ' not in program


def test_single_node_queries_fetch_properties_in_the_same_program():
    req = {'nodes': [node('n0', 'gene', {'gene_name': 'TP53'})], 'predicates': []}
    gen = mod.MorkCLIQueryGenerator.__new__(mod.MorkCLIQueryGenerator)
    program = MorkJoinCompiler(req, 'human', 'result', gen._safe_atom).compile(
        properties=True, schema=PROPERTY_SCHEMA)
    assert evaluate(program, CHAIN + '(chr (gene G1) chr17)') == set(sexprs('''
    (result (gene G1))
    (tmp (node gene_name (gene G1) TP53))
    (tmp (node chr (gene G1) chr17))
    '''))


def test_count_sinks_include_edge_endpoints_without_properties():
    gen = mod.MorkCLIQueryGenerator.__new__(mod.MorkCLIQueryGenerator)
    program = MorkJoinCompiler(request(), 'human', 'result', gen._safe_atom).compile(counts=True)
    atoms = evaluate(program, CHAIN)
    counts = parse_mork_counts([atoms])
    assert (counts['node_count'], counts['edge_count']) == (3, 2)
    assert {row['label']: row['count'] for row in counts['node_count_by_label']} == {
        'gene': 1, 'protein': 1, 'transcript': 1,
    }
    assert {row['label']: row['count'] for row in counts['edge_count_by_label']} == {
        'transcribes_to': 1, 'translates_to': 1,
    }


def test_counts_deduplicate_same_type_nodes_and_repeated_edge_roles():
    req = {'nodes': [node('n0', 'gene', {'gene_name': 'A'}), node('n1', 'gene'), node('n2', 'gene')],
           'predicates': [predicate('n0', 'n1', 'links'), predicate('n1', 'n2', 'links', 'p1')]}
    facts = '''
    (gene_name (gene G1) A)
    (links (gene G1) (gene G1)) (links (gene G1) (gene G2))
    (links (gene G2) (gene G1))
    '''
    gen = mod.MorkCLIQueryGenerator.__new__(mod.MorkCLIQueryGenerator)
    program = MorkJoinCompiler(req, 'human', 'result', gen._safe_atom).compile(counts=True)
    counts = parse_mork_counts([evaluate(program, facts)])
    assert counts == {'node_count': 2, 'edge_count': 3,
                      'node_count_by_label': [{'label': 'gene', 'count': 2}],
                      'edge_count_by_label': [{'label': 'links', 'count': 3}]}


def test_count_sinks_write_nothing_for_empty_matches():
    req = request({'gene_name': 'missing'})
    gen = mod.MorkCLIQueryGenerator.__new__(mod.MorkCLIQueryGenerator)
    program = MorkJoinCompiler(req, 'human', 'result', gen._safe_atom).compile(counts=True)
    assert evaluate(program, CHAIN) == set()


def test_predicate_ids_do_not_collapse_distinct_constraints():
    req = request()
    req['predicates'][1]['predicate_id'] = 'p0'
    assert evaluate(compile_request(req), CHAIN) == results(
        '(transcribes_to (gene G1) (transcript T1))',
        '(translates_to (transcript T1) (protein P1))',
    )


def test_nodes_with_the_same_type_keep_separate_bindings():
    req = {'nodes': [node('n0', 'gene', {'gene_name': 'A'}),
                     node('n1', 'gene'), node('n2', 'gene')],
           'predicates': [predicate('n0', 'n1', 'first'), predicate('n1', 'n2', 'second', 'p1')]}
    facts = '''
    (gene_name (gene G1) A)
    (first (gene G1) (gene G2)) (first (gene G1) (gene G4))
    (second (gene G2) (gene G3))
    '''
    assert evaluate(compile_request(req), facts) == results(
        '(first (gene G1) (gene G2))', '(second (gene G2) (gene G3))',
    )


def test_empty_name_filter_does_not_override_a_positive_filter():
    req = request({'gene_name': ''})
    req['nodes'][2]['properties'] = {'kind': 'wanted'}
    program = compile_request(req)
    assert sexprs(program)[0][2][1][2] == ('kind', ('protein', '$x'), 'wanted')
    assert evaluate(program, CHAIN + '(kind (protein P1) wanted)') == results(
        '(transcribes_to (gene G1) (transcript T1))',
        '(translates_to (transcript T1) (protein P1))',
    )


@pytest.mark.parametrize('shape', ['cycle', 'parallel', 'disconnected'])
def test_non_tree_requests_are_rejected(shape):
    req = request()
    if shape == 'cycle':
        req['predicates'].append(predicate('n2', 'n0', 'links', 'p2'))
    elif shape == 'parallel':
        req['predicates'].append(predicate('n0', 'n1', 'links', 'p2'))
    else:
        req['nodes'].append(node('n3', 'gene'))
    with pytest.raises(LogicValidationError, match='not supported yet'):
        compile_request(req)


@pytest.mark.parametrize('kind', ['position', 'comma', 'edge'])
def test_unsupported_filters_are_rejected(kind):
    req = request()
    if kind == 'position':
        req['nodes'][0]['properties'] = {'start': 123}
    elif kind == 'comma':
        req['nodes'][0]['properties'] = {'gene_name': 'TP53,BRCA1'}
    else:
        req['predicates'][0]['properties'] = {'score': 1}
    with pytest.raises(LogicValidationError, match='not supported yet'):
        compile_request(req)


@pytest.mark.parametrize('result_id', ['deadbeef', '00123456', '1e080001'])
def test_queries_survive_json_transport_and_execute_once_total(tmp_path, monkeypatch, result_id):
    gen = mod.MorkCLIQueryGenerator(tmp_path)
    monkeypatch.setattr(gen, 'generate_id', lambda: result_id)
    (tmp_path / gen.act_filename).touch()
    monkeypatch.setattr(mod, 'Path', lambda path: tmp_path if path == '/dev/shm' else Path(path))
    programs = []

    def execute(path):
        programs.append(Path(path).read_text())
        return SimpleNamespace(stdout='result:\n')

    monkeypatch.setattr(mod, '_get_session', lambda _: SimpleNamespace(exec_query=execute))
    monkeypatch.setattr(gen, '_run_single_pattern', lambda *args: pytest.fail('per-binding process'))
    req = request()
    original = copy.deepcopy(req)
    queries = gen.query_Generator(req, {n['node_id']: n for n in req['nodes']})
    for query in json.loads(json.dumps(queries)):
        gen.run_query(query)
    assert len(programs) == 1
    assert req == original
    for program, query in zip(programs, queries):
        assert query[3] in program
        atoms = evaluate(program, CHAIN)
        assert all(atom[0] in (query[3], f'{query[3]}_cnt', 'tmp') for atom in atoms)
        assert {atom[1] for atom in atoms if atom[0] == query[3]} == {
            sexprs('(transcribes_to (gene G1) (transcript T1))')[0],
            sexprs('(translates_to (transcript T1) (protein P1))')[0],
        }

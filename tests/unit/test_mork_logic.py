"""Boolean candidate sets and relationship constraints in staged MORK programs."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.lib.logic import LogicValidationError, QueryTooBroadError
from app.services import mork_cli_generator as mod
from app.services.mork_output import parse_mork_counts
from app.services.mork_program import MorkJoinCompiler
from test_mork_program import CHAIN, evaluate, node, predicate, request, results, sexprs


def group(operator, properties, nid='n0'):
    return {'operator': operator, 'nodes': {'node_id': nid, 'properties': properties}}


def root(*groups):
    return {'operator': 'AND', 'children': list(groups)}


def compile_request(req, counts=False):
    gen = mod.MorkCLIQueryGenerator.__new__(mod.MorkCLIQueryGenerator)
    return MorkJoinCompiler(req, 'human', 'result', gen._safe_atom).compile(counts=counts)


def single(properties=None, logic=None):
    req = {'nodes': [node('n0', 'gene', properties)], 'predicates': []}
    if logic is not None:
        req['logic'] = logic
    return req


FACTS = '''
(gene G1) (gene G2) (gene G3) (gene G4)
(chr (gene G1) chr21) (chr (gene G2) chr21) (chr (gene G3) chr21) (chr (gene G4) chr1)
(gene_name (gene G1) APP) (gene_name (gene G2) OTHER)
(gene_type (gene G1) coding) (gene_type (gene G2) lncRNA) (gene_type (gene G4) coding)
(transcribes_to (gene G1) (transcript T1))
(transcribes_to (gene G2) (transcript T2))
(transcribes_to (gene G3) (transcript T3))
'''


def test_property_not_means_none_match_and_preserves_missing_properties():
    req = single({'chr': 'chr21'}, group('NOT', {'gene_name': 'APP', 'gene_type': 'lncRNA'}))
    assert evaluate(compile_request(req), FACTS) == results('(gene G3)')


def test_same_property_values_are_unioned_and_case_is_exact():
    req = single(logic=group('or', {'gene_name': ['APP', 'OTHER', 'APP', 'app']}))
    assert evaluate(compile_request(req), FACTS) == results('(gene G1)', '(gene G2)')


def test_nested_and_or_not_uses_the_restricted_universe():
    req = single({'chr': 'chr21'}, root({'operator': 'OR', 'children': [
        group('AND', {'gene_type': 'coding'}), group('NOT', {'gene_type': 'lncRNA'})]}))
    assert evaluate(compile_request(req), FACTS) == results('(gene G1)', '(gene G3)')


def test_double_not_preserves_only_matching_candidates():
    req = single({'chr': 'chr21'}, root({'operator': 'NOT', 'children': [group('NOT', {'gene_type': 'lncRNA'})]}))
    assert evaluate(compile_request(req), FACTS) == results('(gene G2)')


def test_positive_groups_run_before_not_even_when_not_is_listed_first():
    req = single(logic=root(group('NOT', {'gene_type': 'lncRNA'}), group('AND', {'chr': '21'})))
    assert evaluate(compile_request(req), FACTS) == results('(gene G1)', '(gene G3)')


def test_many_values_use_one_act_first_table_and_remove_all_helpers():
    req = single(logic=group('OR', {'gene_name': ['APP', 'OTHER'] + [f'x{i}' for i in range(10)]}))
    program = compile_request(req)
    assert evaluate(program, FACTS) == results('(gene G1)', '(gene G2)')
    lookups = [rule for rule in sexprs(program) if rule[0] == 'exec' and
               any(src[0] == 'ACT' for src in rule[2][1:])]
    assert len(lookups) == 1 and lookups[0][2][1][0] == 'ACT'


def test_many_negated_values_use_the_table_without_losing_missing_values():
    req = single({'chr': 'chr21'}, group('NOT', {'gene_name': ['APP'] + [f'x{i}' for i in range(10)]}))
    assert evaluate(compile_request(req), FACTS) == results('(gene G2)', '(gene G3)')


def test_non_root_not_reduces_upstream_and_sibling_edges():
    req = request()
    req['logic'] = group('NOT', {'kind': 'excluded'}, 'n1')
    facts = CHAIN + '(kind (transcript T1) excluded)'
    assert evaluate(compile_request(req), facts) == set()


def not_edge_request(reverse=False, far_props=None, far_logic=None):
    nodes = [node('n0', 'gene', {'chr': 'chr21'}), node('n1', 'term', far_props)]
    pred = predicate('n1', 'n0', 'linked') if reverse else predicate('n0', 'n1', 'linked')
    groups = [{'operator': 'NOT', 'predicates': ['p0']}]
    if far_logic:
        groups.append(far_logic)
    predicates = [pred]
    if reverse:
        nodes.append(node('n2', 'transcript'))
        predicates.append(predicate('n0', 'n2', 'transcribes to', 'p1'))
    return {'nodes': nodes, 'predicates': predicates, 'logic': root(*groups)}


def kept_results(reverse, *identifiers):
    return results(*(f'(transcribes_to (gene G{i}) (transcript T{i}))' if reverse else f'(gene G{i})'
                     for i in identifiers))


@pytest.mark.parametrize('reverse', [False, True])
def test_negated_predicates_filter_far_nodes_and_do_not_return_or_count_them(reverse):
    req = not_edge_request(reverse, {'name': 'wanted'})
    edge = '(linked (term T1) (gene G1)) (linked (term T2) (gene G2))' if reverse else \
           '(linked (gene G1) (term T1)) (linked (gene G2) (term T2))'
    atoms = evaluate(compile_request(req, counts=True), FACTS + edge + '(name (term T1) wanted)')
    assert {a for a in atoms if a[0] == 'result'} == kept_results(reverse, 2, 3)
    counts = parse_mork_counts([atoms])
    assert counts['node_count'] == (4 if reverse else 2)
    assert counts['edge_count'] == (2 if reverse else 0)
    assert {row['label'] for row in counts['node_count_by_label']} == ({'gene', 'transcript'} if reverse else {'gene'})
    assert all(row['label'] != 'linked' for row in counts['edge_count_by_label'])
    deletions = [r for r in sexprs(compile_request(req)) if r[3][0] == 'O' and
                 any(s[0] == 'ACT' and s[2][0] == 'linked' for s in r[2][1:])]
    assert len(deletions) == 1
    assert deletions[0][2][1][0] == ('ACT' if reverse else 'BTM')


@pytest.mark.parametrize('reverse', [False, True])
def test_negated_far_node_with_only_not_uses_reachable_candidates(reverse):
    req = not_edge_request(reverse, far_logic=group('NOT', {'kind': 'allowed'}, 'n1'))
    edge = '(linked (term T1) (gene G1)) (linked (term T2) (gene G2))' if reverse else \
           '(linked (gene G1) (term T1)) (linked (gene G2) (term T2))'
    assert evaluate(compile_request(req), FACTS + edge + '(kind (term T1) allowed)') == kept_results(reverse, 1, 3)


def or_request():
    return {'nodes': [node('n0', 'gene', {'chr': 'chr21'}), node('n1', 'term'), node('n2', 'protein')],
            'predicates': [predicate('n0', 'n1', 'first'), predicate('n0', 'n2', 'second', 'p1')],
            'logic': root({'operator': 'OR', 'predicates': ['p0', 'p1']})}


OR_FACTS = FACTS + '''
(first (gene G1) (term T1)) (second (gene G2) (protein P2))
(first (gene G4) (term T4))
'''


def test_predicate_or_keeps_whichever_arms_exist_without_requiring_both():
    assert evaluate(compile_request(or_request()), OR_FACTS) == results(
        '(first (gene G1) (term T1))', '(second (gene G2) (protein P2))')


def test_predicate_or_applies_far_node_filters_and_counts_only_existing_arms():
    req = or_request()
    req['nodes'][1]['properties'] = {'name': 'missing'}
    atoms = evaluate(compile_request(req, counts=True), OR_FACTS)
    assert {a for a in atoms if a[0] == 'result'} == results('(second (gene G2) (protein P2))')
    assert parse_mork_counts([atoms])['node_count'] == 2


def test_predicate_or_and_required_branch_remove_partial_matches():
    req = or_request()
    req['nodes'].append(node('n3', 'transcript'))
    req['predicates'].append(predicate('n0', 'n3', 'third', 'p2'))
    assert evaluate(compile_request(req), OR_FACTS + '(third (gene G2) (transcript T2))') == results(
        '(second (gene G2) (protein P2))', '(third (gene G2) (transcript T2))')


def test_each_or_group_is_required_independently():
    req = or_request()
    req['nodes'] += [node('n3', 'pathway'), node('n4', 'function')]
    req['predicates'] += [predicate('n0', 'n3', 'third', 'p2'), predicate('n0', 'n4', 'fourth', 'p3')]
    req['logic']['children'].append({'operator': 'OR', 'predicates': ['p2', 'p3']})
    assert evaluate(compile_request(req), OR_FACTS + '(fourth (gene G2) (function F2))') == results(
        '(second (gene G2) (protein P2))', '(fourth (gene G2) (function F2))')


def test_or_kept_node_can_be_reached_from_a_filtered_required_branch():
    req = or_request()
    req['nodes'][0]['properties'] = {}
    req['nodes'].append(node('n3', 'transcript', {'name': 'wanted'}))
    req['predicates'].append(predicate('n0', 'n3', 'third', 'p2'))
    facts = OR_FACTS + '(name (transcript T2) wanted) (third (gene G2) (transcript T2))'
    assert evaluate(compile_request(req), facts) == results(
        '(second (gene G2) (protein P2))', '(third (gene G2) (transcript T2))')


def test_or_far_filter_does_not_require_that_arm_to_exist():
    req = or_request()
    req['nodes'][0]['properties'] = {}
    req['nodes'][1]['properties'] = {'name': 'wanted'}
    assert evaluate(compile_request(req), OR_FACTS + '(name (term T1) wanted)') == results(
        '(first (gene G1) (term T1))', '(second (gene G2) (protein P2))')


def test_predicate_or_combines_with_not_without_returning_the_negated_end():
    req = or_request()
    req['nodes'].append(node('n3', 'pathway'))
    req['predicates'].append(predicate('n0', 'n3', 'excluded', 'p2'))
    req['logic']['children'].append({'operator': 'NOT', 'predicates': ['p2']})
    atoms = evaluate(compile_request(req, counts=True), OR_FACTS + '(excluded (gene G2) (pathway X))')
    assert {a for a in atoms if a[0] == 'result'} == results('(first (gene G1) (term T1))')
    assert parse_mork_counts([atoms]) == {
        'node_count': 2, 'edge_count': 1,
        'node_count_by_label': [{'label': 'gene', 'count': 1}, {'label': 'term', 'count': 1}],
        'edge_count_by_label': [{'label': 'first', 'count': 1}],
    }


def test_predicate_or_supports_arms_in_opposite_directions():
    req = or_request()
    req['predicates'][0] = predicate('n1', 'n0', 'first')
    facts = FACTS + '(first (term T1) (gene G1)) (second (gene G2) (protein P2))'
    assert evaluate(compile_request(req), facts) == results(
        '(first (term T1) (gene G1))', '(second (gene G2) (protein P2))')


def test_non_root_not_filters_only_its_own_or_arm():
    req = or_request()
    req['logic']['children'].append(group('NOT', {'kind': 'excluded'}, 'n1'))
    assert evaluate(compile_request(req), OR_FACTS + '(kind (term T1) excluded)') == results(
        '(second (gene G2) (protein P2))')


@pytest.mark.parametrize('req', [single(), single(logic=group('NOT', {'gene_type': 'coding'})),
                              single(logic={'operator': 'OR', 'children': [
                                  group('AND', {'gene_type': 'coding'}), group('NOT', {'name': 'x'})]})])
def test_shared_positive_filter_guard_rejects_broad_requests(req, monkeypatch):
    monkeypatch.setattr(settings, 'REQUIRE_POSITIVE_FILTER', True)
    with pytest.raises(QueryTooBroadError, match='too broad'):
        compile_request(req)


def test_logic_compilation_does_not_mutate_or_keep_request_state():
    req = single(logic=group('OR', {'gene_name': ['APP', 'OTHER']}))
    original = copy.deepcopy(req)
    assert evaluate(compile_request(req), FACTS) == results('(gene G1)', '(gene G2)')
    assert req == original
    assert evaluate(compile_request(single({'gene_name': 'APP'})), FACTS) == results('(gene G1)')


@pytest.mark.parametrize('logic, message', [
    (group('XOR', {'name': 'x'}), 'invalid operator'),
    (group('NOT', {}), 'NOT on the whole node'),
    (group('OR', {'start': '1'}), 'position filter'),
    (group('OR', {'name': 'x,y'}), 'comma-separated'),
    (group('AND', {'name': 'x,y', 'kind': 'wanted'}), 'comma-separated'),
    ({'operator': 'NOT', 'predicates': ['missing']}, 'unknown predicate'),
])
def test_unsupported_logic_returns_validation_errors(logic, message):
    with pytest.raises(LogicValidationError, match=message):
        compile_request(single({'chr': 'chr21'}, logic))


def test_generator_opts_in_and_maps_bad_values_to_http_validation_errors(tmp_path, monkeypatch):
    gen = mod.MorkCLIQueryGenerator(tmp_path)
    assert gen.supports_logic
    monkeypatch.setattr(mod, '_get_property_schema', lambda: {})
    req = single(logic=group('OR', {'name': ['https://example.org/(exec)']}))
    with pytest.raises(LogicValidationError, match='Invalid MORK property value'):
        gen.query_Generator(req, {'n0': req['nodes'][0]})


def test_or_groups_on_different_kept_nodes_are_rejected():
    req = or_request()
    req['nodes'] += [node('n3', 'anchor'), node('n4', 'pathway'), node('n5', 'function')]
    req['predicates'] += [predicate('n0', 'n3', 'connects', 'p2'),
                          predicate('n3', 'n4', 'third', 'p3'), predicate('n3', 'n5', 'fourth', 'p4')]
    req['logic']['children'].append({'operator': 'OR', 'predicates': ['p3', 'p4']})
    with pytest.raises(LogicValidationError, match='OR groups on different nodes'):
        compile_request(req)


def compile_limited(req, limit):
    gen = mod.MorkCLIQueryGenerator.__new__(mod.MorkCLIQueryGenerator)
    return MorkJoinCompiler(req, 'human', 'result', gen._safe_atom).compile(counts=True, limit=limit)


def test_limit_keeps_complete_matches_of_limited_roots_and_full_counts():
    atoms = evaluate(compile_limited(or_request(), 1), OR_FACTS)
    # One root gene with all of its matches; counts still cover both genes.
    assert {a for a in atoms if a[0] == 'result'} == results('(first (gene G1) (term T1))')
    assert parse_mork_counts([atoms]) == {
        'node_count': 4, 'edge_count': 2,
        'node_count_by_label': [{'label': 'gene', 'count': 2}, {'label': 'protein', 'count': 1},
                                {'label': 'term', 'count': 1}],
        'edge_count_by_label': [{'label': 'first', 'count': 1}, {'label': 'second', 'count': 1}],
    }
    assert all(a[0] in ('result', 'result_cnt') for a in atoms)


def test_limit_on_node_only_requests_and_no_limit_by_default():
    req = single({'chr': 'chr21'})
    limited = evaluate(compile_limited(req, 2), FACTS)
    assert {a for a in limited if a[0] == 'result'} == results('(gene G1)', '(gene G2)')
    assert parse_mork_counts([limited])['node_count'] == 3
    for no_limit in (None, 0):
        assert {a for a in evaluate(compile_limited(req, no_limit), FACTS) if a[0] == 'result'} == results(
            '(gene G1)', '(gene G2)', '(gene G3)')


def test_limit_larger_than_the_result_returns_everything():
    assert {a for a in evaluate(compile_limited(or_request(), 50), OR_FACTS) if a[0] == 'result'} == results(
        '(first (gene G1) (term T1))', '(second (gene G2) (protein P2))')


@pytest.mark.parametrize('limit', [-1, 1.5, '10', True])
def test_invalid_limits_are_rejected(limit):
    with pytest.raises(LogicValidationError, match='limit'):
        compile_limited(single({'chr': 'chr21'}), limit)


def test_value_tables_are_executed_as_a_program_after_json_transport(tmp_path, monkeypatch):
    gen = mod.MorkCLIQueryGenerator(tmp_path)
    (tmp_path / gen.act_filename).touch()
    monkeypatch.setattr(mod, '_get_property_schema', lambda: {})
    monkeypatch.setattr(mod, 'Path', lambda path: tmp_path if path == '/dev/shm' else Path(path))
    req = single(logic=group('OR', {'gene_name': ['APP'] + [f'name{i}' for i in range(99)]}))
    queries = gen.query_Generator(req, {'n0': req['nodes'][0]})
    expected = queries[0][0][0]
    assert expected.startswith('(join_')
    executed = []

    def execute(path):
        executed.append(Path(path).read_text())
        return SimpleNamespace(stdout='result:\n')

    monkeypatch.setattr(mod, '_get_session', lambda _: SimpleNamespace(exec_query=execute))
    for query in json.loads(json.dumps(queries)):
        gen.run_query(query)
    assert executed == [expected]

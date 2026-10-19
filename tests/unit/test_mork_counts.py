"""Count sinks, synchronous count reuse, and asynchronous task reuse."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.constants import TaskStatus
from app.services import mork_cli_generator as mod
from app.services.mork_output import parse_mork_counts, parse_mork_output


COUNTS = '''
(q_cnt total node 3) (q_cnt total edge 2)
(q_cnt node gene 1) (q_cnt node transcript 1) (q_cnt node protein 1)
(q_cnt edge transcribes_to 1) (q_cnt edge translates_to 1)
'''
EXPECTED = {'node_count': 3, 'edge_count': 2,
            'node_count_by_label': [{'label': 'gene', 'count': 1}, {'label': 'protein', 'count': 1},
                                    {'label': 'transcript', 'count': 1}],
            'edge_count_by_label': [{'label': 'transcribes_to', 'count': 1}, {'label': 'translates_to', 'count': 1}]}


def test_count_records_are_not_double_counted_across_groups():
    atoms = parse_mork_output(COUNTS)
    assert parse_mork_counts([atoms, atoms]) == EXPECTED


def test_totals_can_be_read_from_label_counts():
    counts = parse_mork_counts([parse_mork_output('(q_cnt node gene 4) (q_cnt edge links 3)')])
    assert counts['node_count'] == 4
    assert counts['edge_count'] == 3


@pytest.mark.parametrize('value', ['-1', 'bad', '1.5', '١'])
def test_invalid_count_values_are_rejected(value):
    with pytest.raises(ValueError, match='Invalid MORK count'):
        parse_mork_counts([parse_mork_output(f'(q_cnt total node {value})')])


@pytest.fixture
def gen(tmp_path, monkeypatch):
    gen = mod.MorkCLIQueryGenerator(tmp_path)
    (tmp_path / gen.act_filename).touch()
    monkeypatch.setattr(mod, 'Path', lambda path: tmp_path if path == '/dev/shm' else Path(path))
    monkeypatch.setattr(mod, '_get_property_schema', lambda: {})
    return gen


def test_synchronous_counts_use_the_original_graph_process(gen, monkeypatch):
    execute = Mock(return_value=SimpleNamespace(stdout='result:\n' + COUNTS))
    monkeypatch.setattr(mod, '_get_session', lambda _: SimpleNamespace(exec_query=execute))
    gen.run_query((('(gene G1)',), ('(q (gene G1))',), 'query', 'q'))
    for kind in ('total_count', 'label_count'):
        raw = gen.run_query(((), (), kind, 'q'))
        assert gen.parse_and_serialize(raw, {}, {}, 'count') == EXPECTED
    assert execute.call_count == 1


def test_counts_require_the_matching_graph_result(gen, monkeypatch):
    execute = Mock(side_effect=AssertionError('unexpected MORK process'))
    monkeypatch.setattr(mod, '_get_session', execute)
    with pytest.raises(RuntimeError, match='graph query to run first'):
        gen.run_query(((), (), 'total_count', 'missing'))
    execute.assert_not_called()


def test_count_cache_is_bounded_and_isolated_by_query(gen, monkeypatch):
    gen._COUNT_CACHE_SIZE = 2
    execute = Mock(side_effect=[SimpleNamespace(stdout=f'result:\n(q{i}_cnt total node {i})')
                               for i in range(1, 4)])
    monkeypatch.setattr(mod, '_get_session', lambda _: SimpleNamespace(exec_query=execute))
    for i in range(1, 4):
        gen.run_query((('(gene G1)',), ('(q (gene G1))',), 'query', f'q{i}'))
    assert len(gen._count_results) == 2
    with pytest.raises(RuntimeError, match='graph query to run first'):
        gen.run_query(((), (), 'total_count', 'q1'))
    for i in (2, 3):
        raw = gen.run_query(((), (), 'total_count', f'q{i}'))
        assert gen.parse_and_serialize(raw, {}, {}, 'count')['node_count'] == i
    assert execute.call_count == 3


def test_empty_graph_counts_are_cached_as_zero(gen, monkeypatch):
    execute = Mock(return_value=SimpleNamespace(stdout='result:\n'))
    monkeypatch.setattr(mod, '_get_session', lambda _: SimpleNamespace(exec_query=execute))
    gen.run_query((('(gene missing)',), ('(q (gene missing))',), 'query', 'q'))
    result = gen.run_query(((), (), 'total_count', 'q'))
    assert gen.parse_and_serialize(result, {}, {}, 'count') == {
        'node_count': 0, 'edge_count': 0, 'node_count_by_label': [], 'edge_count_by_label': [],
    }
    assert execute.call_count == 1


def test_graph_metadata_uses_sinks_without_recounting(gen, monkeypatch):
    from app.services import mork
    monkeypatch.setattr(mork, 'get_count_by_label', lambda *args: pytest.fail('Python recount'))
    raw = parse_mork_output('(q (links (gene G1) (gene G2))) (q_cnt total node 2) '
                            '(q_cnt total edge 1) (q_cnt node gene 2) (q_cnt edge links 1)')
    graph = gen.parse_and_serialize([raw], {}, {}, 'graph')
    assert len(graph['nodes']) == graph['node_count'] == 2
    assert len(graph['edges']) == graph['edge_count'] == 1


def test_existing_graph_metadata_is_usable_with_either_count_input_slot(gen):
    for inputs in ([EXPECTED, {}], [{}, EXPECTED]):
        assert gen.parse_and_serialize(inputs, {}, {}, 'count') == EXPECTED


@pytest.fixture
def worker(monkeypatch):
    from app.workers import task_handler as worker
    monkeypatch.setattr(worker, 'db_type', 'mork_cli')
    backend = SimpleNamespace(run_query=Mock(side_effect=AssertionError('count task reran MORK')))
    monkeypatch.setattr(worker, 'get_db_for_species', lambda _: backend)
    monkeypatch.setattr(worker, '_drop_stale', lambda *args: False)
    monkeypatch.setattr(worker, 'get_status', lambda _: TaskStatus.PENDING.value)
    monkeypatch.setattr(worker, 'get_annotation_redis', lambda _: EXPECTED)
    monkeypatch.setattr(worker, 'update_task', Mock())
    monkeypatch.setattr(worker, 'set_status', Mock())
    monkeypatch.setattr(worker, 'redis_client', Mock())
    monkeypatch.setattr(worker, 'AnnotationStorageService', Mock())
    monkeypatch.setattr(worker.time, 'sleep', lambda *args: pytest.fail('count task waited for graph'))
    return worker


@pytest.mark.parametrize('name, fields', [
    ('total_count_task', ('node_count', 'edge_count')),
    ('label_count_task', ('node_count_by_label', 'edge_count_by_label')),
])
def test_workers_publish_cached_counts_without_queries(worker, name, fields):
    getattr(worker, name).run(None, 'annotation', {'nodes': [], 'predicates': []}, 0, 'human')
    event = json.loads(worker.redis_client.publish.call_args.args[1])
    assert event['update'] == {field: EXPECTED[field] for field in fields}
    update = worker.AnnotationStorageService.update.call_args.args[1]
    assert all(update[field] == EXPECTED[field] for field in fields)
    worker.get_db_for_species('human').run_query.assert_not_called()


@pytest.mark.parametrize('name', ['total_count_task', 'label_count_task'])
def test_missing_graph_metadata_fails_without_query_fallback(worker, monkeypatch, name):
    monkeypatch.setattr(worker, 'get_annotation_redis', lambda _: None)
    getattr(worker, name).run(None, 'annotation', {'nodes': [], 'predicates': []}, 0, 'human')
    worker.set_status.assert_called_with('annotation', TaskStatus.FAILED.value)
    worker.get_db_for_species('human').run_query.assert_not_called()


@pytest.mark.parametrize('name', ['total_count_task', 'label_count_task'])
def test_workers_accept_cached_zero_counts(worker, monkeypatch, name):
    empty = {'node_count': 0, 'edge_count': 0, 'node_count_by_label': [], 'edge_count_by_label': []}
    monkeypatch.setattr(worker, 'get_annotation_redis', lambda _: empty)
    getattr(worker, name).run(None, 'annotation', {'nodes': [], 'predicates': []}, 0, 'human')
    worker.set_status.assert_not_called()
    worker.get_db_for_species('human').run_query.assert_not_called()
    assert json.loads(worker.redis_client.publish.call_args.args[1])['status'] == TaskStatus.PENDING.value


def test_mork_dispatch_sequences_graph_before_immutable_count_tasks(worker, monkeypatch):
    monkeypatch.setattr(worker, 'is_slow_query', lambda _: False)
    count_chord = SimpleNamespace()
    chord_factory = Mock(return_value=count_chord)
    workflow = Mock()
    chain_factory = Mock(return_value=workflow)
    monkeypatch.setattr(worker, 'chord', chord_factory)
    monkeypatch.setattr(worker, 'chain', chain_factory)
    args = {'all_status': {'result_done': 0, 'total_count_done': 0, 'label_count_done': 0},
            'query': ['graph query', 'total ref', 'label ref'], 'request': {},
            'summary': None, 'meta_data': None, 'species': 'human'}
    worker.start_thread('annotation', args)
    graph_signature, next_stage = chain_factory.call_args.args
    assert graph_signature.task.endswith('.graph_task')
    assert graph_signature.args[0] == 'graph query'
    assert next_stage is count_chord
    headers, callback = chord_factory.call_args.args
    assert len(headers) == 2 and all(signature.immutable for signature in headers)
    assert [signature.args[0] for signature in headers] == ['total ref', 'label ref']
    assert callback.task.endswith('.summary_task')
    workflow.apply_async.assert_called_once()


def test_other_backends_keep_the_parallel_chord(worker, monkeypatch):
    monkeypatch.setattr(worker, 'db_type', 'cypher')
    monkeypatch.setattr(worker, 'is_slow_query', lambda _: False)
    workflow = Mock()
    chord_factory = Mock(return_value=workflow)
    chain_factory = Mock(side_effect=AssertionError('unexpected sequential workflow'))
    monkeypatch.setattr(worker, 'chord', chord_factory)
    monkeypatch.setattr(worker, 'chain', chain_factory)
    worker.start_thread('annotation', {
        'all_status': {'result_done': 0, 'total_count_done': 0, 'label_count_done': 0},
        'query': ['graph query', 'total ref', 'label ref'], 'request': {},
        'summary': None, 'meta_data': None, 'species': 'human',
    })
    headers, _ = chord_factory.call_args.args
    assert len(headers) == 3
    assert headers[0].task.endswith('.graph_task')
    workflow.apply_async.assert_called_once()


def test_graph_worker_saves_count_sink_metadata(worker, monkeypatch, tmp_path):
    graph = {'nodes': [{'data': {'id': 'gene G1', 'type': 'gene'}}], 'edges': [], **EXPECTED}
    backend = SimpleNamespace(run_query=Mock(return_value=[]), parse_and_serialize=Mock(return_value=graph))
    monkeypatch.setattr(worker, 'get_db_for_species', lambda _: backend)
    monkeypatch.setattr(worker, 'check_for_cancellation', lambda _: None)
    monkeypatch.setattr(worker, 'RedisStopEvent', lambda *args: None)
    monkeypatch.setattr(worker, 'Graph', lambda: SimpleNamespace(group_node_only=lambda *args: {}))
    monkeypatch.setattr(worker, 'Path', lambda _: tmp_path)
    save = Mock()
    monkeypatch.setattr(worker, 'save_result_redis', save)
    worker.graph_task.run(None, 'annotation', {'nodes': [], 'predicates': []}, 0, 'human')
    saved = save.call_args.args[1]
    assert all(saved[field] == value for field, value in EXPECTED.items())
    backend.run_query.assert_called_once()


@pytest.mark.parametrize('node_count, labels', [(0, []), (1, [{'label': 'gene', 'count': 1}]), (None, None)])
def test_annotation_response_preserves_zero_counts(monkeypatch, node_count, labels):
    from app.api.api_v1.endpoints import query

    fields = ('request query title summary question answer path_url files retrieval_duration '
              'processing_duration summary_duration total_duration graph_error_message '
              'count_error_message label_count_error_message').split()
    annotation = SimpleNamespace(**dict.fromkeys(fields), id='annotation', user_id='user',
                                 participant_user_ids=[], species='human', data_source='all',
                                 status=TaskStatus.COMPLETE.value, node_count=node_count,
                                 edge_count=0 if node_count is not None else None,
                                 node_count_by_label=labels,
                                 edge_count_by_label=[] if labels is not None else None)
    storage = Mock()
    storage.get_by_id.return_value = annotation
    storage.get_user_annotation.return_value = annotation
    monkeypatch.setattr(query, 'AnnotationStorageService', storage)
    monkeypatch.setattr(query.SharedAnnotationStorageService, 'get', lambda _: None)
    monkeypatch.setattr(query.jwt, 'decode', lambda *args, **kwargs: {'user_id': 'user'})
    cache = Mock()
    cache.get.return_value = json.dumps({'graph': {'nodes': [], 'edges': []}})

    result = query.get_annotation_by_id('annotation', token=None, auth_header='token', redis_client=cache)

    if node_count is None:
        assert not any(key in result for key in EXPECTED)
    else:
        assert result['node_count'] == node_count
        assert result['edge_count'] == 0
        assert result['node_count_by_label'] == labels
        assert result['edge_count_by_label'] == []

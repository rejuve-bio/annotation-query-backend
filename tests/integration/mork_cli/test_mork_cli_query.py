"""Basic native execution and an independent direct-ACT comparison."""

import os

import pytest

pytestmark = [pytest.mark.mork_live, pytest.mark.skipif(
    os.environ.get('MORK_LIVE_TESTS') != '1', reason='set MORK_LIVE_TESTS=1 for native MORK')]


def test_mork_cli_runs_query(mork_backend):
    graph, topology = mork_backend.run({
        'nodes': [{'node_id': 'n0', 'type': 'gene', 'id': '', 'properties': {'gene_name': 'TP53'}}],
        'predicates': [],
    })
    assert topology == {('gene', 'ENSG00000141510')}
    assert graph['node_count'] == 1 and graph['edge_count'] == 0
    independent = mork_backend.raw(
        [f'(ACT {mork_backend.space} (gene_name (gene $x) TP53))'],
        ['(reference (gene $x))'])
    assert topology == independent


@pytest.mark.parametrize('result_id', ['00123456', '1e080001'])
def test_numeric_looking_result_ids_remain_exact_symbols(mork_backend, monkeypatch, result_id):
    monkeypatch.setattr(mork_backend.generator, 'generate_id', lambda: result_id)
    graph, topology = mork_backend.run({
        'nodes': [{'node_id': 'n0', 'type': 'gene', 'id': '', 'properties': {'gene_name': 'TP53'}}],
        'predicates': [],
    })
    assert topology == {('gene', 'ENSG00000141510')}
    assert graph['node_count'] == 1 and graph['edge_count'] == 0

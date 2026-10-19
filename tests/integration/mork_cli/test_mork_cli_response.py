"""Result properties and counts on the native human ACT."""

import json
import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.mork_live, pytest.mark.skipif(
    os.environ.get('MORK_LIVE_TESTS') != '1', reason='set MORK_LIVE_TESTS=1 for native MORK')]


@pytest.mark.parametrize('case_name', ['S10c_nolog_chain_TP53', 'S13_not_on_non_root_node'])
def test_mork_cli_response_shape(mork_backend, gene_facts, case_name):
    cases = json.loads(Path(__file__).with_name('cases.json').read_text())
    request = next(case['request'] for case in cases if case['name'] == case_name)
    graph, _ = mork_backend.run(request)
    schema = mork_backend.schema['human']
    assert len(graph['nodes']) == graph['node_count']
    assert len(graph['edges']) == graph['edge_count']
    for entry in graph['nodes']:
        data = entry['data']
        assert {'id', 'type', 'name'} <= data.keys()
        declared = schema['nodes'].get(data['type'], {}).get('properties', {})
        assert data.keys() <= set(declared) | {'id', 'type', 'name'}
        assert not {'synonym', 'synonyms', 'accessions'} & data.keys()
        if data['type'] == 'gene':
            source = gene_facts[data['id'].split(' ', 1)[1]]
            for prop in set(declared) & source.keys() - {'synonym', 'synonyms', 'accessions'}:
                assert prop in data and data[prop] in source[prop]
    identifiers = {entry['data']['id'] for entry in graph['nodes']}
    for entry in graph['edges']:
        data = entry['data']
        assert data['source'] in identifiers and data['target'] in identifiers
        structural = {'id', 'edge_id', 'label', 'source', 'target', 'source_data'}
        declared = schema['edges'].get(data['label'], {}).get('properties', {})
        assert data.keys() <= set(declared) | structural

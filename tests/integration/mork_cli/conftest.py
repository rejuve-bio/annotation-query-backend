"""Opt-in native MORK fixtures; application services stay outside collection."""

import copy
import fcntl
import hashlib
import os
import re
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest


class NativeMork:
    def __init__(self, generator, schema, binary, lock_file, timeout, scratch, source_dir):
        self.generator = generator
        self.schema = schema
        self.binary = binary
        self.lock_file = lock_file
        self.timeout = timeout
        self.scratch = scratch
        self.source_dir = source_dir
        self.calls = []
        dataset_id = hashlib.md5(str(generator.dataset_path.resolve()).encode()).hexdigest()[:8]
        self.space = f'mork_{dataset_id}'

    def execute(self, query_file):
        with self.lock_file.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            start = time.perf_counter()
            result = subprocess.run([str(self.binary), 'run', str(query_file)],
                                    capture_output=True, text=True, timeout=self.timeout,
                                    cwd=self.scratch, check=True)
            elapsed = time.perf_counter() - start
        self.calls.append({'seconds': elapsed, 'program': Path(query_file).read_text()})
        return result

    def run(self, request, limit=None):
        from app.lib.logic import counted_nodes_and_predicates
        from app.lib.query_canonical import canonicalize_graph
        from app.lib.validator import validate_request

        request = copy.deepcopy(request)
        nodes = {node['node_id']: node for node in request['nodes']}
        relationships = {
            f"{nodes[p['source']]['type']}_{p['type'].replace(' ', '_')}_{nodes[p['target']]['type']}": {}
            for p in request.get('predicates', [])
        }
        validate_request(request, relationships, None)
        request = self.generator.parse_id(request)
        canonical, _ = canonicalize_graph(request)
        queries = self.generator.query_Generator(canonical, {n['node_id']: n for n in canonical['nodes']}, limit)
        before = len(self.calls)
        raw = self.generator.run_query(queries[0])
        components = {'nodes': request['nodes'], 'predicates': request['predicates'], 'properties': True}
        graph = self.generator.parse_and_serialize(raw, self.schema, components, 'graph')
        fields = ('node_count', 'edge_count', 'node_count_by_label', 'edge_count_by_label')
        counts = {key: graph[key] for key in fields}
        counted_nodes, counted_predicates = counted_nodes_and_predicates(request)
        for query in queries[1:]:
            count_input = self.generator.run_query(query)
            actual = self.generator.parse_and_serialize(count_input, self.schema, {
                **components, 'nodes': counted_nodes, 'predicates': counted_predicates}, 'count')
            assert actual == counts
        assert len(self.calls) - before == 1
        assert all(atom[0] in (queries[0][3], queries[0][3] + '_cnt', 'tmp') for atom in raw[0])
        return graph, {atom[1] for atom in raw[0] if atom[0] == queries[0][3]}

    def raw(self, sources, outputs):
        from app.services.mork_cli_generator import _repair_mork_output
        from app.services.mork_output import parse_mork_output

        query = self.scratch / 'reference.metta'
        query.write_text(f"(exec 1 (I {' '.join(sources)}) (, {' '.join(outputs)}))\n")
        result = self.execute(query)
        atoms = parse_mork_output(_repair_mork_output(result.stdout.split('result:', 1)[1]))
        assert all(atom[0] == 'reference' for atom in atoms)
        return {atom[1] for atom in atoms}


@pytest.fixture(scope='module')
def mork_backend(tmp_path_factory):
    if os.environ.get('MORK_LIVE_TESTS') != '1':
        pytest.skip('set MORK_LIVE_TESTS=1 to run against a native human ACT')
    required = ('MORK_TEST_BINARY', 'MORK_TEST_DATA_DIR')
    for name in required:
        if not os.environ.get(name):
            pytest.skip(f'set {name} for native MORK checks')
    binary = Path(os.environ['MORK_TEST_BINARY']).resolve()
    data_dir = Path(os.environ['MORK_TEST_DATA_DIR']).resolve()
    act_file = os.environ.get('MORK_TEST_ACT_FILE', 'annotation.act')
    if not binary.is_file() or not os.access(binary, os.X_OK):
        pytest.fail(f'MORK_TEST_BINARY is not executable: {binary}')
    if not (data_dir / act_file).is_file():
        pytest.fail(f'ACT file is missing: {data_dir / act_file}')
    repo = Path(__file__).resolve().parents[3]
    local_lock = repo / 'dev-tools/mork/.mork.lock'
    default_lock = local_lock if local_lock.parent.is_dir() else Path(tempfile.gettempdir()) / 'annotation-mork-live.lock'
    lock_file = Path(os.environ.get('MORK_TEST_LOCK_FILE', str(default_lock))).resolve()
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    timeout = float(os.environ.get('MORK_TEST_TIMEOUT', '300'))
    if timeout <= 0:
        pytest.fail('MORK_TEST_TIMEOUT must be positive')

    from app.services import mork_cli_generator as mod
    generator = mod.MorkCLIQueryGenerator(data_dir, act_filename=act_file, species='human')
    backend = NativeMork(generator, mod._get_property_schema(), binary, lock_file, timeout,
                         tmp_path_factory.mktemp('mork-native'),
                         Path(os.environ.get('MORK_TEST_SOURCE_DIR', str(data_dir))).resolve())
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(mod, '_get_session', lambda _: SimpleNamespace(exec_query=backend.execute))
        yield backend


@pytest.fixture(scope='module')
def gene_facts(mork_backend):
    source = mork_backend.source_dir / 'gencode/gene/nodes_gene.metta'
    if not source.is_file():
        pytest.skip(f'gene source facts are missing: {source}')
    facts = defaultdict(lambda: defaultdict(set))
    pattern = re.compile(r'^\((\S+) \(gene ([^\s()]+)\) ([^\s()]+)\)\s*$')
    for line in source.open():
        if line.startswith('(gene '):
            facts[line.strip()[6:-1]]
        match = pattern.match(line)
        if match:
            name, identifier, value = match.groups()
            facts[identifier][name].add(value.encode()[:63].decode('utf-8', errors='ignore'))
    return facts

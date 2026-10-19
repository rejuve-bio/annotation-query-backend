"""Building, staleness and lookups of the MORK neighbourhood index."""

import fcntl
import os
import re

import pytest

from app.core.config import settings
from app.services import mork_neighbourhood_index as mod
from app.services.mork_neighbourhood_index import NeighbourhoodIndex
from app.services.mork_output import parse_mork_output

FACTS = '''
(gene_name (gene G1) TP53) (gene_type (gene G1) coding) (transcript_name (transcript T1) TP53-201)
(transcribes_to (gene G1) (transcript T1))
(closest_gene (snp S1) (gene G1)) (closest_gene (snp S2) (gene G1))
(coexpressed_with (gene G1) (gene G2)) (coexpressed_with (gene G2) (gene G1))
(distance (closest_gene (snp S1) (gene G1)) 120)
'''


class FakeMork:
    """Runs the index's scan and reverse programs over FACTS."""

    def __init__(self, shm):
        self.shm = shm
        self.programs = []
        self.facts = parse_mork_output(FACTS)

    def __call__(self, program, timeout_s, stop_event=None):
        self.programs.append(program)
        if "(, (triple" in program:
            return [('triple', a[0], a[1][0], a[2][0]) for a in self.facts
                    if len(a) == 3 and all(isinstance(x, tuple) and len(x) == 2 for x in a[1:])]
        if "(, (np" in program:
            return [('np', a[0], a[1][0]) for a in self.facts
                    if len(a) == 3 and isinstance(a[1], tuple) and len(a[1]) == 2]
        if "(, (ep" in program:
            return [('ep', a[0], a[1][0]) for a in self.facts
                    if len(a) == 3 and isinstance(a[1], tuple) and len(a[1]) == 3]
        match = re.search(r"\(ACT \S+ \((\S+) \((\S+) \$s\) \((\S+) \$t\)\)\)\) \(O \(ACT (\S+) ", program)
        label, source, target, name = match.groups()
        edges = [a for a in self.facts if a[0] == label and a[1][0] == source and a[2][0] == target]
        if edges:   # an empty ACT sink writes no file
            (self.shm / f"{name}.act").write_text(
                "".join(f"({label} ({target} {e[2][1]}) ({source} {e[1][1]}))\n" for e in edges))
        return []


@pytest.fixture
def index(tmp_path, monkeypatch):
    shm = tmp_path / 'shm'
    shm.mkdir()
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'human.act').write_text('act')
    monkeypatch.setattr(mod, 'SHM', shm)
    monkeypatch.setattr(settings, 'MORK_INDEX_DIR', str(tmp_path / 'index'))
    fake = FakeMork(shm)
    idx = NeighbourhoodIndex(data, 'human.act', 'mork_test', fake)
    idx.fake, idx.shm = fake, shm
    return idx


def test_missing_until_built_then_ready_with_vocabulary(index):
    assert index.status() == mod.MISSING and index.vocabulary() is None
    assert index.build() is True
    assert index.status() == mod.READY
    vocab = index.vocabulary()
    assert vocab['triples'] == [['gene', 'coexpressed_with', 'gene'], ['gene', 'transcribes_to', 'transcript'],
                                ['snp', 'closest_gene', 'gene']]
    assert vocab['node_types'] == ['gene', 'snp', 'transcript']
    # Edges match ($p ($t $x) $v) too; they must not become node properties.
    assert vocab['node_properties'] == {'gene': ['gene_name', 'gene_type'], 'transcript': ['transcript_name']}
    assert vocab['edge_properties'] == {'closest_gene': ['distance']}


def test_reverse_spaces_hold_target_first_edges_and_skip_symmetric_types(index):
    index.build()
    name = index.reverse_space(('snp', 'closest_gene', 'gene'))
    assert (index.dir / f'{name}.act').read_text() == \
        '(closest_gene (gene G1) (snp S1))\n(closest_gene (gene G1) (snp S2))\n'
    assert (index.shm / f'{name}.act').resolve() == (index.dir / f'{name}.act').resolve()
    assert index.reverse_space(('gene', 'coexpressed_with', 'gene')) is None
    assert not any('(coexpressed_with (gene $s)' in p for p in index.fake.programs)


def test_links_are_recreated_after_dev_shm_is_emptied(index):
    index.build()
    triple = ('gene', 'transcribes_to', 'transcript')
    name = index.reverse_space(triple)
    (index.shm / f'{name}.act').unlink()
    assert index.reverse_space(triple) == name
    assert (index.shm / f'{name}.act').exists()


def test_a_changed_act_makes_the_index_stale_and_rebuild_replaces_it(index):
    index.build()
    old = set(os.listdir(index.dir))
    act = index.act_file
    act.write_text('a newer act')
    os.utime(act, (act.stat().st_atime + 10, act.stat().st_mtime + 10))
    assert index.status() == mod.MISSING and index.vocabulary() is None
    programs = len(index.fake.programs)
    index.build()
    assert index.status() == mod.READY and len(index.fake.programs) > programs
    assert {p for p in os.listdir(index.dir) if p.endswith('.act')} == \
        {p for p in old if p.endswith('.act')}


def test_build_is_a_no_op_when_current_and_skipped_while_another_builds(index):
    index.build()
    programs = len(index.fake.programs)
    assert index.build() is True and len(index.fake.programs) == programs
    with open(index.dir / '.build.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert index.is_building()
        assert index.build() is False


def test_vocabulary_survives_a_failed_reverse_build(index):
    def fail_on_reverse(program, timeout_s, stop_event=None):
        if '(O (ACT' in program:
            raise TimeoutError('too slow')
        return FakeMork(index.shm)(program, timeout_s)
    index.run_program = fail_on_reverse
    with pytest.raises(TimeoutError):
        index.build()
    assert index.status() == mod.VOCABULARY_ONLY
    assert index.reverse_space(('snp', 'closest_gene', 'gene')) is None
    index.run_program = index.fake
    index.build()
    assert index.status() == mod.READY
    assert not any('(, (triple' in p for p in index.fake.programs)   # vocabulary reused

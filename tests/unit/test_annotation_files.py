"""Tests for the per-annotation graph/VCF file copies made when a result is reused."""
from types import SimpleNamespace

import pytest

from app.lib import annotation_files
from app.lib.annotation_files import copy_graph_files

VCF_FILES = [{"type": "vcf", "file": "/public/vcf/orig.vcf.gz", "index": "/public/vcf/orig.vcf.gz.tbi"}]


@pytest.fixture
def public(monkeypatch, tmp_path):
    monkeypatch.setattr(annotation_files, "PUBLIC_DIR", tmp_path)
    (tmp_path / "graph").mkdir()
    (tmp_path / "vcf").mkdir()
    (tmp_path / "graph" / "orig.json").write_text('{"nodes": [], "edges": []}')
    (tmp_path / "vcf" / "orig.vcf.gz").write_bytes(b"vcf")
    (tmp_path / "vcf" / "orig.vcf.gz.tbi").write_bytes(b"tbi")
    return tmp_path


def doc(public, files=None):
    return SimpleNamespace(path_url=str(public / "graph" / "orig.json"), files=files)


def test_graph_file_is_copied_under_the_new_id(public):
    result = copy_graph_files(doc(public), "new")
    assert result == {"path_url": str(public / "graph" / "new.json"), "files": None}
    assert (public / "graph" / "new.json").read_text() == '{"nodes": [], "edges": []}'


def test_copy_does_not_follow_later_changes_to_the_original(public):
    result = copy_graph_files(doc(public), "new")
    (public / "graph" / "orig.json").write_text('{"nodes": [1], "edges": []}')
    assert open(result["path_url"]).read() == '{"nodes": [], "edges": []}'


def test_vcf_and_index_are_copied_and_relinked(public):
    result = copy_graph_files(doc(public, VCF_FILES), "new")
    assert result["files"] == [{"type": "vcf", "file": "/public/vcf/new.vcf.gz",
                                "index": "/public/vcf/new.vcf.gz.tbi"}]
    assert (public / "vcf" / "new.vcf.gz").read_bytes() == b"vcf"
    assert (public / "vcf" / "new.vcf.gz.tbi").read_bytes() == b"tbi"
    assert not list(public.rglob("*.tmp"))


@pytest.mark.parametrize("path_url", [None, "/does/not/exist.json"])
def test_missing_graph_file_means_recompute(public, path_url):
    source = SimpleNamespace(path_url=path_url, files=None)
    assert copy_graph_files(source, "new") == {"path_url": None, "files": None}


def test_missing_vcf_means_recompute_and_copies_nothing(public):
    (public / "vcf" / "orig.vcf.gz.tbi").unlink()
    assert copy_graph_files(doc(public, VCF_FILES), "new") == {"path_url": None, "files": None}
    assert not (public / "graph" / "new.json").exists()


def test_copy_failure_means_recompute(public, monkeypatch):
    def fail(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(annotation_files.shutil, "copyfile", fail)
    assert copy_graph_files(doc(public), "new") == {"path_url": None, "files": None}

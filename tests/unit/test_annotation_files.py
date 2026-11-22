"""Tests for the per-annotation graph/VCF file copies made when a result is reused."""
from types import SimpleNamespace

import pytest

from app.lib import annotation_files
from app.lib.annotation_files import copy_graph_files

ORIGINAL_ID = "507f1f77bcf86cd799439011"
COPY_ID = "507f1f77bcf86cd799439012"
VCF_FILES = [{"type": "vcf", "file": f"/public/vcf/{ORIGINAL_ID}.vcf.gz", "index": f"/public/vcf/{ORIGINAL_ID}.vcf.gz.tbi"}]


@pytest.fixture
def public(monkeypatch, tmp_path):
    monkeypatch.setattr(annotation_files, "PUBLIC_DIR", tmp_path)
    (tmp_path / "graph").mkdir()
    (tmp_path / "vcf").mkdir()
    (tmp_path / "graph" / f"{ORIGINAL_ID}.json").write_text('{"nodes": [], "edges": []}')
    (tmp_path / "vcf" / f"{ORIGINAL_ID}.vcf.gz").write_bytes(b"vcf")
    (tmp_path / "vcf" / f"{ORIGINAL_ID}.vcf.gz.tbi").write_bytes(b"tbi")
    return tmp_path


def doc(public, files=None):
    return SimpleNamespace(id=ORIGINAL_ID, path_url=str(public / "graph" / f"{ORIGINAL_ID}.json"), files=files)


def test_graph_file_is_copied_under_the_new_id(public):
    result = copy_graph_files(doc(public), COPY_ID)
    assert result == {"path_url": str(public / "graph" / f"{COPY_ID}.json"), "files": None}
    assert (public / "graph" / f"{COPY_ID}.json").read_text() == '{"nodes": [], "edges": []}'


def test_copy_does_not_follow_later_changes_to_the_original(public):
    result = copy_graph_files(doc(public), COPY_ID)
    (public / "graph" / f"{ORIGINAL_ID}.json").write_text('{"nodes": [1], "edges": []}')
    assert open(result["path_url"]).read() == '{"nodes": [], "edges": []}'


def test_vcf_and_index_are_copied_and_relinked(public):
    result = copy_graph_files(doc(public, VCF_FILES), COPY_ID)
    assert result["files"] == [{"type": "vcf", "file": f"/public/vcf/{COPY_ID}.vcf.gz",
                                "index": f"/public/vcf/{COPY_ID}.vcf.gz.tbi"}]
    assert (public / "vcf" / f"{COPY_ID}.vcf.gz").read_bytes() == b"vcf"
    assert (public / "vcf" / f"{COPY_ID}.vcf.gz.tbi").read_bytes() == b"tbi"
    assert not list(public.rglob("*.tmp"))


def test_missing_graph_file_means_recompute(public):
    source = doc(public)
    (public / "graph" / f"{ORIGINAL_ID}.json").unlink()
    assert copy_graph_files(source, COPY_ID) == {"path_url": None, "files": None}


def test_copy_uses_the_record_id_even_if_stored_path_differs(public):
    source = doc(public)
    source.path_url = str(public / "different.json")
    assert copy_graph_files(source, COPY_ID)["path_url"] == str(public / "graph" / f"{COPY_ID}.json")


@pytest.mark.parametrize("subdir,suffix,resolve", [
    ("graph", ".json", annotation_files.graph_file_path),
    ("vcf", ".vcf.gz", annotation_files.vcf_file_path),
])
def test_file_resolver_rejects_aliases_to_other_records(public, subdir, suffix, resolve):
    file_path = public / subdir / f"{ORIGINAL_ID}{suffix}"
    other_file = public / subdir / f"{COPY_ID}{suffix}"
    other_file.write_bytes(b"another annotation")
    assert resolve(ORIGINAL_ID) == str(file_path)
    file_path.unlink()
    file_path.symlink_to(other_file)
    assert resolve(ORIGINAL_ID) is None
    assert resolve("invalid") is None


def test_missing_vcf_means_recompute_and_copies_nothing(public):
    (public / "vcf" / f"{ORIGINAL_ID}.vcf.gz.tbi").unlink()
    assert copy_graph_files(doc(public, VCF_FILES), COPY_ID) == {"path_url": None, "files": None}
    assert not (public / "graph" / f"{COPY_ID}.json").exists()


def test_copy_failure_means_recompute(public, monkeypatch):
    def fail(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(annotation_files.shutil, "copyfile", fail)
    assert copy_graph_files(doc(public), COPY_ID) == {"path_url": None, "files": None}

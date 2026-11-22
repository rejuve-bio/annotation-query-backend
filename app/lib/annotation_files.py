"""Per-annotation copies of the graph JSON and VCF files the worker writes."""
import logging
import os
import shutil
from pathlib import Path

from bson import ObjectId

logger = logging.getLogger(__name__)

PUBLIC_DIR = Path(__file__).resolve().parents[2] / "public"


def _annotation_file_path(directory, annotation_id, suffix):
    if not ObjectId.is_valid(annotation_id):
        return None

    root = os.path.realpath(PUBLIC_DIR)
    base = os.path.join(root, directory)
    expected = os.path.join(base, f"{ObjectId(annotation_id)}{suffix}")
    path = os.path.realpath(expected)
    if not path.startswith(base + os.sep):
        return None
    # A sibling annotation's file is outside the authorized record too.
    if path != expected:
        return None
    return path


def graph_file_path(annotation_id):
    return _annotation_file_path("graph", annotation_id, ".json")


def vcf_file_path(annotation_id, *, index=False):
    return _annotation_file_path("vcf", annotation_id, ".vcf.gz.tbi" if index else ".vcf.gz")


def _copy(src, dst):
    # Copy to a temp name and rename, so a reader never sees a half-written file.
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def copy_graph_files(existing_doc, new_annotation_id):
    """Give a dedup copy its own graph and VCF files; returns {"path_url", "files"}.

    The worker rewrites graph/{id}.json and vcf/{id}.vcf.gz in place when the
    original annotation is edited or re-run, and the VCF download only serves
    the original's owner, so a copy must not point at the original's files.
    If any source file is missing or can't be copied, both fields are None and
    the copy recomputes its graph on its first uncached read.
    """
    none = {"path_url": None, "files": None}
    graph_src = graph_file_path(existing_doc.id)
    graph_dst = graph_file_path(new_annotation_id)
    if not graph_src or not graph_dst or not os.path.isfile(graph_src):
        return none

    copies = [(graph_src, Path(graph_dst))]

    files = None
    if existing_doc.files:
        files = []
        for entry in existing_doc.files:
            new_entry = dict(entry)
            for key, suffix in (("file", ".vcf.gz"), ("index", ".vcf.gz.tbi")):
                if entry.get(key):
                    src = vcf_file_path(existing_doc.id, index=key == "index")
                    dst = vcf_file_path(new_annotation_id, index=key == "index")
                    if not src or not dst or not os.path.isfile(src):
                        return none
                    copies.append((src, Path(dst)))
                    new_entry[key] = f"/public/vcf/{new_annotation_id}{suffix}"
            files.append(new_entry)

    try:
        for src, dst in copies:
            _copy(src, dst)
    except OSError as e:
        logger.warning("Could not copy graph files for annotation %s: %s", new_annotation_id, e)
        return none

    return {"path_url": graph_dst, "files": files}

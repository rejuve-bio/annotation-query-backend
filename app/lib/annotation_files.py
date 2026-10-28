"""Per-annotation copies of the graph JSON and VCF files the worker writes."""
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

PUBLIC_DIR = Path("/app/public")


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
    if not existing_doc.path_url or not os.path.exists(existing_doc.path_url):
        return none

    vcf_dir = PUBLIC_DIR / "vcf"
    copies = []  # (src, dst)
    graph_dst = Path(existing_doc.path_url).with_name(f"{new_annotation_id}.json")
    copies.append((Path(existing_doc.path_url), graph_dst))

    files = None
    if existing_doc.files:
        files = []
        for entry in existing_doc.files:
            new_entry = dict(entry)
            for key, suffix in (("file", ".vcf.gz"), ("index", ".vcf.gz.tbi")):
                if entry.get(key):
                    src = vcf_dir / Path(entry[key]).name
                    if not src.exists():
                        return none
                    copies.append((src, vcf_dir / f"{new_annotation_id}{suffix}"))
                    new_entry[key] = f"/public/vcf/{new_annotation_id}{suffix}"
            files.append(new_entry)

    try:
        for src, dst in copies:
            _copy(src, dst)
    except OSError as e:
        logger.warning("Could not copy graph files for annotation %s: %s", new_annotation_id, e)
        return none

    return {"path_url": str(graph_dst), "files": files}

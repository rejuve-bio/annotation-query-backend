"""Vocabulary and reverse-edge index for MORK neighbourhood expansion.

The ACT is a trie keyed from the front of each atom, so `(label (A a) (B b))`
is found quickly from its source but only by a full scan from its target.
Incoming edges into a gene take ~25 s that way. The index stores every edge
type a second time with the target first, one ACT per (source type, label,
target type), and turns that lookup into milliseconds.

The vocabulary (edge type triples, node and edge property names) is read from
the ACT itself, because the schema config misses types and properties.

Both are built by the service from the ACT, in the background, and rebuilt
whenever the ACT changes. A build takes ~45 min: three full scans for the
vocabulary, then one program per edge type for the reverse index.
"""

import fcntl
import json
import logging
import os
import shutil
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

INDEX_VERSION = 1

# Edge types stored in both directions in the data, so incoming edges are
# found from the outgoing side without an index.
SYMMETRIC_LABELS = frozenset({"coexpressed_with"})

# MORK resolves ACT space names to files here.
SHM = Path("/dev/shm")

READY, VOCABULARY_ONLY, BUILDING, MISSING = "ready", "vocabulary_only", "building", "missing"


class NeighbourhoodIndex:
    def __init__(self, dataset_path, act_filename, space, run_program):
        self.dataset_path = Path(dataset_path)
        self.act_file = self.dataset_path / act_filename
        self.space = space
        # run_program(program_text, timeout_s, stop_event) -> parsed atoms
        self.run_program = run_program
        root = Path(settings.MORK_INDEX_DIR) if settings.MORK_INDEX_DIR else self.dataset_path / "neighbourhood_index"
        self.dir = root / space
        self.manifest_path = self.dir / "manifest.json"
        self._manifest = None
        self._manifest_mtime = None

    # -- state -------------------------------------------------------------

    def _act_signature(self):
        stat = self.act_file.stat()
        return {"mtime": int(stat.st_mtime), "size": stat.st_size}

    def manifest(self):
        """The manifest for the current ACT, or None if missing or stale."""
        try:
            mtime = self.manifest_path.stat().st_mtime
        except FileNotFoundError:
            return None
        if mtime != self._manifest_mtime:
            try:
                self._manifest = json.loads(self.manifest_path.read_text())
            except (OSError, ValueError):
                return None
            self._manifest_mtime = mtime
        manifest = self._manifest
        if manifest.get("version") != INDEX_VERSION or manifest.get("act") != self._act_signature():
            return None
        return manifest

    def is_building(self):
        lock = self.dir / ".build.lock"
        if not lock.exists():
            return False
        with open(lock, "a") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(fh, fcntl.LOCK_UN)
        return False

    def status(self):
        manifest = self.manifest()
        if manifest and manifest.get("reverse") is not None:
            return READY
        if self.is_building():
            return BUILDING
        return VOCABULARY_ONLY if manifest else MISSING

    def vocabulary(self):
        manifest = self.manifest()
        return manifest["vocabulary"] if manifest else None

    def reverse_space(self, triple):
        """ACT space holding `(label (T t) (S s))` for an edge type, or None."""
        manifest = self.manifest()
        if not manifest or manifest.get("reverse") is None:
            return None
        name = manifest["reverse"].get(" ".join(triple))
        if name:
            self._link(name)
        return name

    def _link(self, name):
        # MORK resolves ACT names in /dev/shm, which is emptied on reboot.
        link, target = SHM / f"{name}.act", self.dir / f"{name}.act"
        if not link.exists():
            tmp = link.with_name(f"{link.name}.tmp.{os.getpid()}")
            tmp.unlink(missing_ok=True)
            os.symlink(target.resolve(), tmp)
            os.replace(tmp, link)

    # -- build -------------------------------------------------------------

    def build(self, stop_event=None):
        """Build the vocabulary and reverse index for the current ACT.

        Returns False without doing anything when another process is
        building. Safe to call when the index is already up to date.
        """
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / ".build.lock", "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            signature = self._act_signature()
            manifest = self.manifest()
            if manifest is None:
                logger.info("[neighbourhood index] Reading the vocabulary from %s", self.act_file)
                manifest = {"version": INDEX_VERSION, "act": signature,
                            "vocabulary": self._scan_vocabulary(stop_event), "reverse": None}
                self._write_manifest(manifest)
            if manifest["reverse"] is None:
                manifest["reverse"] = self._build_reverse(manifest["vocabulary"]["triples"], stop_event)
                if self._act_signature() != signature:
                    logger.warning("[neighbourhood index] ACT changed during the build; it will be rebuilt")
                    return True
                self._write_manifest(manifest)
                self._remove_stale_files(manifest)
            logger.info("[neighbourhood index] Ready in %s", self.dir)
            return True

    def _run(self, program, stop_event):
        return self.run_program(program, settings.MORK_INDEX_PROGRAM_TIMEOUT_S, stop_event)

    def _scan_vocabulary(self, stop_event):
        act = f"(ACT {self.space}"
        triples = {atom[1:] for atom in self._run(
            f"(exec 1 (I {act} ($l ($a $x) ($b $y)))) (, (triple $l $a $b)))\n", stop_event)
            if atom[0] == "triple"}
        # ($p ($t $x) $v) also matches every edge as (label, source type).
        edge_subjects = {(label, source) for label, source, _ in triples}
        node_properties = {}
        for atom in self._run(f"(exec 1 (I {act} ($p ($t $x) $v))) (, (np $p $t)))\n", stop_event):
            if atom[0] == "np" and (atom[1], atom[2]) not in edge_subjects:
                node_properties.setdefault(atom[2], set()).add(atom[1])
        edge_properties = {}
        for atom in self._run(f"(exec 1 (I {act} ($p ($l $s $o) $v))) (, (ep $p $l)))\n", stop_event):
            if atom[0] == "ep":
                edge_properties.setdefault(atom[2], set()).add(atom[1])
        node_types = {source for _, source, _ in triples} | {target for _, _, target in triples}
        node_types |= set(node_properties)
        return {
            "triples": sorted([source, label, target] for label, source, target in triples),
            "node_types": sorted(node_types),
            "node_properties": {t: sorted(keys) for t, keys in sorted(node_properties.items())},
            "edge_properties": {label: sorted(keys) for label, keys in sorted(edge_properties.items())},
        }

    def _build_reverse(self, triples, stop_event):
        reverse = {}
        for number, (source, label, target) in enumerate(triples):
            if label in SYMMETRIC_LABELS and source == target:
                continue
            name = f"{self.space}_rev{number}"
            built = SHM / f"{name}.act"
            built.unlink(missing_ok=True)
            logger.info("[neighbourhood index] Reversing %s %s %s", source, label, target)
            # An ACT sink writes /dev/shm/<name>.act (memory); move it to disk.
            self._run(f"(exec 1 (I (ACT {self.space} ({label} ({source} $s) ({target} $t)))) "
                      f"(O (ACT {name} ({label} ({target} $t) ({source} $s)))))\n", stop_event)
            if not built.exists():
                continue    # no edges of this type: an empty sink writes no file
            shutil.move(str(built), self.dir / f"{name}.act")
            self._link(name)
            reverse[f"{source} {label} {target}"] = name
        return reverse

    def _write_manifest(self, manifest):
        tmp = self.manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=1))
        os.replace(tmp, self.manifest_path)

    def _remove_stale_files(self, manifest):
        keep = {f"{name}.act" for name in manifest["reverse"].values()}
        for path in self.dir.glob("*.act"):
            if path.name not in keep:
                path.unlink()

#!/usr/bin/env python3
import os
import sys
import subprocess
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def _fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

def _fmt_elapsed(seconds):
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"

def get_mork_bin():
    default_wrapper = Path(__file__).resolve().parent / "mork_docker_wrapper.py"
    if default_wrapper.exists():
        return str(default_wrapper)
    raise RuntimeError("MORK docker wrapper not found.")

def get_metta_files(data_dir):
    data_path = Path(data_dir)
    type_defs = data_path / "type_defs.metta"

    others = sorted(
        f for f in data_path.rglob("*.metta")
        if f != type_defs and not f.name.endswith(".tmp.metta")
    )

    metta_files = []
    if type_defs.exists():
        metta_files.append(type_defs)
    metta_files.extend(others)
    return metta_files

def needs_rebuild(data_dir, output_act):
    data_path = Path(data_dir)
    act_path = Path(output_act)
    
    if not act_path.exists():
        return True
        
    metta_files = get_metta_files(data_dir)
    if not metta_files:
        return False
        
    act_mtime = act_path.stat().st_mtime
    return any(f.stat().st_mtime > act_mtime for f in metta_files)

def build_act(data_dir, output_act=None):
    data_path = Path(data_dir)
    if not data_path.is_dir():
        print(f"Error: Directory '{data_dir}' does not exist.")
        return False

    if output_act is None:
        output_act = data_path / "annotation.act"
    else:
        output_act = Path(output_act)

    if not needs_rebuild(data_dir, output_act):
        print(f"{output_act.name} is up to date.")
        return True

    merged_metta = data_path / "annotation.tmp.metta"
    mork_bin = get_mork_bin()

    metta_files = get_metta_files(data_dir)
    if not metta_files:
        print(f"No .metta files found in {data_dir}")
        return False

    total_size = sum(f.stat().st_size for f in metta_files)
    total_files = len(metta_files)
    print(f"1. Consolidating {total_files} MeTTa files ({_fmt_size(total_size)}) ...")

    t0 = time.time()
    written = 0
    CHUNK = 4 * 1024 * 1024  # 4 MB read buffer
    with open(merged_metta, "wb") as outfile:
        for i, metta_file in enumerate(metta_files, 1):
            file_size = metta_file.stat().st_size
            rel = metta_file.relative_to(data_path)
            pct = written / total_size * 100 if total_size else 0
            print(f"  [{i:>{len(str(total_files))}}/{total_files}] {rel}  ({_fmt_size(file_size)})  —  {pct:.1f}% done", flush=True)
            with open(metta_file, "rb") as infile:
                while chunk := infile.read(CHUNK):
                    outfile.write(chunk)
                    written += len(chunk)
            outfile.write(b"\n")
            written += 1

    elapsed = time.time() - t0
    print(f"   Merged {_fmt_size(written)} in {_fmt_elapsed(elapsed)}")

    print(f"\n2. Compiling into binary Arena (ACT) ...")
    convert_cmd = [
        sys.executable,
        mork_bin,
        "convert",
        "metta",
        "act",
        "$",
        "_1",
        str(merged_metta),
        str(output_act)
    ]
    env = os.environ.copy()
    env["MORK_DATA_DIR"] = str(data_path)

    t1 = time.time()
    proc = None
    try:
        proc = subprocess.Popen(convert_cmd, text=True, env=env)
        proc.wait()
        if proc.returncode != 0:
            print(f"Error: mork exited with code {proc.returncode}")
            return False
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return False
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            proc.wait()
        if merged_metta.exists():
            merged_metta.unlink()

    elapsed2 = time.time() - t1
    print(f"   Compilation done in {_fmt_elapsed(elapsed2)}")

    print(f"\n3. Finalizing...")
    act_size = Path(output_act).stat().st_size if Path(output_act).exists() else 0
    total_elapsed = time.time() - t0
    print(f"Done: {output_act}  ({_fmt_size(act_size)})  total time: {_fmt_elapsed(total_elapsed)}")
    return True

if __name__ == "__main__":
    import argparse

    default_data_dir = os.getenv("MORK_DATA_DIR")

    parser = argparse.ArgumentParser(
        description="Compile MeTTa files into a MORK ACT binary.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # use MORK_DATA_DIR from .env, default output name (annotation.act)
  python scripts/build_act.py

  # explicit data dir, default output name
  python scripts/build_act.py /data/mork

  # explicit data dir and custom output file
  python scripts/build_act.py /data/mork /data/mork/human.act

  # keep data dir from .env, custom output name only
  python scripts/build_act.py --output human.act
        """,
    )
    parser.add_argument(
        "data_dir",
        nargs="?",
        default=default_data_dir,
        help="directory containing .metta files (default: $MORK_DATA_DIR)",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="output .act file path (default: <data_dir>/annotation.act)",
    )
    parser.add_argument(
        "--output", "-o",
        dest="output_flag",
        default=None,
        metavar="FILE",
        help="output .act file path (alternative to positional arg)",
    )

    args = parser.parse_args()

    if not args.data_dir:
        parser.error("MORK_DATA_DIR is not set and no data_dir was provided.")

    output_act = args.output_flag or args.output
    try:
        success = build_act(args.data_dir, output_act)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    sys.exit(0 if success else 1)
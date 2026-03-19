#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

def main():
    mork_data_dir = os.getenv("MORK_DATA_DIR")
    if not mork_data_dir:
        print("MORK_DATA_DIR is not set", file=sys.stderr)
        return 1

    data_path = Path(mork_data_dir)
    if not data_path.is_dir():
        print(f"MORK_DATA_DIR does not exist: {mork_data_dir}", file=sys.stderr)
        return 1

    docker_cmd = [
        "docker", "run", "--rm",
        "-u", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{mork_data_dir}:{mork_data_dir}:rw",
        "-v", "/dev/shm:/dev/shm",
        "-w", mork_data_dir,
        "mork:latest",
        "/app/MORK/target/release/mork",
        *sys.argv[1:],
    ]

    try:
        result = subprocess.run(docker_cmd, check=True)
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    return result.returncode

if __name__ == "__main__":
    raise SystemExit(main())

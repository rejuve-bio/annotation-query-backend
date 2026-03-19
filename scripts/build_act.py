import os
import sys
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def get_mork_bin():
    default_wrapper = Path(__file__).resolve().parent / "mork_docker_wrapper.py"
    if default_wrapper.exists():
        return str(default_wrapper)
    raise RuntimeError("MORK docker wrapper not found.")

def get_metta_files(data_dir):
    data_path = Path(data_dir)
    metta_files = []
    
    type_defs = data_path / "type_defs.metta"
    if type_defs.exists():
        metta_files.append(type_defs)

    metta_files.extend(list(data_path.rglob("*nodes.metta")))
    metta_files.extend(list(data_path.rglob("*edges.metta")))
    
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

    print(f"1. Consolidating MeTTa fragments in {data_dir}...")
    with open(merged_metta, "w") as outfile:
        for metta_file in metta_files:
            with open(metta_file, "r") as infile:
                outfile.write(infile.read())
                outfile.write("\n")

    print(f"2. Compiling into binary Arena (ACT)...")
    convert_cmd = [
        mork_bin,
        "convert",
        "metta",
        "act",
        "$",
        "_1",
        str(merged_metta),
        str(output_act)
    ]
    
    try:
        subprocess.run(convert_cmd, capture_output=True, text=True, check=True)
        print("Conversion successful.")
    except subprocess.CalledProcessError as e:
        print(f"Error during conversion: {e.stderr}")
        if merged_metta.exists():
            merged_metta.unlink()
        return False

    print("3. Finalizing...")
    if merged_metta.exists():
        merged_metta.unlink()
    
    print(f"Done: {output_act}")
    return True

if __name__ == "__main__":
    default_data_dir = os.getenv("MORK_DATA_DIR")
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
    elif default_data_dir:
        target_dir = default_data_dir
    else:
        print("Error: MORK_DATA_DIR is not set and no directory was provided.")
        sys.exit(1)
    build_act(target_dir)

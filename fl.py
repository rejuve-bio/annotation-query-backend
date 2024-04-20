from flask import Flask, request, jsonify
from gene import generate_metta
from hyperon import MeTTa
import logging
# from hyperon import *
import json
import glob
import os
from typing import List


# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
metta = MeTTa()
# metta.run("!(bind! &space (new-space))")  # Binding a new space at app start

# Load data on startup
def load_dataset(path: str) -> None:
    if not os.path.exists(path):
        raise ValueError(f"Dataset path '{path}' does not exist.")

    # Recursively find all .metta files within the path
    paths = glob.glob(os.path.join(path, "**/*.metta"), recursive=True)
    if not paths:
        raise ValueError(f"No .metta files found in dataset path '{path}'.")

    for file_path in paths:
        if (file_path == "./Data/gencode/nodes.metta" or file_path == "./Data/uniprot/nodes.metta"):
            continue 
        print(f"Start loading dataset from '{file_path}'...")
        try:
            # Execute the import command for each .metta file found
            metta.run(f'!(import! &self {file_path})')
            print(f"Successfully loaded '{file_path}'.")
        except Exception as e:
            print(f"Error loading dataset from '{file_path}': {e}")

    print(f"Finished loading {len(paths)} datasets.")

load_dataset("./Data")

@app.route('/query', methods=['POST'])
def process_query():
    data = request.get_json()
    if not data or 'requests' not in data:
        return jsonify({"error": "Missing requests data"}), 400
    try:
        requests = data['requests']
        query_code = generate_metta(requests)
        result = metta.run(query_code) 
        logging.debug(f"Generated METTA Code: {query_code}")
        logging.debug(f"Query Result: {result}")
        logging.debug(f"out: {type(result)}")
        return jsonify({"query": query_code, "result": str(result)})
    except Exception as e:
        logging.error(f"Error processing the query: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)


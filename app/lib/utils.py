import pandas as pd
from pathlib import Path
import os
import logging
import re
import zipfile
from io import BytesIO

def adjust_file_path(file_path):
    parent_name = file_path.parents[1].name
    file_path = str(file_path)

    file_path = file_path.split(f'{parent_name}/', 1)[-1]

    return file_path

def generate_file_path(file_name, user_id, extension):
     # Remove all non-alphanumeric characters (including commas, hyphens, etc.) except spaces
    file_name = re.sub(r'[^\w\s]', '', file_name)

    # Replace spaces with hyphens
    file_name = '-'.join(file_name.split())
    file_name = f'{file_name}-{user_id}'
    file_path = Path(f'./public/{file_name}.{extension}').resolve()

    return file_path

def convert_to_csv(response, user_id, file_name):
    file_path = generate_file_path(file_name=file_name, user_id=user_id, extension='xls')
    # create public directory if it doesn't exit.
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    nodes, edges = response
    # Convert nodes and edges to DataFrames
    # Add sheet for each node
    # Convert to .xls file so that there is separate sheet for nodes and edges in a single file
    try:
        with pd.ExcelWriter(file_path) as writer:
            for key, _ in nodes.items():
                node = pd.json_normalize(nodes[key])
                node.columns = [col.replace('data.', '') for col in node.columns]
                node.to_excel(writer, sheet_name=f'{key}', index=False)
            for key, _ in edges.items():
                source = edges[key][0]['data']['source'].split(' ')[0]
                target = edges[key][0]['data']['target'].split(' ')[0]
                edge = pd.json_normalize(edges[key])
                edge.columns = [col.replace('data.', '') for col in edge.columns]
                edge.to_excel(writer, sheet_name=f'{source}-relationship-{target}', index=False)
    except Exception as e:
        print(e)
        os.remove(file_path)
        logging.error(e)
    return file_path


def extract_middle(words):
    words = words.split("_")
    if len(words) <= 2:
        return words[1] if len(words) == 2 else ""
    return "_".join(words[1:-1])

def convert_to_tsv(new_graph):
    output = BytesIO()

    try:
        nodes = new_graph['nodes']
        edges = new_graph['edges']

        # flatten all the nodes data, include only id, name, type
        node_records = []
        for node in nodes:
            data = node.get("data", {})
            filtered_data = {
                "id": data.get("id"),
                "name": data.get("name"),
                "type": data.get("type")
            }
            node_records.append(filtered_data)

        df_nodes = pd.json_normalize(node_records)

        # flatten all the edge data
        edge_records = []
        for edge in edges:
            data = edge.get("data", {})

            edge_records.append({
                "source": data.get("source"),
                "edge": data.get("target"),
                "label": data.get('label') or data.get('type') or ''
            })

        df_edges = pd.DataFrame(edge_records)

        # Write both to a zip file containing two .tsv files
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Write nodes.tsv
            node_buf = BytesIO()
            df_nodes.to_csv(node_buf, sep='\t', index=False)
            zipf.writestr('nodes.tsv', node_buf.getvalue())

            # Write edges.tsv
            edge_buf = BytesIO()
            df_edges.to_csv(edge_buf, sep='\t', index=False)
            zipf.writestr('edges.tsv', edge_buf.getvalue())

        output.seek(0)
        return output

    except Exception as e:
        print("E: ", e)
        return None

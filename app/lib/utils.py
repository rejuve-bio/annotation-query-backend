import pandas as pd
from pathlib import Path
import os
import logging
import re

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

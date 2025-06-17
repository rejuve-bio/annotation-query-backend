import pandas as pd
from pathlib import Path
import logging
import re
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

def convert_to_excel(response):
    output = BytesIO()
    try:
        nodes = response['nodes']
        edges = response['edges']

        # Build a map of node ID to name and type
        node_map = {
            node['data']['id']: {
                "name": node['data']['name'],
                "type": node['data']['type']
            }
            for node in nodes
        }

        # Accumulate nodes by type
        node_type_data = {}
        for node_data in nodes:
            actual_data = node_data['data']
            node_type = actual_data['type']

            if node_type not in node_type_data:
                node_type_data[node_type] = []

            if 'nodes' in actual_data and isinstance(actual_data['nodes'], list):
                df_nested = pd.json_normalize(actual_data['nodes'])
                df_nested['id'] = actual_data['id']
                if 'parent' in actual_data:
                    df_nested['parent'] = actual_data['parent']
                node_type_data[node_type].append(df_nested)
            else:
                df_node = pd.json_normalize(actual_data)
                node_type_data[node_type].append(df_node)

        # Accumulate edges by source-type -> target-type
        edge_type_data = {}
        for edge_data in edges:
            source_type = node_map[edge_data['data']['source']]['type']
            target_type = node_map[edge_data['data']['target']]['type']
            relationship_type = f'{source_type}-relationship-{target_type}'

            if relationship_type not in edge_type_data:
                edge_type_data[relationship_type] = []

            edge_df = pd.json_normalize(edge_data)
            edge_df.columns = [col.replace('data.', '') for col in edge_df.columns]
            edge_type_data[relationship_type].append(edge_df)

        # Write to Excel
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # One sheet per node type
            for node_type, dfs in node_type_data.items():
                combined_df = pd.concat(dfs, ignore_index=True)
                sheet_name = node_type[:31]  # Excel sheet name limit
                combined_df.to_excel(writer, sheet_name=sheet_name, index=False)

            # One sheet per edge relationship type
            for rel_type, dfs in edge_type_data.items():
                combined_df = pd.concat(dfs, ignore_index=True)
                sheet_name = rel_type[:31]  # Excel sheet name limit
                combined_df.to_excel(writer, sheet_name=sheet_name, index=False)

        output.seek(0)
        return output

    except Exception as e:
        logging.error(f"Error converting to Excel: {e}")
        return None

def extract_middle(words):
    words = words.split("_")
    if len(words) <= 2:
        return words[1] if len(words) == 2 else ""
    return "_".join(words[1:-1])

import logging
import os
import re
import tempfile
import zipfile
from io import BytesIO
from itertools import chain
from pathlib import Path

import pandas as pd
import yaml

logger = logging.getLogger(__name__)


def convert_to_excel(response):
    output = BytesIO()
    try:
        nodes = response["nodes"]
        edges = response["edges"]

        node_types = {node["data"]["id"]: node["data"]["type"] for node in nodes}

        # Accumulate nodes by type
        node_type_data = {}
        for node_data in nodes:
            actual_data = node_data["data"]
            node_type = actual_data["type"]

            if node_type not in node_type_data:
                node_type_data[node_type] = []

            if "nodes" in actual_data and isinstance(actual_data["nodes"], list):
                df_nested = pd.json_normalize(actual_data["nodes"])
                df_nested["id"] = actual_data["id"]
                if "parent" in actual_data:
                    df_nested["parent"] = actual_data["parent"]
                node_type_data[node_type].append(df_nested)
            else:
                df_node = pd.json_normalize(actual_data)
                node_type_data[node_type].append(df_node)

        # Accumulate edges by source-type -> target-type
        edge_type_data = {}
        for edge_data in edges:
            source_type = node_types.get(edge_data["data"]["source"], "unknown")
            target_type = node_types.get(edge_data["data"]["target"], "unknown")
            relationship_type = f"{source_type}-relationship-{target_type}"

            if relationship_type not in edge_type_data:
                edge_type_data[relationship_type] = []

            edge_df = pd.json_normalize(edge_data)
            edge_df.columns = [col.replace("data.", "") for col in edge_df.columns]
            edge_type_data[relationship_type].append(edge_df)

        # Write to Excel
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            if not node_type_data and not edge_type_data:
                pd.DataFrame().to_excel(writer, sheet_name="Results", index=False)
            for name, dfs in chain(node_type_data.items(), edge_type_data.items()):
                combined_df = pd.concat(dfs, ignore_index=True)
                # Leave room for openpyxl's suffix when truncated names collide.
                title = re.sub(r"[\\[\]:*?/]", "_", name)[:25] or "Results"
                worksheet = writer.book.create_sheet(title)
                combined_df.to_excel(writer, sheet_name=worksheet.title, index=False)

            for worksheet in writer.book.worksheets:
                for row in worksheet.iter_rows():
                    for cell in row:
                        if cell.data_type == "f":
                            cell.data_type = "s"

        output.seek(0)
        return output
    except Exception as e:
        logger.error(f"Error converting to Excel: {e}")
        return None


def extract_middle(words):
    words = words.split("_")
    if len(words) <= 2:
        return words[1] if len(words) == 2 else ""
    return "_".join(words[1:-1])


def convert_to_tsv(new_graph):
    output = BytesIO()

    try:
        nodes = new_graph["nodes"]
        edges = new_graph["edges"]

        # flatten all the nodes data, include only id, name, type
        node_records = []
        for node in nodes:
            data = node.get("data", {})
            filtered_data = {
                "id": data.get("id"),
                "name": data.get("name"),
                "type": data.get("type"),
            }
            node_records.append(filtered_data)

        df_nodes = pd.json_normalize(node_records)

        # flatten all the edge data
        edge_records = []
        for edge in edges:
            data = edge.get("data", {})

            edge_records.append(
                {
                    "source": data.get("source"),
                    "edge": data.get("target"),
                    "label": data.get("label") or data.get("type") or "",
                }
            )

        df_edges = pd.DataFrame(edge_records)

        # Write both to a zip file containing two .tsv files
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zipf:
            # Write nodes.tsv
            node_buf = BytesIO()
            df_nodes.to_csv(node_buf, sep="\t", index=False)
            zipf.writestr("nodes.tsv", node_buf.getvalue())

            # Write edges.tsv
            edge_buf = BytesIO()
            df_edges.to_csv(edge_buf, sep="\t", index=False)
            zipf.writestr("edges.tsv", edge_buf.getvalue())
            zipf.writestr("edges.tsv", edge_buf.getvalue())

        output.seek(0)
        return output

    except Exception as e:
        logger.error(f"Error converting to Excel: {e}")
        return None


def merge_schemas(primer_schema_path, species_schema_path, output_path=None):
    """
    Merges two BioCypher schema YAML files. Species schema entries override primer on conflict.

    Args:
        primer_schema_path (str): Path to the primer schema YAML file.
        species_schema_path (str): Path to the species-specific schema YAML file.
        output_path (str, optional): Destination path for the merged file.
            If None, a temporary file is created in the same directory as the primer schema.

    Returns:
        Path: Path to the merged schema file.
    """
    primer_schema_path = Path(primer_schema_path)
    species_schema_path = Path(species_schema_path)

    with open(primer_schema_path, "r") as f:
        primer_schema = yaml.safe_load(f)

    with open(species_schema_path, "r") as f:
        species_schema = yaml.safe_load(f)

    merged_schema = {**primer_schema, **species_schema}

    if output_path is not None:
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_fd = open(dest, "w")
        try:
            items = list(merged_schema.items())
            for i, (schema_name, schema_content) in enumerate(items):
                yaml.dump(
                    {schema_name: schema_content},
                    write_fd,
                    default_flow_style=False,
                    sort_keys=False,
                )
                if i < len(items) - 1:
                    write_fd.write("\n")
        finally:
            write_fd.close()
        return dest

    temp_fd, temp_path = tempfile.mkstemp(
        suffix=".yaml",
        dir=primer_schema_path.parent,
    )
    try:
        with os.fdopen(temp_fd, "w") as f:
            items = list(merged_schema.items())
            for i, (schema_name, schema_content) in enumerate(items):
                yaml.dump(
                    {schema_name: schema_content},
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                )
                if i < len(items) - 1:
                    f.write("\n")
    except Exception as e:
        Path(temp_path).unlink(missing_ok=True)
        raise RuntimeError(f"Error writing merged schema: {e}")

    return Path(temp_path)


def format_duration(ms):
    if ms is None:
        return None
    if ms < 1000:
        return f"{ms} ms"
    elif ms < 60_000:
        return f"{ms / 1000:.2f} sec"
    elif ms < 3_600_000:
        return f"{ms / 60_000:.2f} min"
    else:
        return f"{ms / 3_600_000:.2f} hr"

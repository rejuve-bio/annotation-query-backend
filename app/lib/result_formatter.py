"""
Unified Result Formatter

This module centralizes the processing and formatting of query results from
various database backends (Neo4j, MeTTa, Mork) into a unified JSON structure
suitable for the frontend graph visualization.
NOTE: for now it only tested on neo4j and only being used by neo4j
"""

from typing import TypedDict, List, Dict, Any, Tuple, Union
import neo4j
        
try:
    import graph_native as _graph_native
    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False

class LabelCount(TypedDict):
    label: str
    count: int

class ProcessedCount(TypedDict):
    node_count: int
    edge_count: int
    node_count_by_label: List[LabelCount]
    edge_count_by_label: List[LabelCount]

class NodeData(TypedDict):
    data: Dict[str, Any]

class EdgeData(TypedDict):
    data: Dict[str, Any]

class UnifiedGraphOutput(TypedDict):
    nodes: List[NodeData]
    edges: List[EdgeData]


class Result_Formatter:
    """
    Formats raw database results into a standardized graph or count representation.
    """

    NAMED_TYPES = [
        'gene_name', 'transcript_name', 'protein_name',
        'pathway_name', 'term_name'
    ]

    def format_result(self, data: Any, format_type: str, graph_components: Dict[str, Any], result_type: str = 'graph') -> Union[UnifiedGraphOutput, ProcessedCount, Dict[str, Any]]:
        """
        Main entry point for formatting database results.
        
        Args:
            data: Raw results from the database.
            format_type (str): The source database type ('neo4j', 'metta', 'mork').
            graph_components (dict): Metadata about the requested graph structure.
            result_type (str): The desired output format ('graph' or 'count').
            
        Returns:
            dict: The formatted result in the unified structure.
        """
        if result_type == 'graph':
            nodes, edges = self._process_graph(data, format_type, graph_components)
            return self._format_graph_output(nodes, edges)

        elif result_type == 'count':
            return self._process_count(data, format_type, graph_components)

        return {}

    def _process_graph(self, data: Any, format_type: str, graph_components: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Routes graph processing to the appropriate database-specific handler."""
        if format_type == "neo4j":
            return self._process_neo4j_graph(data, graph_components)

        elif format_type in ["mork", "metta"]:
            from app.services.metta.metta_seralizer import metta_seralizer

            results = data
            identifiers = None
            if isinstance(data, tuple) and len(data) == 2:
                results, identifiers = data

            tuples = metta_seralizer(results[0]) if isinstance(results, list) and results else []

            if not tuples and identifiers:
                return self._process_simple_graph(identifiers)

            return self._process_metta_graph(tuples, graph_components)

        raise ValueError(f"Unknown format_type for graph processing: {format_type}")

    def _process_neo4j_graph(self, results, graph_components):
        if _NATIVE_AVAILABLE:
            try:
                out = _graph_native.format_neo4j_graph(results, graph_components)
                # native already returns {"nodes": [...], "edges": [...]} with data-wrapped dicts
                return (
                    [n["data"] for n in out["nodes"]],
                    [e["data"] for e in out["edges"]],
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "Native Neo4j graph formatter failed; falling back to Python implementation"
                )

        nodes = []
        node_seen = {}
        edges = []
        edge_seen = set()

        properties_enabled = graph_components.get('properties', True)

        named_types_dict = {
            "gene": "gene_name",
            "transcript": "transcript_name",
            "protein": "protein_name",
            "pathway": "pathway_name",
            "term": "term_name",
        }

        def _register_node(item):
            label = list(item.labels)[0]
            node_id = f"{label} {item['id']}"
            if node_id in node_seen:
                return
            node_data = {"id": node_id, "type": label}
            for key, value in item.items():
                if properties_enabled:
                    if key not in ("id", "synonyms"):
                        node_data[key] = value
                elif key in self.NAMED_TYPES:
                    node_data["name"] = value
            if "name" not in node_data:
                fallback_key = named_types_dict.get(label.lower())
                if fallback_key and fallback_key in node_data:
                    node_data["name"] = node_data[fallback_key]
                else:
                    node_data["name"] = node_id
            nodes.append(node_data)
            node_seen[node_id] = node_data

        def _register_relationship(item):
            source_label = list(item.start_node.labels)[0]
            target_label = list(item.end_node.labels)[0]
            source_id = f"{source_label} {item.start_node['id']}"
            target_id = f"{target_label} {item.end_node['id']}"
            sig = f"{source_id} - {item.type} - {target_id}"
            if sig in edge_seen:
                return
            edge_seen.add(sig)
            edge_data = {
                "edge_id": f"{source_label}_{item.type}_{target_label}",
                "label": item.type,
                "source": source_id,
                "target": target_id,
            }
            for key, value in item.items():
                edge_data["source_data" if key == "source" else key] = value
            edges.append(edge_data)
            # Always register endpoint nodes too
            _register_node(item.start_node)
            _register_node(item.end_node)

        for record in results:
            for item in record.values():
                if isinstance(item, neo4j.graph.Node):
                    _register_node(item)
                elif isinstance(item, neo4j.graph.Relationship):
                    _register_relationship(item)
                elif isinstance(item, list):
                    # CALL subquery path: list of maps {node_var: Node, pred_var: Rel}
                    for entry in item:
                        if isinstance(entry, dict):
                            for val in entry.values():
                                if isinstance(val, neo4j.graph.Node):
                                    _register_node(val)
                                elif isinstance(val, neo4j.graph.Relationship):
                                    _register_relationship(val)
                        elif isinstance(entry, neo4j.graph.Node):
                            _register_node(entry)
                        elif isinstance(entry, neo4j.graph.Relationship):
                            _register_relationship(entry)

        return nodes, edges

    def _process_metta_graph(self, tuples: List[Tuple], graph_components: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Extracts nodes and edges from serialized MeTTa/Mork tuples."""
        nodes_map = {}
        rels_map = {}

        properties_enabled = graph_components.get('properties', True)

        for match in tuples:
            graph_attr = match[0]
            parts = match[1:]

            if graph_attr == "node":
                prop = parts[0]
                src_type = parts[1]
                src_value = parts[2]
                target_val = parts[3:]

                node_id = f"{src_type} {src_value}"

                if node_id not in nodes_map:
                    nodes_map[node_id] = {"id": node_id, "type": src_type}

                if properties_enabled:
                    nodes_map[node_id][prop] = target_val
                elif prop in self.NAMED_TYPES:
                    nodes_map[node_id]['name'] = target_val

                nodes_map[node_id].pop('synonyms', None)

            elif graph_attr == "edge":
                prop = parts[0]
                label = parts[1]
                src_type = parts[2]
                src_id = parts[3]
                tgt_type = parts[4]
                tgt_id = parts[5]
                val = ' '.join(parts[6:])

                rel_key = (label, src_type, src_id, tgt_type, tgt_id)
                if rel_key not in rels_map:
                    rels_map[rel_key] = {
                        "edge_id": f"{src_type}_{label}_{tgt_type}",
                        "label": label,
                        "source": f"{src_type} {src_id}",
                        "target": f"{tgt_type} {tgt_id}",
                    }

                rels_map[rel_key]["source_data" if prop == "source" else prop] = val

        return list(nodes_map.values()), list(rels_map.values())

    def _format_graph_output(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> UnifiedGraphOutput:
        """Wraps standard node and edge dictionaries into the final unified format."""
        return {
            "nodes": [{"data": node} for node in nodes],
            "edges": [{"data": edge} for edge in edges],
        }

    def _process_count(self, data: Any, format_type: str, graph_components: Dict[str, Any]) -> ProcessedCount:
        """Routes count processing to the appropriate database-specific handler."""
        if format_type == "neo4j":
            return self._process_neo4j_count(data, graph_components)
        elif format_type in ["mork", "metta"]:
            return self._process_metta_mork_count(data)

        raise ValueError(f"Unknown format_type for count processing: {format_type}")

    def _process_neo4j_count(self, results, graph_components):
        if not results:
            return {}
        
        if _NATIVE_AVAILABLE:
            try:
                return _graph_native.format_neo4j_count(results, graph_components)
            except Exception as e:
                print("PROCESS NEO4j COUNT------------------------", flush=True)
                print(e, flush=True)
                pass  

        node_and_edge_count = results[0]
        count_by_label = results[1] if len(results) > 1 else {}

        node_count = node_and_edge_count.get('total_nodes', 0) if node_and_edge_count else 0
        edge_count = node_and_edge_count.get('total_edges', 0) if node_and_edge_count else 0

        node_agg = {n['type']: 0 for n in graph_components.get('nodes', [])}
        edge_agg = {
            p['type'].replace(" ", "_").lower(): 0
            for p in graph_components.get('predicates', [])
        }

        if count_by_label:
            for key, value in count_by_label.items():
                label_key = '_'.join(key.split('_')[1:])
                if label_key in node_agg:
                    node_agg[label_key] += value
                if label_key in edge_agg:
                    edge_agg[label_key] += value

        return {
            "node_count": node_count,
            "edge_count": edge_count,
            "node_count_by_label": [{'label': k, 'count': v} for k, v in node_agg.items()],
            "edge_count_by_label": [{'label': k, 'count': v} for k, v in edge_agg.items()],
        }

    def _process_metta_mork_count(self, results: Any) -> ProcessedCount:
        """Aggregates node and edge counts from MeTTa/Mork query results."""
        from app.services.mork import get_total_counts, get_count_by_label

        meta_data = {}
        if results and results[0]:
            meta_data.update(get_total_counts(results[0]))
        if len(results) > 1 and results[1]:
            meta_data.update(get_count_by_label(results[1]))
        return meta_data

    def _process_simple_graph(self, results: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Creates a basic graph structure from identifiers when property fetching yields no results.
        """
        nodes_seen = set()
        nodes = []
        edges = []

        for result in results:
            if not result:
                continue

            source = result.get('source')
            target = result.get('target')
            predicate = result.get('predicate')

            for node_id in [source, target]:
                if node_id and node_id not in nodes_seen:
                    nodes_seen.add(node_id)
                    nodes.append({
                        "id": node_id,
                        "type": node_id.split(' ')[0],
                        "name": node_id
                    })

            if source and target and predicate:
                source_label = source.split(' ')[0]
                target_label = target.split(' ')[0]
                edges.append({
                    "id": f"{source_label}_{predicate}_{target_label}_{len(edges)}",
                    "edge_id": f"{source_label}_{predicate}_{target_label}",
                    "label": predicate,
                    "source": source,
                    "target": target,
                })

        return nodes, edges
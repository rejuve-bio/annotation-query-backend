from typing import List
import logging
from dotenv import load_dotenv
import neo4j
from app.services.query_generator_interface import QueryGeneratorInterface
from neo4j import GraphDatabase
import glob
import os
from neo4j.graph import Node, Relationship

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
 
from typing import List, Dict, Any, Union, Optional

class CypherQueryGenerator:
    def __init__(self, dataset_path: str) -> None:
        self.driver = GraphDatabase.driver(
            os.getenv('NEO4J_URI'),
            auth=(os.getenv('NEO4J_USERNAME'), os.getenv('NEO4J_PASSWORD'))
        )
        # self.dataset_path = dataset_path
        # self.load_dataset(self.dataset_path)

    def close(self) -> None:
        self.driver.close()

    def load_dataset(self, path: str) -> None:
        if not os.path.exists(path):
            raise ValueError(f"Dataset path '{path}' does not exist.")

        paths: List[str] = glob.glob(os.path.join(path, "**/*.cypher"), recursive=True)
        if not paths:
            raise ValueError(f"No .cypher files found in dataset path '{path}'.")

        nodes_paths: List[str] = [p for p in paths if p.endswith("nodes.cypher")]
        edges_paths: List[str] = [p for p in paths if p.endswith("edges.cypher")]

        def process_files(file_paths: List[str], file_type: str) -> None:
            for file_path in file_paths:
                print(f"Start loading {file_type} dataset from '{file_path}'...")
                try:
                    with open(file_path, 'r') as file:
                        data = file.read()
                        for line in data.splitlines():
                            self.run_query(line)
                except Exception as e:
                    print(f"Error loading {file_type} dataset from '{file_path}': {e}")

        process_files(nodes_paths, "nodes")
        process_files(edges_paths, "edges")
        print(f"Finished loading {len(nodes_paths)} nodes and {len(edges_paths)} edges datasets.")

    def run_query(self, query_code: Union[str, List[str]], run_count: bool = True) -> List[Any]:
        results: List[Any] = []
        find_query, total_count_query, label_count_query = (query_code, None, None) if isinstance(query_code, str) else query_code[:3]

        with self.driver.session() as session:
            results.append(list(session.run(find_query)))
        
        if run_count:
            for query in [total_count_query, label_count_query]:
                if query:
                    try:
                        with self.driver.session() as session:
                            results.append(list(session.run(query)))
                    except:
                        results.append([])
        
        return results

    def query_Generator(self, requests: Dict[str, Any], node_map: Dict[str, Any], limit: Optional[int] = None, node_only: bool = False) -> List[str]:
        nodes: List[Dict[str, Any]] = requests['nodes']
        predicate_map: Dict[str, Any] = {}
        
        predicates: Optional[List[Dict[str, Any]]] = requests.get("predicates")
        if predicates:
            for predicate in predicates:
                predicate_map[predicate['predicate_id']] = predicate

        cypher_queries: List[str] = []
        match_no_preds, return_no_preds, where_no_preds = [], [], []
        match_preds, return_preds, where_preds = [], [], []
        node_ids, used_nodes = set(), set()
        
        if not predicates:
            list_of_node_ids = []
            for node in nodes:
                var_name = f"{node['node_id']}"
                match_no_preds.append(self.match_node(node, var_name))
                if node['properties']:
                    where_no_preds.extend(self.where_construct(node, var_name))
                return_no_preds.append(var_name)
                list_of_node_ids.append(var_name)
            
            cypher_query = self.construct_optional_clause(match_no_preds, return_no_preds, where_no_preds, limit) if node_only else self.construct_clause(match_no_preds, return_no_preds, where_no_preds, limit)
            cypher_queries.append(cypher_query)
        
        return cypher_queries

    def construct_clause(self, match_clause: List[str], return_clause: List[str], where_no_preds: List[str], limit: Optional[int]) -> str:
        match_clause_str = f"MATCH {', '.join(match_clause)}"
        return_clause_str = f"RETURN {', '.join(return_clause)}"
        where_clause = f"WHERE {' AND '.join(where_no_preds)}" if where_no_preds else ""
        return f"{match_clause_str} {where_clause} {return_clause_str} {self.limit_query(limit)}".strip()

    def construct_optional_clause(self, match_clause: List[str], return_clause: List[str], where_no_preds: List[str], limit: Optional[int]) -> str:
        optional_clause = ""

        for match in match_clause:
            optional_clause += f"OPTIONAL MATCH {match} "

        return_clause = f"RETURN {', '.join(return_clause)}"
        if len(where_no_preds) > 0:
            where_clause = f"WHERE {' AND '.join(where_no_preds)}"
            return f"{optional_clause} {where_clause} {return_clause} {self.limit_query(limit)}"
        return f"{optional_clause} {return_clause} {self.limit_query(limit)}"
    
    def construct_union_clause(self, query_clauses: Dict[str, List[str]], limit: Optional[int]) -> str:
        clauses: Dict[str, str] = {
            'match_no_clause': '', 'where_no_clause': '', 'return_no_clause': '',
            'match_clause': '', 'where_clause': '', 'return_clause': ''
        }
        
        if 'match_no_preds' in query_clauses and query_clauses['match_no_preds']:
            clauses['match_no_clause'] = f"MATCH {', '.join(query_clauses['match_no_preds'])}"
            if 'where_no_preds' in query_clauses and query_clauses['where_no_preds']:
                clauses['where_no_clause'] = f"WHERE {' AND '.join(query_clauses['where_no_preds'])}"
            clauses['return_no_clause'] = "RETURN " + ', '.join(query_clauses['return_no_preds'])
        
        if 'match_preds' in query_clauses and query_clauses['match_preds']:
            clauses['match_clause'] = f"MATCH {', '.join(query_clauses['match_preds'])}"
            if 'where_preds' in query_clauses and query_clauses['where_preds']:
                clauses['where_clause'] = f"WHERE {' AND '.join(query_clauses['where_preds'])}"
            clauses['return_clause'] = "RETURN " + ', '.join(query_clauses['full_return_preds'])
        
        return self.construct_call_clause(clauses, limit)

    def construct_count_clause(self, query_clauses: Dict[str, List[str]], node_map: Dict[str, Dict[str, str]], predicate_map: Dict[str, Dict[str, str]]) -> List[str]:
        match_no_clause, where_no_clause, match_clause, where_clause = '', '', '', ''
        return_preds: List[str] = []
        collect_node_and_edge = ''
        
        if 'match_no_preds' in query_clauses and query_clauses['match_no_preds']:
            match_no_clause = f"MATCH {', '.join(query_clauses['match_no_preds'])}"
            if 'where_no_preds' in query_clauses and query_clauses['where_no_preds']:
                where_no_clause = f"WHERE {' AND '.join(query_clauses['where_no_preds'])}"
        
        if 'match_preds' in query_clauses and query_clauses['match_preds']:
            match_clause = f"MATCH {', '.join(query_clauses['match_preds'])}"
            if 'where_preds' in query_clauses and query_clauses['where_preds']:
                where_clause = f"WHERE {' AND '.join(query_clauses['where_preds'])}"
        
        if "return_preds" in query_clauses:
            return_preds = query_clauses['return_preds']
        
        for node_ids in query_clauses['list_of_node_ids']:
            collect_node_and_edge += f"COLLECT(DISTINCT {node_ids}) AS {node_ids}_count, "
        
        if "return_preds" in query_clauses:
            for predicate in query_clauses['predicates']:
                predicate_id = predicate['predicate_id']
                collect_node_and_edge += f"COLLECT(DISTINCT {predicate_id}) AS {predicate_id}_count, "
        
        collect_node_and_edge = f"WITH {collect_node_and_edge.rstrip(', ')}"
        
        combined_nodes = ' + '.join([f"{var}_count" for var in query_clauses['list_of_node_ids']])
        combined_edges = ' + '.join([f"{var}_count" for var in return_preds]) if return_preds else None
        
        with_clause = f"WITH {combined_nodes} AS combined_nodes {f', {combined_edges} AS combined_edges' if combined_edges else ''}"
        unwind_clause = "UNWIND combined_nodes AS nodes"
        return_clause = f"RETURN COUNT(DISTINCT nodes) AS total_nodes {', SIZE(combined_edges) AS total_edges ' if combined_edges else ''}"
        
        total_count = f"""
            {match_no_clause}
            {where_no_clause}
            {match_clause}
            {where_clause}
            {collect_node_and_edge}
            {with_clause}
            {unwind_clause}
            {return_clause}
        """
        
        label_count_query = """
            {match_no_clause} {where_no_clause} {return_clause}
        """
        
        return [total_count, label_count_query]

    def limit_query(self, limit: Optional[int]) -> str:
        curr_limit = min(1000, int(limit)) if limit else 1000
        return f"LIMIT {curr_limit}"
    
    def construct_call_clause(self, clauses: Dict[str, str], limit: Optional[int] = None) -> str:
        if not ("match_no_clause" in clauses or "match_clause" in clauses):
            raise Exception("Either 'match_clause' or 'match_no_clause' must be present")
        
        call_clauses = []
        if "match_no_clause" in clauses and clauses["match_no_clause"]:
            call_clauses.append(
                f'CALL() {{ {clauses["match_no_clause"]} {clauses.get("where_no_clause", "")} {clauses["return_no_clause"]} {self.limit_query(limit) if "return_count_sum" not in clauses else ""} }}'
            )
        if "match_clause" in clauses and clauses["match_clause"]:
            call_clauses.append(
                f'CALL() {{ {clauses["match_clause"]} {clauses.get("where_clause", "")} {clauses["return_clause"]} {self.limit_query(limit) if "return_count_sum" not in clauses else ""} }}'
            )
        call_clauses.append(clauses.get("return_count_sum", "RETURN *"))
        return " ".join(call_clauses)
    
    def match_node(self, node: Dict[str, str], var_name: str) -> str:
        return f"({var_name}:{node['type']} {{id: '{node['id']}'}})" if node['id'] else f"({var_name}:{node['type']})"
    
    def where_construct(self, node: Dict[str, Union[str, Dict[str, str]]], var_name: str) -> List[str]:
        if node['id']: return []
        return [f"{var_name}.{key} =~ '(?i){property}'" for key, property in node['properties'].items()]
    
    def parse_neo4j_results(self, results: dict, graph_components: dict) -> dict:
        nodes, edges, _, _, meta_data = self.process_result(results, graph_components)
        return {"nodes": nodes, "edges": edges, **meta_data}
    
    def parse_and_serialize(self, input_data: dict, schema: dict, graph_components: dict) -> dict:
        return self.parse_neo4j_results(input_data, graph_components)
    
    def convert_to_dict(self, results: dict, schema: dict, graph_components: dict) -> tuple:
        graph_components['properties'] = True
        _, _, node_dict, edge_dict, _ = self.process_result(results, graph_components)
        return node_dict, edge_dict

     
    

    def process_result(self, results,graph_components):
        match_result = results[0]
        node_count_by_label = []
        edge_count_by_label = []
        node_count = 0
        edge_count = 0
        node_and_edge_count = []
        count_by_label = []

        if len(results) > 2:
            node_and_edge_count = results[1]
        if len(results) > 1:
            count_by_label = results[2]

        nodes = []
        edges = []
        node_dict = {}
        node_to_dict = {}
        edge_to_dict = {}
        node_type = set()
        edge_type = set()
        visited_relations = set()

        named_types = ['gene_name', 'transcript_name', 'protein_name', 'pathway_name', 'term_name']

        for record in match_result:
            for item in record.values():
                if isinstance(item, neo4j.graph.Node):
                    node_id = f"{list(item.labels)[0]} {item['id']}"
                    if node_id not in node_dict:
                        node_data = {
                            "data": {
                                "id": node_id,
                                "type": list(item.labels)[0],
                            }
                        }

                        for key, value in item.items():
                            if graph_components['properties']:
                                if key != "id" and key != "synonyms":
                                    node_data["data"][key] = value
                            else:
                                if key in named_types:
                                    node_data["data"]["name"] = value
                        if "name" not in node_data["data"]:
                            node_data["data"]["name"] = node_id
                        nodes.append(node_data)
                        if node_data["data"]["type"] not in node_type:
                            node_type.add(node_data["data"]["type"])
                            node_to_dict[node_data['data']['type']] = []
                        node_to_dict[node_data['data']['type']].append(node_data)
                        node_dict[node_id] = node_data
                elif isinstance(item, neo4j.graph.Relationship):
                    source_label = list(item.start_node.labels)[0]
                    target_label = list(item.end_node.labels)[0]
                    source_id = f"{list(item.start_node.labels)[0]} {item.start_node['id']}"
                    target_id = f"{list(item.end_node.labels)[0]} {item.end_node['id']}"
                    edge_data = {
                        "data": {
                            # "id": item.id,
                            "edge_id": f"{source_label}_{item.type}_{target_label}",
                            "label": item.type,
                            "source": source_id,
                            "target": target_id,
                        }
                    }
                    temp_relation_id = f"{source_id} - {item.type} - {target_id}"
                    if temp_relation_id in visited_relations:
                        continue
                    visited_relations.add(temp_relation_id)

                    for key, value in item.items():
                        if key == 'source':
                            edge_data["data"]["source_data"] = value
                        else:
                            edge_data["data"][key] = value
                    edges.append(edge_data)
                    if edge_data["data"]["label"] not in edge_type:
                        edge_type.add(edge_data["data"]["label"])
                        edge_to_dict[edge_data['data']['label']] = []
                    edge_to_dict[edge_data['data']['label']].append(edge_data)

        if node_and_edge_count:
            for count_record in node_and_edge_count:
                node_count += count_record.get('total_nodes', 0)
                edge_count += count_record.get('total_edges', 0)

        if count_by_label:
            # build edge type set
            node_count_aggregate = {}
            ege_count_aggregate = {}

            # initialize node count aggreate dictionary where the key is the label.
            for node in graph_components['nodes']:
                node_type = node['type']
                node_count_aggregate[node_type] = {'count': 0}

            # initialize edge count aggreate dictionary where the key is the label.
            for predicate in graph_components['predicates']:
                edge_type = predicate['type'].replace(" ", "_").lower()
                ege_count_aggregate[edge_type] = {'count': 0}

            for count_record in count_by_label:
                # update node count aggregate dictionary with the count of each label
                for key, value in count_record.items():
                    node_type_key = '_'.join(key.split('_')[1:])
                    if node_type_key in node_count_aggregate:
                        node_count_aggregate[node_type_key]['count'] += value

                # update edge count aggregate dictionary with the count of each label
                for key, value in count_record.items():
                    edge_type_key = '_'.join(key.split('_')[1:])
                    if edge_type_key in ege_count_aggregate:
                        ege_count_aggregate[edge_type_key]['count'] += value

                # update the way node count by label and edge count by label are represented
                for key, value in node_count_aggregate.items():
                    node_count_by_label.append({'label': key, 'count': value['count']})
                for key, value in ege_count_aggregate.items(): 
                    edge_count_by_label.append({'label': key, 'count': value['count']})

        meta_data = {
            "node_count": node_count,
            "edge_count": edge_count,
            "node_count_by_label": node_count_by_label,
            "edge_count_by_label": edge_count_by_label
        }
    
        return (nodes, edges, node_to_dict, edge_to_dict, meta_data)

    def parse_id(self, request):
        nodes = request["nodes"]
        named_types = {"gene": "gene_name", "transcript": "transcript_name"}
        prefixes = ["ensg", "enst"]
 
        for node in nodes:
            is_named_type = node['type'] in named_types
            id = node["id"].lower()
            is_name_as_id = all(not id.startswith(prefix) for prefix in prefixes)
            no_id = node["id"] != ''
            if is_named_type and is_name_as_id and no_id:
                node_type = named_types[node['type']]
                node['properties'][node_type] = node["id"]
                node['id'] = ''
            node["id"] = node["id"].lower()
        return request
    

    def process_result(self, results: List[Any], graph_components: Dict[str, Any]) -> Tuple[
        List[Dict[str, Any]],  # Nodes
        List[Dict[str, Any]],  # Edges
        Dict[str, List[Dict[str, Any]]],  # Node to dict
        Dict[str, List[Dict[str, Any]]],  # Edge to dict
        Dict[str, Any]  # Metadata
    ]:
        match_result = results[0]
        node_count_by_label: List[Dict[str, Any]] = []
        edge_count_by_label: List[Dict[str, Any]] = []
        node_count: int = 0
        edge_count: int = 0
        node_and_edge_count: List[Dict[str, int]] = []
        count_by_label: List[Dict[str, int]] = []

        if len(results) > 2:
            node_and_edge_count = results[1]
        if len(results) > 1:
            count_by_label = results[2]

        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        node_dict: Dict[str, Dict[str, Any]] = {}
        node_to_dict: Dict[str, List[Dict[str, Any]]] = {}
        edge_to_dict: Dict[str, List[Dict[str, Any]]] = {}
        node_type: set = set()
        edge_type: set = set()
        visited_relations: set = set()

        named_types = ['gene_name', 'transcript_name', 'protein_name', 'pathway_name', 'term_name']

        for record in match_result:
            for item in record.values():
                if isinstance(item, neo4j.graph.Node):
                    node_id = f"{list(item.labels)[0]} {item['id']}"
                    if node_id not in node_dict:
                        node_data: Dict[str, Any] = {
                            "data": {
                                "id": node_id,
                                "type": list(item.labels)[0],
                            }
                        }

                        for key, value in item.items():
                            if graph_components['properties']:
                                if key != "id" and key != "synonyms":
                                    node_data["data"][key] = value
                            else:
                                if key in named_types:
                                    node_data["data"]["name"] = value
                        if "name" not in node_data["data"]:
                            node_data["data"]["name"] = node_id
                        nodes.append(node_data)
                        if node_data["data"]["type"] not in node_type:
                            node_type.add(node_data["data"]["type"])
                            node_to_dict[node_data['data']['type']] = []
                        node_to_dict[node_data['data']['type']].append(node_data)
                        node_dict[node_id] = node_data
                elif isinstance(item, neo4j.graph.Relationship):
                    source_label = list(item.start_node.labels)[0]
                    target_label = list(item.end_node.labels)[0]
                    source_id = f"{source_label} {item.start_node['id']}"
                    target_id = f"{target_label} {item.end_node['id']}"
                    edge_data: Dict[str, Any] = {
                        "data": {
                            "edge_id": f"{source_label}_{item.type}_{target_label}",
                            "label": item.type,
                            "source": source_id,
                            "target": target_id,
                        }
                    }
                    temp_relation_id = f"{source_id} - {item.type} - {target_id}"
                    if temp_relation_id in visited_relations:
                        continue
                    visited_relations.add(temp_relation_id)

                    for key, value in item.items():
                        if key == 'source':
                            edge_data["data"]["source_data"] = value
                        else:
                            edge_data["data"][key] = value
                    edges.append(edge_data)
                    if edge_data["data"]["label"] not in edge_type:
                        edge_type.add(edge_data["data"]["label"])
                        edge_to_dict[edge_data['data']['label']] = []
                    edge_to_dict[edge_data['data']['label']].append(edge_data)

        if node_and_edge_count:
            for count_record in node_and_edge_count:
                node_count += count_record.get('total_nodes', 0)
                edge_count += count_record.get('total_edges', 0)

        if count_by_label:
            node_count_aggregate: Dict[str, Dict[str, int]] = {}
            edge_count_aggregate: Dict[str, Dict[str, int]] = {}

            for node in graph_components['nodes']:
                node_type = node['type']
                node_count_aggregate[node_type] = {'count': 0}

            for predicate in graph_components['predicates']:
                edge_type = predicate['type'].replace(" ", "_").lower()
                edge_count_aggregate[edge_type] = {'count': 0}

            for count_record in count_by_label:
                for key, value in count_record.items():
                    node_type_key = '_'.join(key.split('_')[1:])
                    if node_type_key in node_count_aggregate:
                        node_count_aggregate[node_type_key]['count'] += value

                for key, value in count_record.items():
                    edge_type_key = '_'.join(key.split('_')[1:])
                    if edge_type_key in edge_count_aggregate:
                        edge_count_aggregate[edge_type_key]['count'] += value

                for key, value in node_count_aggregate.items():
                    node_count_by_label.append({'label': key, 'count': value['count']})
                for key, value in edge_count_aggregate.items():
                    edge_count_by_label.append({'label': key, 'count': value['count']})

        meta_data: Dict[str, Any] = {
            "node_count": node_count,
            "edge_count": edge_count,
            "node_count_by_label": node_count_by_label,
            "edge_count_by_label": edge_count_by_label
        }

        return nodes, edges, node_to_dict, edge_to_dict, meta_data

    def parse_id(self, request: Dict[str, Any]) -> Dict[str, Any]:
        nodes = request["nodes"]
        named_types: Dict[str, str] = {"gene": "gene_name", "transcript": "transcript_name"}
        prefixes: List[str] = ["ensg", "enst"]

        for node in nodes:
            is_named_type: bool = node['type'] in named_types
            node_id: str = node["id"].lower()
            is_name_as_id: bool = all(not node_id.startswith(prefix) for prefix in prefixes)
            no_id: bool = node["id"] != ''
            
            if is_named_type and is_name_as_id and no_id:
                node_type = named_types[node['type']]
                node['properties'][node_type] = node["id"]
                node['id'] = ''
            node["id"] = node["id"].lower()

        return request

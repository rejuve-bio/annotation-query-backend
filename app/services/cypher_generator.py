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

class CypherQueryGenerator(QueryGeneratorInterface):
    def __init__(self, dataset_path: str):
        self.driver = GraphDatabase.driver(
            os.getenv('NEO4J_URI'),
            auth=(os.getenv('NEO4J_USERNAME'), os.getenv('NEO4J_PASSWORD'))
        )
        # self.dataset_path = dataset_path
        # self.load_dataset(self.dataset_path)

    def close(self):
        self.driver.close()

    def load_dataset(self, path: str) -> None:
        if not os.path.exists(path):
            raise ValueError(f"Dataset path '{path}' does not exist.")

        paths = glob.glob(os.path.join(path, "**/*.cypher"), recursive=True)
        if not paths:
            raise ValueError(f"No .cypher files found in dataset path '{path}'.")

        # Separate nodes and edges
        nodes_paths = [p for p in paths if p.endswith("nodes.cypher")]
        edges_paths = [p for p in paths if p.endswith("edges.cypher")]

        # Helper function to process files
        def process_files(file_paths, file_type):
            for file_path in file_paths:
                logger.info(f"Start loading {file_type} dataset from '{file_path}'...")
                try:
                    with open(file_path, 'r') as file:
                        data = file.read()
                        for line in data.splitlines():
                            self.run_query(line)
                except Exception as e:
                    logger.error(f"Error loading {file_type} dataset from '{file_path}': {e}")

        # Process nodes and edges files
        process_files(nodes_paths, "nodes")
        process_files(edges_paths, "edges")

        logger.info(f"Finished loading {len(nodes_paths)} nodes and {len(edges_paths)} edges datasets.")

    def run_query(self, query_code):
        if isinstance(query_code, list):
            query_code = query_code[0]
        with self.driver.session() as session:
            results = session.run(query_code)
            result_list = [record for record in results]
            return result_list

    def query_Generator(self, requests,node_map):
        nodes = requests['nodes']
        predicates = requests['predicates']

        cypher_queries = []
        all_valid = True
        # node_dict = {node['node_id']: node for node in nodes}

        if all_valid:
            match_clauses = []
            return_clauses = []

            # Track nodes that are included in relationships
            used_nodes = set()
            if not predicates:
                # Case when there are no predicates
                for node in nodes:
                    var_name = f"n_{node['node_id']}"
                    match_clauses.append(self.match_node(node, var_name))
                    return_clauses.append(var_name)
            else:
                for i, predicate in enumerate(predicates):
                    predicate_type = predicate['type'].replace(" ", "_")
                    source_node = node_map[predicate['source']]
                    target_node = node_map[predicate['target']]

                    if i == 0:
                        source_var = 's0'
                        source_match = self.match_node(source_node, source_var)
                        match_clauses.append(source_match)
                    else:
                        source_var = f"t{i-1}"

                    target_var = f"t{i}"
                    target_match = self.match_node(target_node, target_var)

                    match_clauses.append(f"({source_var})-[r{i}:{predicate_type}]->{target_match}")
                    return_clauses.append(f"r{i}")

                    used_nodes.add(predicate['source'])
                    used_nodes.add(predicate['target'])
                
                for node_id, node in node_map.items():
                    if node_id not in used_nodes:
                        var_name = f"n_{node_id}"
                        match_clauses.append(self.match_node(node, var_name))
                        return_clauses.append(var_name)

                return_clauses.extend([f"s0"] + [f"t{i}" for i in range(len(predicates))])

            match_clause = "MATCH " + ", ".join(match_clauses)
            return_clause = "RETURN " + ", ".join(return_clauses)
            cypher_query = f"{match_clause} {return_clause}"
            cypher_queries.append(cypher_query)
        else:
            logging.debug("Processing stopped due to invalid request.")
        return cypher_queries

    
    def match_node(self, node, var_name):
        if node['id']:
            return f"({var_name}:{node['type']} {{id: '{node['id']}'}})"
        elif node['properties']:
            properties = ", ".join([f"{k}: '{v}'" for k, v in node['properties'].items()])
            return f"({var_name}:{node['type']} {{{properties}}})"
        else:
            return f"({var_name}:{node['type']})"

    def parse_neo4j_results(self, results):
        nodes = []
        edges = []
        node_dict = {}

        for record in results:
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
                            if key != "id" and key!= "synonyms":
                                node_data["data"][key] = value
                        nodes.append(node_data)
                        node_dict[node_id] = node_data
                elif isinstance(item, neo4j.graph.Relationship):
                    source_id = f"{list(item.start_node.labels)[0]} {item.start_node['id']}"
                    target_id = f"{list(item.end_node.labels)[0]} {item.end_node['id']}"
                    edge_data = {
                        "data": {
                            # "id": item.id,
                            "label": item.type,
                            "source": source_id,
                            "target": target_id,
                        }
                    }

                    for key, value in item.items():
                        if key == 'source':
                            edge_data["data"]["source_data"] = value
                        else:
                            edge_data["data"][key] = value
                    edges.append(edge_data)

        return {"nodes": nodes, "edges": edges}

    def parse_and_serialize(self, input,schema):
        parsed_result = self.parse_neo4j_results(input)
        return parsed_result["nodes"], parsed_result["edges"]




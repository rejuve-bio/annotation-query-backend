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
        self.return_union = []
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

    def query_Generator(self, requests, node_map):
        nodes = requests['nodes']

        if "predicates" in requests:
            predicates = requests["predicates"]
        else:
            predicates = None

        cypher_queries = []
        # node_dict = {node['node_id']: node for node in nodes}

        match_preds = []
        return_preds = []
        match_no_preds = []
        return_no_preds = []
        optional_match_preds = [] # for parent nodes  
        optional_return_preds = []
        optional_return_union = []


    
        # Track nodes that are included in relationships
        used_nodes = set()
        if not predicates:
            # Case when there are no predicates
            for node in nodes:
                var_name = f"n_{node['node_id']}"
                match_no_preds.append(self.match_node(node, var_name))
                return_no_preds.append(var_name)
            cypher_query = self.construct_clause(match_no_preds, return_no_preds)
            cypher_queries.append(cypher_query)
        else:
            for i, predicate in enumerate(predicates):
                predicate_type = predicate['type'].replace(" ", "_").lower()
                source_node = node_map[predicate['source']]
                target_node = node_map[predicate['target']]

                if i == 0:
                    source_var = 's0'
                    source_match = self.match_node(source_node, source_var)
                    match_preds.append(source_match)
                else:
                    source_var = f"t{i-1}"

                target_var = f"t{i}"
                target_match = self.match_node(target_node, target_var)
                optional_n,return_n, return_union = self.optional_parent_match(target_var)
                optional_match_preds.append(optional_n)   
                optional_return_preds.append(return_n)
                optional_return_union.append(return_union)

                match_preds.append(f"({source_var})-[r{i}:{predicate_type}]->{target_match}")
                return_preds.append(f"r{i}")

                used_nodes.add(predicate['source'])
                used_nodes.add(predicate['target'])

            for node_id, node in node_map.items():
                if node_id not in used_nodes:
                    var_name = f"n_{node_id}"
                    match_no_preds.append(self.match_node(node, var_name))
                    return_no_preds.append(var_name)
            # CASE WHEN {var_name} IS NOT NULL THEN {{ node: {var_name}, parent: id(parent{var_name}) }} ELSE null END AS {var_name}WithParent
            return_preds.extend(
                [f"s0"]+
                # [f"CASE WHEN  s0 IS NOT NULL THEN {{  node: {{s0}}, parent: id(parent{{s0}}) }} ELSE null END AS {{s0}}"] + 
                # [f"CASE WHEN  s0 IS NOT NULL THEN {{  node: {{s0}}, parent: id(parent{{s0}}) }} ELSE null END AS {{s0}}"] + 
                [
                 f"CASE WHEN t{i} IS NOT NULL THEN {{  node: t{i}, parent: id(parentt{i}) }} ELSE null END AS t{i}"
                 for i in range(len(predicates))])
            # return_preds.extend([f"s0"] + [f"t{i}" for i in range(len(predicates))])
                
            if (len(match_no_preds) == 0):
                cypher_query = self.construct_clause(match_preds, return_preds, optional_match_preds, optional_return_preds)
                cypher_queries.append(cypher_query)
            else:
                cypher_query = self.construct_union_clause(match_preds, return_preds, match_no_preds, return_no_preds, optional_match_preds,optional_return_preds, optional_return_union)
                cypher_queries.append(cypher_query)
        return cypher_queries
    
    def construct_clause(self, match_clause, return_clause, optional_match_clause=[], optional_return_clause=[]):
        match_clause = f"MATCH {', '.join(match_clause)}"
        optional_clause= ""
        if optional_match_clause:
            optional_clause = f"OPTIONAL MATCH {', '.join(optional_match_clause)}"
        return_clause = f"RETURN {', '.join( return_clause +  optional_return_clause)}"
        query = f"{match_clause} {optional_clause} {return_clause}"
        return query

    def construct_union_clause(self, match_preds, return_preds, match_no_preds, return_no_preds,optional_match_preds,optional_return_preds,optional_return_union):
        match_preds = f"MATCH {', '.join(match_preds)}"
        optional_clause = f"OPTIONAL MATCH {', '.join(optional_match_preds)}"
        tmp_return_preds = return_preds
        return_preds = f"RETURN {', '.join(  return_preds)} , null AS {', null AS '.join(return_no_preds)}"
        match_no_preds = f"MATCH {', '.join(match_no_preds)}"
        return_no_preds = f"RETURN  {', '.join(return_no_preds )} , null AS {', null AS '.join(optional_return_union)}"
        query = f"{match_preds} {optional_clause} {return_preds} UNION {match_no_preds} {return_no_preds}"
        return query

    def match_node(self, node, var_name):
        if node['id']:
            return f"({var_name}:{node['type']} {{id: '{node['id']}'}})"
        elif node['properties']:
            properties = ", ".join([f"{k}: '{v}'" for k, v in node['properties'].items()])
            return f"({var_name}:{node['type']} {{{properties}}})"
        else:
            return f"({var_name}:{node['type']})"

    # def match_node(self, node, var_name):
    #     # Build the node match clause
    #     if node['id']:
    #         match_clause = f"({var_name}:{node['type']} {{id: '{node['id']}'}})"
    #     elif node['properties']:
    #         properties = ", ".join([f"{k}: '{v}'" for k, v in node['properties'].items()])
    #         match_clause = f"({var_name}:{node['type']} {{{properties}}})"
    #     else:
    #         match_clause = f"({var_name}:{node['type']})"

    #     # Add OPTIONAL MATCH for incoming relationships to the node
    #     optional_parent_match = f"OPTIONAL MATCH (parent{var_name})-[]->({var_name})"

    #     print("match node", f"{match_clause} {optional_parent_match}")
        
    #     # Return both the match and optional match clauses
    #     return f"{match_clause} {optional_parent_match}"

    # def match_node(self, node, var_name):
    #     # Build the node match clause
    #     if node['id']:
    #         match_clause = f"({var_name}:{node['type']} {{id: '{node['id']}'}})"
    #     elif node['properties']:
    #         properties = ", ".join([f"{k}: '{v}'" for k, v in node['properties'].items()])
    #         match_clause = f"({var_name}:{node['type']} {{{properties}}})"
    #     else:
    #         match_clause = f"({var_name}:{node['type']})"
        
    #     # Add OPTIONAL MATCH for incoming relationships to the node
    #     optional_parent_match = f"OPTIONAL MATCH (parent{var_name})-[]->({var_name})"
        
    #     # Create the return clause to include both the node and its parent
    #     return_clause = f"{{ node: {var_name}, parent: parent{var_name} }} AS {var_name}WithParent"

    #     # Return the full MATCH, OPTIONAL MATCH, and RETURN clause for the node with parent
    #     return match_clause, optional_parent_match, return_clause

    def optional_parent_match(self, var_name):
        # Add OPTIONAL MATCH for incoming relationships to the node
        optional_parent_match = f"(parent{var_name})-[]->({var_name})"
        
        # Create the return clause to include both the node and its parent
        return_clause = f"CASE WHEN {var_name} IS NOT NULL THEN {{ node: {var_name}, parentis: id(parent{var_name}) }} ELSE null END AS {var_name}"        
        # Create the return clause to include both the node and its parent
        return_union = f"{var_name}"


        # Return both the OPTIONAL MATCH and RETURN clause
        return optional_parent_match, return_clause, return_union



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
                            # add parent field
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


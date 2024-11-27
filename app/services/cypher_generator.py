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

    def run_query(self, query_code, limit, apply_limit=True):
        results = []
        if isinstance(query_code, list):
            find_query = query_code[0]
            count_query = query_code[1]
        else:
            find_query = query_code
            count_query = None

        if apply_limit:
            try:
                curr_limit = min(5000, int(limit)) # TODO: Find a better way for the max limit
            except (ValueError, TypeError):
                curr_limit = 5000
                find_query += f"\nLIMIT {curr_limit}"

        
        with self.driver.session() as session:
            results.append(list(session.run(find_query)))

        if count_query:
            with self.driver.session() as session:
                results.append(list(session.run(count_query)))

        return results

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
        where_preds = []
        match_no_preds = []
        return_no_preds = []
        where_no_preds = []
        node_ids = set()
        # Track nodes that are included in relationships
        used_nodes = set()
        if not predicates:
            list_of_node_ids = []
            # Case when there are no predicates
            for node in nodes:
                var_name = f"n_{node['node_id']}"
                match_no_preds.append(self.match_node(node, var_name))
                if node['properties']:
                    where_no_preds.extend(self.where_construct(node, var_name))
                return_no_preds.append(var_name)
                list_of_node_ids.append(var_name)
            cypher_query = self.construct_clause(match_no_preds, return_no_preds, where_no_preds)
            cypher_queries.append(cypher_query)
            query_clauses = {
                    "match_no_preds": match_no_preds,
                    "return_no_preds": return_no_preds,
                    "where_no_preds": where_no_preds,
                    "list_of_node_ids": list_of_node_ids,
                }
            count = self.construct_count_clause(query_clauses)
            cypher_queries.append(count)
        else:
            for i, predicate in enumerate(predicates):
                predicate_type = predicate['type'].replace(" ", "_").lower()
                source_node = node_map[predicate['source']]
                target_node = node_map[predicate['target']]
                source_var = source_node['node_id']
                target_var = target_node['node_id']

                source_match = self.match_node(source_node, source_var)
                where_preds.extend(self.where_construct(source_node, source_var))
                match_preds.append(source_match)
                target_match = self.match_node(target_node, target_var)
                where_preds.extend(self.where_construct(target_node, target_var))

                match_preds.append(f"({source_var})-[r{i}:{predicate_type}]->{target_match}")
                return_preds.append(f"r{i}")

                used_nodes.add(predicate['source'])
                used_nodes.add(predicate['target'])
                node_ids.add(source_var)
                node_ids.add(target_var)

            for node_id, node in node_map.items():
                if node_id not in used_nodes:
                    var_name = f"n_{node_id}"
                    match_no_preds.append(self.match_node(node, var_name))
                    where_no_preds.extend(self.where_construct(node, var_name))
                    return_no_preds.append(var_name)

            list_of_node_ids = list(node_ids)
            list_of_node_ids.sort()
            full_return_preds = return_preds + list_of_node_ids
            #return_preds.extend(list(list_of_node_ids))
                
            if (len(match_no_preds) == 0):
                cypher_query = self.construct_clause(match_preds, full_return_preds, where_preds)
                cypher_queries.append(cypher_query)

                query_clauses = {
                    "match_preds": match_preds, 
                    "full_return_preds": full_return_preds,
                    "where_preds": where_preds,
                    "list_of_node_ids": list_of_node_ids,
                    "return_preds": return_preds
                }
                count = self.construct_count_clause(query_clauses)
                cypher_queries.append(count)
            else:
                print("in match no preds")
                cypher_query = self.construct_union_clause(match_preds, full_return_preds, where_preds, match_no_preds, return_no_preds, where_no_preds)
                cypher_queries.append(cypher_query)

                query_clauses = {
                    "match_preds": match_preds, 
                    "full_return_preds": full_return_preds,
                    "where_preds": where_preds,
                    "match_no_preds": match_no_preds,
                    "return_no_preds": return_no_preds,
                    "where_no_preds": where_no_preds,
                    "list_of_node_ids": list_of_node_ids,
                    "return_preds": return_preds
                }

                count = self.construct_count_clause(query_clauses)
                cypher_queries.append(count)
        return cypher_queries
    
    def construct_clause(self, match_clause, return_clause, where_no_preds):
        match_clause = f"MATCH {', '.join(match_clause)}"
        return_clause = f"RETURN {', '.join(return_clause)}"
        if len(where_no_preds) > 0:
            where_clause = f"WHERE {' AND '.join(where_no_preds)}"
            return f"{match_clause} {where_clause} {return_clause}"
        return f"{match_clause} {return_clause}"

    def construct_union_clause(self, match_preds, return_preds, where_preds ,match_no_preds, return_no_preds, where_no_preds):
        where_clause = ""
        where_no_clause = ""
        match_preds = f"MATCH {', '.join(match_preds)}"
        tmp_return_preds = return_preds
        return_preds = f"RETURN {', '.join(return_preds)} , null AS {', null AS '.join(return_no_preds)}"
        if len(where_preds) > 0:
            where_clause = f"WHERE {' AND '.join(where_preds)}"
        match_no_preds = f"MATCH {', '.join(match_no_preds)}"
        return_no_preds = f"RETURN  {', '.join(return_no_preds)} , null AS {', null AS '.join(tmp_return_preds)}"
        if len(where_no_preds) > 0:
            where_no_clause = f"WHERE {' AND '.join(where_no_preds)}"
        query = f"{match_preds} {where_clause} {return_preds} UNION {match_no_preds} {where_no_clause} {return_no_preds}"
        return query

    def construct_count_clause(self, query_clauses):
        match_no_clause = ''
        where_no_clause = ''
        match_clause = ''
        where_clause = ''
        count_clause = ''
        with_clause = ''
        unwind_clause = ''
        return_clause = ''

        # Check and construct clause for match with no predicates
        if 'match_no_preds' in query_clauses and query_clauses['match_no_preds']:
            match_no_clause = f"MATCH {', '.join(query_clauses['match_no_preds'])}"
            if 'where_no_preds' in query_clauses and query_clauses['where_no_preds']:
                where_no_clause = f"WHERE {' AND '.join(query_clauses['where_no_preds'])}"

        # Construct a clause for match with predicates
        if 'match_preds' in query_clauses and query_clauses['match_preds']:
            match_clause = f"MATCH {', '.join(query_clauses['match_preds'])}"
            if 'where_preds' in query_clauses and query_clauses['where_preds']:
                where_clause = f"WHERE {' AND '.join(query_clauses['where_preds'])}"

        # Construct the COUNT clause
        if 'return_no_preds' in query_clauses and 'return_preds' in query_clauses:
            query_clauses['list_of_node_ids'].extend(query_clauses['return_no_preds'])
        for node_ids in query_clauses['list_of_node_ids']:
            count_clause += f"COLLECT(DISTINCT {node_ids}) AS {node_ids}_count, "
        if 'return_preds' in query_clauses:
            for edge_ids in query_clauses['return_preds']:
                count_clause += f"COLLECT(DISTINCT {edge_ids}) AS {edge_ids}_count, "
        count_clause = f"WITH {count_clause.rstrip(', ')}"


        # Construct the WITH and UNWIND clauses
        combined_nodes = ' + '.join([f"{var}_count" for var in query_clauses['list_of_node_ids']])
        combined_edges = None
        if 'return_preds' in query_clauses:
            combined_edges = ' + '.join([f"{var}_count" for var in query_clauses['return_preds']])
        with_clause = f"WITH {combined_nodes} AS combined_nodes {f',{combined_edges} AS combined_edges' if combined_edges else ''}"
        unwind_clause = f"UNWIND combined_nodes AS nodes"

        # Construct the RETURN clause
        return_clause = f"RETURN COUNT(DISTINCT nodes) AS total_nodes {', SIZE(combined_edges) AS total_edges ' if combined_edges else ''}"

        query = f'''
            {match_no_clause}
            {where_no_clause}
            {match_clause}
            {where_clause}
            {count_clause}
            {with_clause}
            {unwind_clause}
            {return_clause}
        '''
        return query


    def construct_call_clause(self, clauses):
        # For both nodes without prediacate and with predicate
        if "match_no_clause" in clauses and clauses["match_no_clause"] != "" and \
           "match_clause" in clauses and clauses["match_clause"] != "":
            return f'CALL() {{ {clauses["match_no_clause"]} {clauses["where_no_clause"]} {clauses["return_no_clause"]} }} ' \
                   f'CALL() {{ {clauses["match_clause"]} {clauses["where_clause"]} {clauses["return_clause"]} }} ' \
                   f'{clauses["return_count_sum"]}'
        # For only nodes with predicate
        elif "match_clause" in clauses and clauses["match_clause"] != "":
            return f'CALL() {{ {clauses["match_clause"]} {clauses["where_clause"]} {clauses["return_clause"]} }} ' \
                   f'{clauses["return_count_sum"]}'
        # For only nodes with out predicate
        elif "match_no_clause" in clauses and clauses["match_no_clause"] != "":
            return f'CALL() {{ {clauses["match_no_clause"]} {clauses["where_no_clause"]} {clauses["return_no_clause"]} }}' \
                   f'{clauses["return_count_sum"]}'
        else:
            raise Exception("match clause or match_no_clause need to be present")




    def match_node(self, node, var_name):
        if node['id']:
            return f"({var_name}:{node['type']} {{id: '{node['id']}'}})"
        else:
            return f"({var_name}:{node['type']})"

    def where_construct(self, node, var_name):
        properties = []
        if node['id']: 
            return properties
        for key, property in node['properties'].items():
            properties.append(f"{var_name}.{key} =~ '(?i){property}'")
        return properties

    def parse_neo4j_results(self, results, all_properties):
        (nodes, edges, _, _, node_count, edge_count) = self.process_result(results, all_properties)
        return {"nodes": nodes, "edges": edges, "node_count": node_count, "edge_count": edge_count}

    def parse_and_serialize(self, input, schema, all_properties):
        parsed_result = self.parse_neo4j_results(input, all_properties)
        return parsed_result

    def convert_to_dict(self, results, schema):
        (_, _, node_dict, edge_dict, _, _) = self.process_result(results, True)
        return (node_dict, edge_dict)

    def process_result(self, results, all_properties):
        match_result = results[0]
        if len(results) > 1:
            count_result = results[1]
        else:
            count_result = None
        node_count = None
        edge_count = None
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
                            if all_properties:
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

        if count_result:
            for count_record in count_result:
                node_count = count_record['total_nodes']
                edge_count = count_record.get('total_edges', 0)
    
        return (nodes, edges, node_to_dict, edge_to_dict, node_count, edge_count)

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

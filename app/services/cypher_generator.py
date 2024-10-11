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

    def query_Generator(self, requests, node_map,take, page):
        nodes = requests['nodes']
        if "predicates" in requests:
            predicates = requests["predicates"]
        else:
            predicates = None

        cypher_queries = []
        # node_dict = {node['node_id']: node for node in nodes}

        match_preds = []
        optional_match_preds = []
        edges = [] # added edges to separate nodes
        return_edges = []
        edge_returns = []
        return_preds = []
        match_no_preds = []
        return_no_preds = []
        node_ids = set()
        # Track nodes that are included in relationships
        used_nodes = set()
        if not predicates:
            # Case when there are no predicates
            for node in nodes:
                var_name = f"n_{node['node_id']}"
                match_no_preds.append(self.match_node(node, var_name))
                optional_match_preds.append(self.optional_child_match(var_name))
                return_no_preds.append(var_name)
            cypher_query = self.construct_clause(match_no_preds, return_no_preds, return_edges, [], optional_match_preds)
            cypher_queries.append(cypher_query)
        else:
            for i, predicate in enumerate(predicates):
                predicate_type = predicate['type'].replace(" ", "_").lower()
                source_node = node_map[predicate['source']]
                target_node = node_map[predicate['target']]
                source_var = source_node['node_id']
                target_var = target_node['node_id']

                source_match = self.match_node(source_node, source_var)
                optional_match_preds.append(self.optional_child_match(source_var))
                match_preds.append(source_match)
                target_match = self.match_node(target_node, target_var)
                optional_match_preds.append(self.optional_child_match(target_var))


                match_preds.append(f"({source_var})-[r{i}:{predicate_type}]->{target_match}")
                edges.append(f"r{i}")
                edges.append(f"labels(startNode(r{i})) AS startNodeLabels_r{i}")
                edges.append(f"labels(endNode(r{i})) AS  endNodeLabels_r{i}")

                edge_returns.append(f"r{i}")
                
                return_edges.append(f"{{relationship: r{i}, startNodeLabel: startNodeLabels_r{i}, endNodeLabel: endNodeLabels_r{i}}} AS r{i}")

                used_nodes.add(predicate['source'])
                used_nodes.add(predicate['target'])
                node_ids.add(source_var)
                node_ids.add(target_var)

            for node_id, node in node_map.items():
                if node_id not in used_nodes:
                    var_name = f"n_{node_id}"
                    match_no_preds.append(self.match_node(node, var_name))
                    return_no_preds.append(var_name)

            return_preds.extend(list(node_ids))
                
            if (len(match_no_preds) == 0):
                cypher_query = self.construct_clause(match_preds, return_preds, return_edges, edges, optional_match_preds,page, take)
                cypher_queries.append(cypher_query)
            else:
                cypher_query = self.construct_union_clause(match_preds, return_preds, match_no_preds, return_no_preds, optional_match_preds, edges, return_edges, edge_returns, page, take)
                cypher_queries.append(cypher_query)
        
        # add_pagination = self.add_pagination_to_query(cypher_queries)
        return cypher_queries
    def construct_clause(self, match_clause, return_clause, return_edges, edges, optional_match_preds, page, take):
        match_clause = f"MATCH {', '.join(match_clause)}"

        optional_clause = f"{' '.join([f'OPTIONAL MATCH {optional_pred}' for optional_pred in optional_match_preds])}"
        collect_child_nodes = [f"collect(distinct id(child{var_name})) AS child{var_name}" for var_name in return_clause]

        if len(edges) != 0:
            with_clause = f"WITH {', '.join(edges + return_clause + collect_child_nodes )}"
        else:
            with_clause = f"WITH {', '.join(return_clause + collect_child_nodes)}"
        nodes = [f"CASE WHEN {var_name} IS NOT NULL THEN {{ properties: {var_name}{{.*, child: child{var_name}}}, id: id({var_name}), labels: labels({var_name}), elementId: elementId({var_name}) }} ELSE null END AS {var_name}" for var_name in return_clause]
        return_clause = f"RETURN {', '.join(nodes + return_edges)}"
        [limit, skip] = self.add_pagination_to_query(take, page)
        query = f"{match_clause} {optional_clause} {with_clause} {return_clause} SKIP {skip} LIMIT {limit}"
        return query

    def construct_union_clause(self, match_preds, return_preds, match_no_preds, return_no_preds, optional_match_preds,edges, return_edges, edge_returns, page, take):
        match_preds = f"MATCH {', '.join(match_preds)}"
        # child field returns null if more than one node is not present
        # multiline optional match
        optional_clause = f"{' '.join([f'OPTIONAL MATCH {optional_pred}' for optional_pred in optional_match_preds])}"
        
        # make the ids into a list with distinct values to avoid node duplication
        collect_child_nodes = [f"collect(distinct id(child{var_name})) AS child{var_name}" for var_name in return_preds]
        with_clause = f"WITH {', '.join(return_preds + edges + collect_child_nodes)}"
        #with_clause += f" RETURN {', '.join(edges)}"
        tmp_return_preds = return_preds + edge_returns

        
        nodes = [f"CASE WHEN {var_name} IS NOT NULL THEN {{ properties: {var_name}{{.*, child: child{var_name}}}, id: id({var_name}), labels: labels({var_name}), elementId: elementId({var_name}) }} ELSE null END AS {var_name}" for var_name in return_preds]


        # output example
        # { node: n2{.*, child: childn2}}
        #   { 
        #            node: {
        #              identity: id(n2),
        #              labels: labels(n2),
        #              properties: n2 {.*, child: childn2 },
        #              elementId: elementId(n2)
        #            }
        #          }
        # OR
        # null AS n2
        
        nodes_no_pred = [f"null AS {var_name}" for var_name in return_no_preds]
        return_preds = f"RETURN {', '.join(return_edges + nodes + nodes_no_pred)}"
        match_no_preds = f"MATCH {', '.join(match_no_preds)}"
        tmp_no_preds = [f"{{ properties: properties({var_name}), id: id({var_name}), labels: labels({var_name}), elementId: elementId({var_name})}} AS {var_name}" for var_name in return_no_preds]
        return_no_preds = f"RETURN  {', '.join(tmp_no_preds)} , null AS {', null AS '.join(tmp_return_preds)}"
        [limit,skip] = self.add_pagination_to_query(take, page)
        query = f"{match_preds} {optional_clause} {with_clause} ORDER BY n3.id {return_preds}  SKIP {skip} LIMIT {limit} UNION {match_no_preds} {return_no_preds}"
        return query

    def match_node(self, node, var_name):
        if node['id']:
            return f"({var_name}:{node['type']} {{id: '{node['id']}'}})"
        elif node['properties']:
            properties = ", ".join([f"{k}: '{v}'" for k, v in node['properties'].items()])
            return f"({var_name}:{node['type']} {{{properties}}})"
        else:
            return f"({var_name}:{node['type']})"

    def parse_neo4j_results(self, results, all_properties):
        (nodes, edges, _, _) = self.process_result(results, all_properties)
        return {"nodes": nodes, "edges": edges}

    def parse_and_serialize(self, input, schema, all_properties):
        parsed_result = self.parse_neo4j_results(input, all_properties)
        return parsed_result["nodes"], parsed_result["edges"]

    def convert_to_dict(self, results, schema):
        (_, _, node_dict, edge_dict) = self.process_result(results, True)
        return (node_dict, edge_dict)
    
    def is_dict_node(self, item):
        # Check if the item contains the typical node structure (identity, labels, properties)
        return isinstance(item, dict) and 'id' in item and 'labels' in item and 'properties' in item and 'elementId' in item
    
    def process_result(self, results, all_properties):
        nodes = []
        edges = []
        node_dict = {}
        node_to_dict = {}
        edge_to_dict = {}
        node_type = set()
        edge_type = set()

        named_types = ['gene_name', 'transcript_name', 'protein_name']

        for record in results:
            for item in record.values():

                if item is None:
                    continue
                # Checking if the item is a node of our return type
                if self.is_dict_node(item) or isinstance(item, neo4j.graph.Node):
                    label = None
                    properties = None
                    if self.is_dict_node(item):
                        label = list(item['labels'])[0]
                        properties = item['properties']['id']
                        node_id = f"{item['id']}"
                        
                    else:
                        label = list(item.labels)[0]
                        # properties = item['id']
                        node_id = f"{item['id']}"
                        
                    if node_id not in node_dict:
                        node_data = {
                            "data": {
                                "id": node_id,
                                "type": label,
                            }
                        }
                        
                        #print("ITEM", item)
                        for key, value in item.items():
                            if all_properties:
                                if key != "id" and key != "synonyms":
                                    node_data["data"][key] = value
                            else:
                                #print("here")
                                if key == 'properties':
                                    node_data["data"]['properties'] = {}
                                    #print('properties', type(properties))
                                    for properties_name, property_value in value.items():
                                        if properties_name in named_types:
                                            node_data["data"]['properties']["name"] = property_value
                                        if properties_name == 'child':
                                            node_data["data"]['properties'][properties_name] = property_value
                        nodes.append(node_data)
                        if node_data["data"]["type"] not in node_type:
                            node_type.add(node_data["data"]["type"])
                            node_to_dict[node_data['data']['type']] = []
                        node_to_dict[node_data['data']['type']].append(node_data)
                        node_dict[node_id] = node_data
                elif "relationship" in item or isinstance(item, neo4j.graph.Relationship):
                    source_label = item["startNodeLabel"][0]
                    target_label = item["endNodeLabel"][0]
                    if "relationship" in item:
                        item = item["relationship"]

                    source_id = f"{item.nodes[0].id}"
                    target_id = f"{item.nodes[1].id}"
                    #source_label = f"{list(item.labels)[0]}"
                    edge_data = {
                        "data": {
                            # "id": item.id,
                            "label": item.type,
                            "source": source_id,
                            "target": target_id,
                            "source_label": source_label,
                            "target_label": target_label
                        }
                    }
                    if item is not None or isinstance(item, type):
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
        return (nodes, edges, node_to_dict, edge_to_dict)

    def optional_child_match(self, var_name):
        # Add OPTIONAL MATCH for outgoing relationships from the nodes that are included in the relationships
        optional_child_match = f"({var_name})-[]->(child{var_name})"

        return optional_child_match

    def parse_id(self, request):
        nodes = request["nodes"]
        named_types = {"gene": "gene_name", "transcript": "transcript_name"}
        prefixes = ["ENSG", "ENST"]

        for node in nodes:
            is_named_type = node['type'] in named_types
            is_name_as_id = all(not node["id"].startswith(prefix) for prefix in prefixes)
            no_id = node["id"] != ''
            if is_named_type and is_name_as_id and no_id:
                node_type = named_types[node['type']]
                node['properties'][node_type] = node["id"]
                node['id'] = ''
            node["id"] = node["id"].lower()
        return request

    # def paginate(query, skip, take):

        # parsed_limit = int(self.params.get('take', 10)) if self.params.get('take') else 10  # Default to 10 if invalid
        # parsed_page = int(self.params.get('page', 1)) if self.params.get('page') else 1     # Default to page 1 if invalid
        # skip = (parsed_page - 1) * parsed_limit

        # self.query = self.query.limit(parsed_limit).offset(skip)

        # return self

    def add_pagination_to_query(self , take: str = "1", page: str = "1") -> str:
        # Ensure 'take' and 'page' are strings and parse them, with defaults of 10 and 1 respectively
        take = str(take) if not isinstance(take, str) else take
        page = str(page) if not isinstance(page, str) else page

        parsed_limit = int(take) if take.isdigit() else 10  # Default to 10 if invalid
        parsed_page = int(page) if page.isdigit() else 1    # Default to page 1 if invalid
        skip = (parsed_page - 1) * parsed_limit

        # return LIMIT and SKIP to the query string on new lines

        return parsed_limit, skip 


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
        results = []
        if isinstance(query_code, list):
            find_query = query_code[0]
            count_query = query_code[1]
        else:
            find_query = query_code
            count_query = None
        
        with self.driver.session() as session:
            results.append(list(session.run(find_query)))

        if count_query:
            try:
                with self.driver.session() as session:
                    results.append(list(session.run(count_query)))
            except Exception as e:
                return results.append([])

        return results

    def query_Generator(self, requests, node_map,take, page):
        nodes = requests['nodes']
        predicates = requests.get("predicates", [])
        logic = requests.get("logic", None)

        cypher_queries = []
        # node_dict = {node['node_id']: node for node in nodes}

        match_preds = []
        optional_match_preds = []
        where_preds = []
        edges = [] # added edges to separate nodes
        return_edges = []
        edge_returns = []
        return_preds = []
        match_no_preds = []
        return_no_preds = []
        where_no_preds = []
        node_ids = set()
        # Track nodes that are included in relationships
        used_nodes = set()
        no_label_ids = None
        where_logic = None

        # define a set of nodes with predicates
        node_predicates = {p['source'] for p in predicates}.union({p['target'] for p in predicates})

        predicate_map = {}

        if logic:
            for predicate in predicates:
                if predicate['predicate_id'] not in predicate_map:
                    predicate_map[predicate['predicate_id']] = predicate
                else:
                    raise Exception('Repeated predicate_id')
            where_logic, no_label_ids = self.apply_boolean_operation(logic['children'], node_map, node_predicates, predicate_map)

        if not predicates:
            # Case when there are no predicates
            for node in nodes:
                if node['properties']:
                    where_no_preds.extend(self.where_construct(node))
                if where_logic:
                    where_no_preds.extend(where_logic['where_no_preds'])
                match_no_preds.append(self.match_node(node, no_label_ids['no_node_labels'] if no_label_ids else None))
                optional_match_preds.append(self.optional_child_match(node))
                return_no_preds.append(node['node_id'])

            query_clause = {
                'match_no_preds': match_no_preds,
                'where_no_preds': where_no_preds,
                'return_no_preds': return_no_preds,
                'list_of_node_ids': list(node_ids) 
            }
            
            count_query = self.construct_count_clause(query_clause)
            data_query = self.construct_clause(match_no_preds, where_no_preds, return_no_preds, 
                                               return_edges, [], optional_match_preds, [],page, take)
            cypher_queries.extend([count_query, data_query])
        else:
            for i, predicate in enumerate(predicates):
                predicate_type = predicate['type'].replace(" ", "_").lower()
                source_node = node_map[predicate['source']]
                target_node = node_map[predicate['target']]
                source_var = source_node['node_id']
                target_var = target_node['node_id']
                predicate_id = predicate['predicate_id']
                 # Common match and return part
                if logic and predicate['predicate_id'] in no_label_ids['no_predicate_labels']:
                    source_match = source_var
                    target_match = target_var
                    match_preds.append(f"({source_var})-[{predicate_id}]->({target_var})")
                    #return_preds.append(predicate['predicate_id'])
                else:
                    source_match = self.match_node(source_node)
                    where_preds.extend(self.where_construct(source_node))
                    match_preds.append(source_match)

                    target_match = self.match_node(target_node)
                    where_preds.extend(self.where_construct(target_node))

                    match_preds.append(f"({source_var})-[{predicate_id}:{predicate_type}]->{target_match}")
                    #return_preds.append(f"r{i}")

                optional_match_preds.append(self.optional_child_match(source_node))
                optional_match_preds.append(self.optional_child_match(target_node))

                edges.append(f"{predicate_id}")
                edges.append(f"labels(startNode({predicate_id})) AS startNodeLabels_{predicate_id}")
                edges.append(f"labels(endNode({predicate_id})) AS  endNodeLabels_{predicate_id}")

                edge_returns.append(f"{predicate_id}")
                
                return_edges.append(f"{{relationship: {predicate_id}, startNodeLabel: startNodeLabels_{predicate_id}, endNodeLabel: endNodeLabels_{predicate_id}}} AS {predicate_id}")

                used_nodes.add(predicate['source'])
                used_nodes.add(predicate['target'])
                node_ids.add(source_var)
                node_ids.add(target_var)

            for node_id, node in node_map.items():
                if node_id not in used_nodes:
                    match_no_preds.append(self.match_node(node))
                    where_no_preds.extend(self.where_construct(node))
                    return_no_preds.append(node_id)

            return_preds.extend(list(node_ids))
            print(return_preds)
                
            if (len(match_no_preds) == 0):
                if where_logic:
                    where_preds.extend(where_logic['where_preds'])
                query_clause = {
                    "match_preds": match_preds,
                    "where_preds": where_preds,
                    "return_preds": return_preds,
                    "edge_returns": edge_returns,
                    "list_of_node_ids": list(node_ids)
                }
                count_query = self.construct_count_clause(query_clause)
                data_query = self.construct_clause(match_preds, where_preds, return_preds, return_edges, edges, optional_match_preds, edge_returns,page, take)
                cypher_queries.extend([count_query, data_query])
            else:
                if where_logic:
                    where_no_preds.extend(where_logic['where_no_preds'])
                    where_preds.extend(where_logic['where_preds'])
                query_clause = {
                    "match_preds": match_preds,
                    "where_preds": where_preds,
                    "return_preds": return_preds,
                    "match_no_preds": match_no_preds,
                    "where_no_preds": where_no_preds,
                    "return_no_preds": return_no_preds,
                    "list_of_node_ids": list(node_ids),
                    "return_preds": return_preds,
                    "optional_match_preds": optional_match_preds,
                    "edges": edges,
                    "return_edges": return_edges,
                    "edge_returns": edge_returns
                }
                count_query = self.construct_count_clause(query_clause)
                data_query = self.construct_union_clause(query_clause, page, take)
                cypher_queries.extend([count_query, data_query])
        
        return cypher_queries
    
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

        if "return_no_preds" in query_clauses:
            query_clauses['list_of_node_ids'].extend(query_clauses['return_no_preds'])

        # Construct the COUNT clause
        count_clause = f"{' + '.join([f'COLLECT(DISTINCT {node})' for node in query_clauses['list_of_node_ids']])} AS combined_nodes"
        print("EDGE RETURNS: ", query_clauses.get('edge_returns', []))
        if 'edge_returns' in query_clauses:
            count_clause += ", " + " + ".join([f"COLLECT(DISTINCT {edge})" for edge in query_clauses['edge_returns']]) + " AS combined_edges"
        count_clause = f"WITH {count_clause}"

        if 'return_preds' in query_clauses:
            unwind_clause = '''
                UNWIND combined_nodes AS nodes
                UNWIND combined_nodes AS node_e
                UNWIND labels(nodes) AS label
            '''
            with_clause = '''
                WITH
                    label,
                    node_e,
                    COUNT(DISTINCT nodes) AS node_count, 
                    combined_nodes,
                    combined_edges
                ORDER BY label
                WITH
                    label,
                    node_count,
                    node_e,
                    combined_edges
                UNWIND combined_edges AS edges
                WITH 
                    label,
                    node_count,
                    TYPE(edges) AS edge_type,
                    COUNT(edges) AS edge_count,
                    node_e,
                    combined_edges
                WITH 
                    COLLECT(DISTINCT {label: label, count: node_count}) AS nodes_count_by_label,
                    COLLECT(DISTINCT {label: edge_type, count: edge_count}) AS edges_count_by_type,
                    COUNT(DISTINCT(node_e)) AS total_nodes,
                    SIZE(combined_edges) AS total_edges
            '''
            return_clause = '''
                RETURN    
                    nodes_count_by_label,
                    edges_count_by_type,
                    total_nodes,
                    total_edges
            '''
        else:
            unwind_clause = '''
                UNWIND combined_nodes AS nodes
                UNWIND labels(nodes) AS label
            '''
            with_clause = '''
                WITH
                    label,
                    COUNT(DISTINCT nodes) AS node_count, 
                    combined_nodes
                ORDER BY label
                WITH 
                    COLLECT(DISTINCT {label: label, count: node_count}) AS nodes_count_by_label,
                    node_count AS total_nodes
            '''
            return_clause = '''
                RETURN    
                    nodes_count_by_label,
                    total_nodes
            '''

        query = f'''
            {match_no_clause}
            {where_no_clause}
            {match_clause}
            {where_clause}
            {count_clause}
            {unwind_clause}
            {with_clause}
            {return_clause}
        '''
        return query
        
    
    def construct_clause(self, match_clause, where_preds, return_clause, return_edges, edges, optional_match_preds, edge_returns,page, take):
        match_clause = f"MATCH {', '.join(match_clause)}"
        where_clause = ''
        if len(where_preds) > 0:
            where_clause = f"WHERE {' AND '.join(where_preds)}"
        [limit, skip] = self.add_pagination_to_query(take, page)
        pre_with_clause = f"WITH {', '.join(return_clause + edge_returns)}"
        limit_clause = f"SKIP {skip} LIMIT {limit}"

        # optional_clause = f"{' '.join([f'OPTIONAL MATCH {optional_pred}' for optional_pred in optional_match_preds])}"
        child_nodes = [f"child{var_name}" for var_name in return_clause]
        optional_clause = f" CALL {{ {' '.join([f'OPTIONAL MATCH {optional_pred}' for optional_pred in optional_match_preds])} RETURN {', '.join(child_nodes)}}} LIMIT 2"
        collect_child_nodes = [f"collect(distinct id(child{var_name})) AS child{var_name}" for var_name in return_clause]

        if len(edges) != 0:
            with_clause = f"WITH {', '.join(edges + return_clause + collect_child_nodes )}"
        else:
            with_clause = f"WITH {', '.join(return_clause + collect_child_nodes)}"
        nodes = [f"CASE WHEN {var_name} IS NOT NULL THEN {{ properties: {var_name}{{.*, child: child{var_name}}}, id: id({var_name}), labels: labels({var_name}), elementId: elementId({var_name}) }} ELSE null END AS {var_name}" for var_name in return_clause]
        return_clause = f"RETURN {', '.join(nodes + return_edges)}"
        query = f"{match_clause} {where_clause} {pre_with_clause} {limit_clause} {optional_clause} {with_clause} {return_clause}"
        return query

    def construct_union_clause(self, query_clause, page, take):
        match_clause = f"MATCH {', '.join(query_clause['match_preds'])}"
        where_clause = ''
        where_no_clause = ''
        if len(query_clause['where_preds']) > 0:
            where_clause = f"WHERE {' AND '.join(query_clause['where_preds'])}"
        # child field returns null if more than one node is not present
        # multiline optional match
        child_nodes = [f"child{var_name}" for var_name in query_clause['return_preds']]
        # optional_clause = f"{' '.join([f'OPTIONAL MATCH {optional_pred}' for optional_pred in optional_match_preds])}"
        optional_clause = f"{' '.join([f'OPTIONAL MATCH {optional_pred}' for optional_pred in query_clause['optional_match_preds']])} " \
                          f"RETURN {', '.join(child_nodes)} LIMIT 2"
        # make the ids into a list with distinct values to avoid node duplication
        collect_child_nodes = [f"collect(distinct id(child{var_name})) AS child{var_name}" for var_name in query_clause['return_preds']]
        with_clause = f"WITH {', '.join(query_clause['return_preds'] + query_clause['edges'] + collect_child_nodes)}"

        nodes = [f"CASE WHEN {var_name} IS NOT NULL THEN {{ properties: {var_name}{{.*, child: child{var_name}}}, id: id({var_name}), "
                 f"labels: labels({var_name}), elementId: elementId({var_name}) }} "
                 f"ELSE null END AS {var_name}" for var_name in query_clause['return_preds']]

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
        
        # nodes_no_pred = [f"null AS {var_name}" for var_name in return_no_preds]
        return_clause = f"RETURN {', '.join(query_clause['return_edges'] + nodes)}"

        match_no_clause = f"MATCH {', '.join(query_clause['match_no_preds'])}"
        if len(query_clause['where_no_preds']) > 0:
            where_no_clause = f"WHERE {' AND '.join(query_clause['where_no_preds'])}"
        tmp_no_preds = [f"{{ properties: properties({var_name}), id: id({var_name}), labels: labels({var_name}), \
                        elementId: elementId({var_name})}} AS {var_name}" for var_name in query_clause['return_no_preds']]
        return_no_clause = f"RETURN  {', '.join(tmp_no_preds)}"
        [limit,skip] = self.add_pagination_to_query(take, page)

        limit_clause = f"SKIP {skip} LIMIT {limit}"

        #query = f"{match_clause}  {optional_clause} {with_clause} {return_clause}  SKIP {skip} LIMIT {limit}"
        clauses = {}

        clauses['match_clause'] = match_clause
        clauses['optional_clause'] = optional_clause
        clauses['with_clause'] = with_clause
        clauses['return_clause'] = return_clause
        clauses['match_no_clause'] = match_no_clause
        clauses['return_no_clause'] = return_no_clause
        clauses['limit_clause'] = limit_clause
        clauses['where_clause'] = where_clause
        clauses['where_no_clause'] = where_no_clause

        query = self.construct_call_clause(clauses)

        return query

    def where_construct(self, node):
        properties = []
        if node['id']: 
            return properties
        for key, property in node['properties'].items():
            properties.append(f"{node['node_id']}.{key} =~ '(?i){property}'")
        return properties

    def construct_call_clause(self, clauses):
        call_clause = ''

        call_clause = f'''CALL() {{
            {clauses['match_clause']}
            {clauses['where_clause']}
            {clauses['limit_clause']}

            CALL() {{
                {clauses['optional_clause']}
            }}

            {clauses['with_clause']}

            {clauses['return_clause']}
        }}
        
        CALL() {{
            {clauses['match_no_clause']}
            {clauses['where_no_clause']}
            {clauses['return_no_clause']}
            {clauses['limit_clause']}
        }} RETURN *'''

        return call_clause

    def apply_boolean_operation(self, logics, node_map, node_predicates, predicate_map):
        where_clauses = {'where_no_preds': [], 'where_preds': []}
        no_label_ids = {'no_node_labels': set(), 'no_predicate_labels': set()}

        for logic in logics:
            if logic['operator'] == "NOT":
                where_query, no_label_id = self.construct_not_operation(logic, node_map, predicate_map)

                # Default action for handling where_clauses and no_label_ids
                if 'nodes' in logic:
                    node_id = logic['nodes']['node_id']
                    if node_id not in node_predicates:
                        where_clauses['where_no_preds'].append(where_query)
                    else:
                        where_clauses['where_preds'].append(where_query)
                    no_label_ids['no_node_labels'].update(no_label_id['no_node_labels'])

                elif 'predicates' in logic:
                    where_clauses['where_preds'].append(where_query)
                    no_label_ids['no_predicate_labels'].update(no_label_id['no_predicate_labels'])

        return where_clauses, no_label_ids

    def construct_not_operation(self, logic, node_map, predicate_map):
        where_clause = ''
        no_label_id = {'no_node_labels': set(), 'no_predicate_labels': set()}

        if 'nodes' in logic:
            node_id = logic['nodes']['node_id']
            if 'properties' in logic['nodes']:
                properties = logic['nodes']['properties']
                where_clause = ' AND '.join([f"{node_id}.{property} <> '{value}'" for property, value in properties.items()])
            else:
                node_type = node_map[node_id]['type']
                no_label_id['no_node_labels'].add(node_id)
                where_clause = f'NOT ({node_id}: {node_type})'

        elif 'predicates' in logic:
            predicate_id = logic['predicates']['predicate_id']
            predicate = predicate_map[predicate_id]
            label = predicate['type'].replace(" ", "_").lower()
            no_label_id['no_node_labels'].update([predicate['source'], predicate['target']])
            no_label_id['no_predicate_labels'].add(predicate_id)
            where_clause = f"type({predicate_id}) <> '{label}'"
        return where_clause, no_label_id
    
    def match_node(self, node, no_label_ids=None):
        if no_label_ids and node['node_id'] in no_label_ids:
            return f"({node['node_id']})"

        if node['id']:
            return f"({node['node_id']}:{node['type']} {{id: '{node['id']}'}})"
        else:
            return f"({node['node_id']}:{node['type']})"

    def parse_neo4j_results(self, results, all_properties):
        (nodes, edges, _, _, meta_data) = self.process_result(results, all_properties)
        return {"nodes": nodes, "edges": edges, "meta_data": meta_data}


    def parse_and_serialize(self, input, schema, all_properties):
        parsed_result = self.parse_neo4j_results(input, all_properties)
        return parsed_result

    def convert_to_dict(self, results, schema):
        (_, _, node_dict, edge_dict, _) = self.process_result(results, True)
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
        visited_relations = set()
        named_types = ['gene_name', 'transcript_name', 'protein_name']
        node_count_by_label = []
        edge_count_by_label = []
        node_count = 0
        edge_count = 0

        count_result = results[0]
        records = results[1]

        for record in records:
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
                        
                        for key, value in item.items():
                            if all_properties:
                                if key != "id" and key != "synonyms":
                                    node_data["data"][key] = value
                            else:
                                if key == 'properties':
                                    node_data["data"]['properties'] = {'id': value['id']}
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

                    temp_relation_id = f"{source_id} - {item.type} - {target_id}"
                    if temp_relation_id in visited_relations:
                        continue
                    visited_relations.add(temp_relation_id)
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

        if count_result:
            for count_record in count_result:
                node_count_by_label.extend(count_record['nodes_count_by_label'])
                edge_count_by_label.extend(count_record.get('edges_count_by_type', []))
                node_count += count_record['total_nodes']
                edge_count += count_record.get('total_edges', 0)
        meta_data = {
            "node_count": node_count,
            "edge_count": edge_count,
            "node_count_by_label": node_count_by_label,
            "edge_count_by_label": edge_count_by_label
        }
        return (nodes, edges, node_to_dict, edge_to_dict, meta_data)

    def optional_child_match(self, node):
        # Add OPTIONAL MATCH for outgoing relationships from the nodes that are included in the relationships
        optional_child_match = f"({node['node_id']})-[]->(child{node['node_id']})"

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

    def add_pagination_to_query(self , take: str = "1", page: str = "1") -> str:
        # Ensure 'take' and 'page' are strings and parse them, with defaults of 10 and 1 respectively
        take = str(take) if not isinstance(take, str) else take
        page = str(page) if not isinstance(page, str) else page

        parsed_limit = int(take) if take.isdigit() else 10  # Default to 10 if invalid
        parsed_page = int(page) if page.isdigit() else 1    # Default to page 1 if invalid
        skip = (parsed_page - 1) * parsed_limit

        # return LIMIT and SKIP to the query string on new lines

        return parsed_limit, skip 


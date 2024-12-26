import json
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
                print(e)
                print("EXCPETION")
                results.append([])
                return results
        print("COUNT : ", results[1])

        return results

    def query_Generator(self, requests, node_map, limit=None):
        nodes = requests['nodes']
        predicates = requests.get("predicates", [])
        logic = requests.get("logic", None)

        cypher_queries = []

        match_preds = []
        return_preds = []
        where_preds = []
        match_no_preds = []
        return_no_preds = []
        where_no_preds = []
        node_ids = set()
        # Track nodes that are included in relationships
        used_nodes = set()
        no_label_ids = None
        where_logic = {}
        exclude_where = set()
        return_or = []

        # define a set of nodes with predicates
        node_predicates = {p['source'] for p in predicates}.union({p['target'] for p in predicates})

        predicate_map = {}

        if logic:
            for predicate in predicates:
                if predicate['predicate_id'] not in predicate_map:
                    predicate_map[predicate['predicate_id']] = predicate
                else:
                    raise Exception('Repeated predicate_id')
            where_logic, no_label_ids, exclude_where, return_or = self.apply_boolean_operation(logic['children'], node_map, node_predicates, predicate_map)
        if not predicates:
            list_of_node_ids = []
            # Case when there are no predicates
            for node in nodes:
                if node['properties']:
                    where_no_preds.extend(self.where_construct(node))
                if where_logic:
                    where_no_preds.extend(where_logic['where_no_preds'])
                match_no_preds.append(self.match_node(node, no_label_ids['no_node_labels'] if no_label_ids else None))
                return_no_preds.append(node['node_id'])
                list_of_node_ids.append(node['node_id'])
                query_clauses = {
                    "match_clause": match_no_preds,
                    "return_clause": return_no_preds,
                    "where_clause": where_no_preds,
                }
            cypher_query = self.construct_clause(query_clauses, limit)
            cypher_queries.append(cypher_query)
            query_clauses = {
                    "match_no_preds": match_no_preds,
                    "return_no_preds": return_no_preds,
                    "where_no_preds": where_no_preds,
                    "list_of_node_ids": list_of_node_ids,
                    "predicates": predicates
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

                # Common match and return part
                if logic and predicate['predicate_id'] in no_label_ids['no_predicate_labels']:
                    source_match = source_var
                    target_match = target_var
                    match_preds.append(f"({source_var})-[{predicate['predicate_id']}]->({target_var})")
                    return_preds.append(predicate['predicate_id'])
                else:
                    source_match = self.match_node(source_node)
                    if source_var not in exclude_where:
                        where_preds.extend(self.where_construct(source_node))
                    match_preds.append(source_match)

                    target_match = self.match_node(target_node)
                    
                    if target_var not in exclude_where:
                        where_preds.extend(self.where_construct(target_node))

                    match_preds.append(f"({source_var})-[r{i}:{predicate_type}]->{target_match}")
                    return_preds.append(f"r{i}")


                used_nodes.add(predicate['source'])
                used_nodes.add(predicate['target'])
                node_ids.add(source_var)
                node_ids.add(target_var)

            for node_id, node in node_map.items():
                if node_id not in used_nodes:
                    match_no_preds.append(self.match_node(node))
                    where_no_preds.extend(self.where_construct(node))
                    return_no_preds.append(node_id)


            list_of_node_ids = list(node_ids - exclude_where)
            list_of_node_id = list(node_ids)
            list_of_node_ids.sort()
            full_return_preds = return_preds + list_of_node_ids
            full_return_preds.extend(return_or)
                
            if (len(match_no_preds) == 0):
                if where_logic:
                    where_preds.extend(where_logic['where_preds'])
                query_clauses = {
                    'match_clause': match_preds,
                    'return_clause': full_return_preds,
                    'where_clause': where_preds 
                }
                cypher_query = self.construct_clause(query_clauses, limit)
                cypher_queries.append(cypher_query)
                query_clauses = {
                    "match_preds": match_preds, 
                    "full_return_preds": full_return_preds,
                    "where_preds": where_preds,
                    "list_of_node_ids": list_of_node_id,
                    "return_preds": return_preds,
                    "predicates": predicates
                }
                count = self.construct_count_clause(query_clauses)
                cypher_queries.append(count)
            else:
                if where_logic:
                    where_no_preds.extend(where_logic['where_no_preds'])
                    where_preds.extend(where_logic['where_preds'])
                query_clauses = {
                    "match_preds": match_preds, 
                    "full_return_preds": full_return_preds,
                    "where_preds": where_preds,
                    "match_no_preds": match_no_preds,
                    "return_no_preds": return_no_preds,
                    "where_no_preds": where_no_preds,
                    "list_of_node_ids": list_of_node_ids,
                    "return_preds": return_preds,
                    "predicates": predicates
                }
                cypher_query = self.construct_union_clause(query_clauses, limit)
                cypher_queries.append(cypher_query)
                query_clauses = {
                    "match_preds": match_preds, 
                    "full_return_preds": full_return_preds,
                    "where_preds": where_preds,
                    "match_no_preds": match_no_preds,
                    "return_no_preds": return_no_preds,
                    "where_no_preds": where_no_preds,
                    "list_of_node_ids": list_of_node_id,
                    "return_preds": return_preds,
                    "predicates": predicates
                }

                count = self.construct_count_clause(query_clauses)
                cypher_queries.append(count)
        return cypher_queries
    
    def construct_clause(self, query_clauses, limit):
        match_clause = f"MATCH {', '.join(query_clauses['match_clause'])}"
        return_clause = f"RETURN {', '.join(query_clauses['return_clause'])}"
        if len(query_clauses['where_clause']) > 0:
            where_clause = f"WHERE {' AND '.join(query_clauses['where_clause'])}"
            return f"{match_clause} {where_clause} {return_clause} {self.limit_query(limit)}"
        return f"{match_clause} {return_clause} {self.limit_query(limit)}"

    def construct_union_clause(self, query_clauses, limit):
        match_no_clause = ''
        where_no_clause = ''
        return_count_no_preds_clause = ''
        match_clause = ''
        where_clause = ''
        return_count_preds_clause = ''

        # Check and construct clause for match with no predicates
        if 'match_no_preds' in query_clauses and query_clauses['match_no_preds']:
            match_no_clause = f"MATCH {', '.join(query_clauses['match_no_preds'])}"
            if 'where_no_preds' in query_clauses and query_clauses['where_no_preds']:
                where_no_clause = f"WHERE {' AND '.join(query_clauses['where_no_preds'])}"
            return_count_no_preds_clause = "RETURN " + ', '.join(query_clauses['return_no_preds'])

        # Construct a clause for match with predicates
        if 'match_preds' in query_clauses and query_clauses['match_preds']:
            match_clause = f"MATCH {', '.join(query_clauses['match_preds'])}"
            if 'where_preds' in query_clauses and query_clauses['where_preds']:
                where_clause = f"WHERE {' AND '.join(query_clauses['where_preds'])}"
            return_count_preds_clause = "RETURN " + ', '.join(query_clauses['full_return_preds'])

        clauses = {}

        # Update the query_clauses dictionary with the constructed clauses
        clauses['match_no_clause'] = match_no_clause
        clauses['where_no_clause'] = where_no_clause
        clauses['return_no_clause'] = return_count_no_preds_clause
        clauses['match_clause'] = match_clause
        clauses['where_clause'] = where_clause
        clauses['return_clause'] = return_count_preds_clause
        
        query = self.construct_call_clause(clauses, limit)
        return query

    def construct_count_clause(self, query_clauses):
        match_no_clause = ''
        where_no_clause = ''
        match_clause = ''
        where_clause = ''
        return_preds = []
        print("LIST OF NODE IDS : ", query_clauses['list_of_node_ids'])

        # Construct clause for match with no predicates
        if 'match_no_preds' in query_clauses and query_clauses['match_no_preds']:
            match_no_clause = f"MATCH {', '.join(query_clauses['match_no_preds'])}"
            if 'where_no_preds' in query_clauses and query_clauses['where_no_preds']:
                where_no_clause = f"WHERE {' AND '.join(query_clauses['where_no_preds'])}"

        # Construct clause for match with predicates
        if 'match_preds' in query_clauses and query_clauses['match_preds']:
            match_clause = f"MATCH {', '.join(query_clauses['match_preds'])}"
            if 'where_preds' in query_clauses and query_clauses['where_preds']:
                where_clause = f"WHERE {' AND '.join(query_clauses['where_preds'])}"

        if "return_no_preds" in query_clauses and "return_preds" in query_clauses:
            query_clauses['list_of_node_ids'].extend(query_clauses['return_no_preds'])

        if "return_preds" in query_clauses:
            return_preds = query_clauses['return_preds']

        label_clause = (
            'WITH DISTINCT ' +
            ' + '.join([f"labels({n})" for n in query_clauses['list_of_node_ids']]) +
            ' AS all_labels'
        )

        if not return_preds:
            label_clause += ', ' + ', '.join(query_clauses['list_of_node_ids'])
        else:
            label_clause += ', ' + ', '.join(return_preds)

        unwind_label_clause = 'UNWIND all_labels AS label'

        count_clause = []
        if return_preds:
            for index, predicate in enumerate(query_clauses['predicates']):
                count_clause.append(f'WHEN label IN labels(startNode(r{index})) THEN startNode(r{index})')
            count_clause.append(f'WHEN label IN labels(endNode(r{index})) THEN endNode(r{index})')
        else:
            for node_id in query_clauses['list_of_node_ids']:
                count_clause.append(f'WHEN label IN labels({node_id}) THEN {node_id}')

        count_clause = ' '.join(count_clause)
        count_clause = f'WITH label, count(DISTINCT CASE {count_clause} ELSE null END) AS node_count'

        node_count_by_label = 'WITH COLLECT({label: label, count: node_count}) AS nodes_count_by_label'

        if return_preds:
            count_relationships = (
            'WITH nodes_count_by_label, ' +
            ' + '.join([f'COLLECT([type(r{i}), r{i}])' for i in range(len(query_clauses['predicates']))]) +
            ' AS relationships'
            )
            unwind_relationships = 'UNWIND relationships AS rel'
            count_edge_by_label = (
            'WITH nodes_count_by_label, rel[0] AS edge_type, COUNT(rel[1]) AS edge_count '
            'WITH nodes_count_by_label, COLLECT({label: edge_type, count: edge_count}) AS edges_count_by_type'
            )
            return_clause = (
            'RETURN nodes_count_by_label, edges_count_by_type, '
            'REDUCE(total = 0, n IN nodes_count_by_label | total + n.count) AS total_nodes, '
            'REDUCE(total_edges = 0, e IN edges_count_by_type | total_edges + e.count) AS total_edges'
            )
            query = f'''
            {match_no_clause}
            {where_no_clause}
            {match_clause}
            {where_clause}
            {label_clause}
            {unwind_label_clause}
            {count_clause}
            {node_count_by_label}
            {match_no_clause}
            {where_no_clause}
            {match_clause}
            {where_clause}
            {count_relationships}
            {unwind_relationships}
            {count_edge_by_label}
            {return_clause}
            '''
        else:
            count_edge_by_label = 'WITH nodes_count_by_label'
            return_clause = (
            'RETURN nodes_count_by_label, '
            'REDUCE(total = 0, n IN nodes_count_by_label | total + n.count) AS total_nodes'
            )
            query = f'''
            {match_no_clause}
            {where_no_clause}
            {match_clause}
            {where_clause}
            {label_clause}
            {unwind_label_clause}
            {count_clause}
            {node_count_by_label}
            {match_no_clause}
            {where_no_clause}
            {match_clause}
            {where_clause}
            {count_edge_by_label}
            {return_clause}
            '''

        print("QUERY : ", query)

        return query
    
    def apply_boolean_operation(self, logics, node_map, node_predicates, predicate_map):
        where_clauses = {'where_no_preds': [], 'where_preds': []}
        no_label_ids = {'no_node_labels': set(), 'no_predicate_labels': set()}
        exclude_where = set()

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
            elif logic['operator'] == "OR":
                where_query, exclude_where, return_or = self.construct_or_operation(logic, node_map, predicate_map)
                if 'nodes' in logic:
                    node_id = logic['nodes']['node_id']
                    if node_id not in node_predicates:
                        where_clauses['where_no_preds'].append(where_query)
                    else:
                        where_clauses['where_preds'].append(where_query)
                elif 'predicates' in logic:
                    where_clauses['where_preds'].append(where_query)
               # what's here = self.construct_or_operation(logic, node_map, predicate_map)


        return where_clauses, no_label_ids ,exclude_where, return_or

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
    
    def construct_or_operation(self, logic, node_map, predicate_map):
        where_clause = ''
        properties_or = []
        exclude_where = set()
        return_or = ''
        
        if 'nodes' in logic:
            node_id = logic['nodes']['node_id']
            properties = logic['nodes']['properties']
            for property, value in properties.items():
                for single_value in value:
                    properties_or.append(f"{node_id}.{property} = '{single_value}'")
            where_clause = ' OR '.join(properties_or)
        
        if 'predicates' in logic:
            predicate_ids = logic['predicates']
            temp_properties_or = []
            operands = []
            returns = []

            for index, predicate_id in enumerate(predicate_ids):
                predicate = predicate_map[predicate_id]
                source_node = node_map[predicate['source']]
                target_node = node_map[predicate['target']]

                exclude_where.add(source_node['node_id'])
                exclude_where.add(target_node['node_id'])

                temp_properties_or.extend(self.where_construct(source_node))
                temp_properties_or.extend(self.where_construct(target_node))


                operand = f"({' AND '.join(temp_properties_or)})"
                operands.append(operand)
                return_statment = f'CASE WHEN {operand} THEN [{source_node["node_id"]}, {target_node["node_id"]}] ELSE NULL END AS case_result_{index}'

                returns.append(return_statment)
                temp_properties_or = []
            
            where_clause = f"({' OR '.join(operands)})"  

        return where_clause, exclude_where, returns

    def limit_query(self, limit):
        if limit:
            curr_limit = min(1000, int(limit))
        else:
            curr_limit = 1000
        return f"LIMIT {curr_limit}"

    def construct_call_clause(self, clauses, limit=None):
        if not ("match_no_clause" in clauses or "match_clause" in clauses):
            raise Exception("Either 'match_clause' or 'match_no_clause' must be present")

        # Build CALL clauses
        call_clauses = []

        # For both nodes without predicate and with predicate
        if "match_no_clause" in clauses and clauses["match_no_clause"]:
            call_clauses.append(
                f'CALL() {{ {clauses["match_no_clause"]} '
                f'{clauses.get("where_no_clause", "")} '
                f'{clauses["return_no_clause"]} '
                f'{self.limit_query(limit) if "return_count_sum" not in clauses else ""} }}'
            )

        if "match_clause" in clauses and clauses["match_clause"]:
            call_clauses.append(
                f'CALL() {{ {clauses["match_clause"]} '
                f'{clauses.get("where_clause", "")} '
                f'{clauses["return_clause"]} '
                f'{self.limit_query(limit) if "return_count_sum" not in clauses else ""} }}'
            )

        # Add any additional return clause sum/normal query
        final_clause = clauses.get("return_count_sum", "RETURN *")
        call_clauses.append(final_clause)

        # Combine clauses into a single string
        return " ".join(call_clauses)



    def match_node(self, node, no_label_ids=None):
        if no_label_ids and node['node_id'] in no_label_ids:
            return f"({node['node_id']})"

        if node['id']:
            return f"({node['node_id']}:{node['type']} {{id: '{node['id']}'}})"
        else:
            return f"({node['node_id']}:{node['type']})"

    def where_construct(self, node):
        properties = []
        if node['id']: 
            return properties
        for key, property in node['properties'].items():
            properties.append(f"{node['node_id']}.{key} =~ '(?i){property}'")
        return properties

    def parse_neo4j_results(self, results, all_properties):
        (nodes, edges, _, _, meta_data) = self.process_result(results, all_properties)
        return {"nodes": nodes, "edges": edges, "node_count": meta_data['node_count'], 
                "edge_count": meta_data['edge_count'], "node_count_by_label": meta_data['node_count_by_label'], 
                "edge_count_by_label": meta_data['edge_count_by_label']
                }

    def parse_and_serialize(self, input, schema, all_properties):
        parsed_result = self.parse_neo4j_results(input, all_properties)
        return parsed_result

    def convert_to_dict(self, results, schema):
        (_, _, node_dict, edge_dict, _) = self.process_result(results, True)
        return (node_dict, edge_dict)

    def process_result(self, results, all_properties):
        match_result = results[0]
        if len(results) > 1:
            count_result = results[1]
        else:
            count_result = None
        node_count = 0
        edge_count = 0
        node_count_by_label = []
        edge_count_by_label = []
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
            for key, item in record.items():
                if item is None:
                    continue
                elif isinstance(item, list):
                    for sub_item in item:
                        node_id = f"{list(sub_item.labels)[0]} {sub_item['id']}"
                        if node_id not in node_dict:
                            node_data = {
                                "data": {
                                    "id": node_id,
                                    "type": list(sub_item.labels)[0],
                                }
                            }

                            for key, value in sub_item.items():
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

                elif isinstance(item, neo4j.graph.Node):
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

                    source_labels = list(item.start_node.labels)
                    if source_labels:
                        source_id = f"{source_labels[0]} {item.start_node['id']}"
                    else:
                        continue
                    
                    target_labels = list(item.end_node.labels)

                    if target_labels:
                        target_id = f"{target_labels[0]} {item.end_node['id']}"
                    else:
                        continue
                    edge_data = {
                        "data": {
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
                print("**COUNT**", count_result)
                node_count_by_label = count_record['nodes_count_by_label']
                edge_count_by_label = count_record.get('edges_count_by_type', [])
                node_count = count_record['total_nodes']
                edge_count = count_record.get('total_edges', 0)

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

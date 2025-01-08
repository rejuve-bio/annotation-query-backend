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

    def run_query(self, query_code, source):
        results = []
        if isinstance(query_code, list):
            find_query = query_code[0]
            count_query = query_code[1]
        else:
            find_query = query_code
            count_query = None
        
        with self.driver.session() as session:
            results.append(list(session.run(find_query)))
        if count_query and source != 'hypotehesis':
            try:
                with self.driver.session() as session:
                    results.append(list(session.run(count_query)))
            except Exception as e:
                print(e)
                print("EXCPETION")
                results.append([])
                return results
        return results

    def query_Generator(self, requests, node_map, limit=None):
        nodes = requests['nodes']
        predicates = requests.get("predicates", [])
        logic = requests.get("logic", None)
        commands = self._initialize_commands()
        
        node_predicates, predicate_map = self._prepare_predicate_maps(predicates, logic)      
        if logic:
            for child in logic['children']:
                commands = self._process_logic_child(child, node_map, predicate_map, node_predicates, commands)
        commands, list_of_node_ids= self.generate_sub_commands(nodes, predicates, node_map, logic, commands)
        cypher_qureies = self.build_queries(commands, list_of_node_ids, predicates, limit)

        return cypher_qureies
    def _prepare_predicate_maps(self, predicates, logic):
        node_predicates = {p['source'] for p in predicates}.union({p['target'] for p in predicates})
        predicate_map = {}

        if logic:
            for predicate in predicates:
                if predicate['predicate_id'] not in predicate_map:
                    predicate_map[predicate['predicate_id']] = predicate
                else:
                    raise Exception('Repeated predicate_id')

        return node_predicates, predicate_map
    def _initialize_commands(self):
        return {
            "preds": {
                "match": [],
                "where": [],
                "return": [],
                "optional_match": [],
                "optional_where": [],
                "optional_return": [],
                "with": [],
                "no_node_labels": set(),
                "no_predicate_labels": set()
            },
            "no_preds": {
                "match": [],
                "where": [],
                "return": [],
                "no_node_labels": set()
            }
        }

    def _process_logic_child(self, child, node_map, predicate_map, node_predicates, commands):
        operator = child["operator"]
        if operator == "NOT":
            return self.construct_not_operation(child, node_map, predicate_map, node_predicates, commands)
        elif operator == "OR":
            return self.construct_or_operation(child, node_map, predicate_map, node_predicates, commands)
        return commands
    
    def build_queries(self, commands, list_of_node_ids, predicates, limit):
        cypher_queries = []
        
        if not predicates:
            cypher_queries.extend(self._build_no_predicate_queries(commands, list_of_node_ids, limit))
        else:
            cypher_queries.extend(self._build_predicate_queries(commands, list_of_node_ids, predicates, limit))

        return cypher_queries

    def _build_no_predicate_queries(self, commands, list_of_node_ids, limit):
        queries = []

        query_clauses = {
            "match_clause": commands['no_preds']['match'],
            "return_clause": commands['no_preds']['return'],
            "where_clause": commands['no_preds']['where']
        }
        queries.append(self.construct_clause(query_clauses, limit))

        count_clauses = {
            "match_no_preds": commands['no_preds']['match'],
            "return_no_preds": commands['no_preds']['return'],
            "where_no_preds": commands['no_preds']['where'],
            "list_of_node_ids": list_of_node_ids,
            "predicates": []
        }
        queries.append(self.construct_count_clause(count_clauses))

        return queries

    def _build_predicate_queries(self, commands, list_of_node_ids, predicates, limit):
        queries = []
        full_return_preds = list(set(commands['preds']['return'] + list_of_node_ids))

        union_clauses = {
            "match_preds": commands['preds']['match'], 
            "full_return_preds": full_return_preds,
            "where_preds": commands['preds']['where'],
            "match_no_preds": commands['no_preds']['match'],
            "return_no_preds": commands['no_preds']['return'],
            "where_no_preds": commands['no_preds']['where'],
            "list_of_node_ids": list_of_node_ids,
            "optional_match": commands['preds']['optional_match'],
            "optional_where": commands['preds']['optional_where'],
            "optional_return": commands['preds']['optional_return'],
            "optional_with": commands['preds']['with'],
            "return_preds": commands['preds']['return'],
            "predicates": predicates
        }
        queries.append(self.construct_union_clause(union_clauses, limit))

        count_clauses = union_clauses.copy()
        queries.append(self.construct_count_clause(count_clauses))

        return queries


    MATCH_NO_PRED_LABELS = 'no_predicate_lables'
    def generate_sub_commands(self, nodes, predicates, node_map, logic, commands):
        list_of_node_ids = set()
        
        if not predicates:
            self._handle_no_predicates(nodes, commands, list_of_node_ids)
        else:
            self._handle_with_predicates(predicates, node_map, logic, commands, list_of_node_ids)
        
        return commands, list(list_of_node_ids)
    
    def _handle_no_predicates(self, nodes, commands, list_of_node_ids):
        for node in nodes:
            if node['properties']:
                commands['no_preds']['where'].extend(self.where_construct(node))
            list_of_node_ids.add(node['node_id'])
            no_node_labels = commands['no_preds']['no_node_labels']
            commands['no_preds']['match'].append(self.match_node(node, no_node_labels if no_node_labels else None))
            commands['no_preds']['return'].append(node['node_id'])
    
    def _handle_with_predicates(self, predicates, node_map, logic, commands, list_of_node_ids):
        for predicate in predicates:
            predicate_type = predicate['type'].replace(" ", "_").lower()
            source_node = node_map.get(predicate['source'])
            target_node = node_map.get(predicate['target'])
            
            if not source_node or not target_node:
                continue
            
            self._process_predicate_logic(source_node, target_node, predicate, predicate_type, logic, commands, list_of_node_ids)
    
    def _process_predicate_logic(self, source_node, target_node, predicate, predicate_type, logic, commands, list_of_node_ids):
        source_var = source_node['node_id']
        target_var = target_node['node_id']
        list_of_node_ids.add(source_var)
        list_of_node_ids.add(target_var)

        if logic and predicate['predicate_id'] in commands['preds'][self.MATCH_NO_PRED_LABELS]:
            self._add_match_return_no_predicates(source_var, target_var, predicate, commands)
        else:
            self._add_match_with_predicates(source_node, target_node, predicate, predicate_type, source_var, target_var, commands)
    
    def _add_match_return_no_predicates(self, source_var, target_var, predicate, commands):
        commands['preds']['match'].append(f"({source_var})-[{predicate['predicate_id']}]->({target_var})")
        commands['preds']['return'].append(predicate['predicate_id'])

    def _add_match_with_predicates(self, source_node, target_node, predicate, predicate_type, source_var, target_var, commands):
        source_match = self.match_node(source_node)
        commands['preds']['where'].extend(self.where_construct(source_node))
        commands['preds']['match'].append(source_match)
        
        target_match = self.match_node(target_node)
        commands['preds']['where'].extend(self.where_construct(target_node))
        commands['preds']['match'].append(f"({source_var})-[{predicate['predicate_id']}:{predicate_type}]->{target_match}")
        commands['preds']['return'].append(predicate['predicate_id'])
    
    def construct_clause(self, query_clauses, limit):
        match_clause = f"MATCH {', '.join(query_clauses['match_clause'])}"
        return_clause = f"RETURN {', '.join(query_clauses['return_clause'])}"
        
        if query_clauses['where_clause']:
            where_clause = f"WHERE {' AND '.join(query_clauses['where_clause'])}"
            return f"{match_clause} {where_clause} {return_clause} {self.limit_query(limit)}"
        
        return f"{match_clause} {return_clause} {self.limit_query(limit)}"

    def construct_union_clause(self, query_clauses, limit):
        clauses = self._construct_union_parts(query_clauses)
        query = self.construct_call_clause(clauses, limit)
        return query

    def _construct_union_parts(self, query_clauses):
        clauses = {}
        
        clauses['match_no_clause'] = self._get_clause_part('match_no_preds', query_clauses)
        clauses['where_no_clause'] = self._get_clause_part('where_no_preds', query_clauses, 'AND')
        clauses['return_no_clause'] = self._get_return_clause(query_clauses, 'return_no_preds')
        
        clauses['match_clause'] = self._get_clause_part('match_preds', query_clauses)
        clauses['where_clause'] = self._get_clause_part('where_preds', query_clauses, 'AND')
        clauses['return_clause'] = self._get_return_clause(query_clauses, 'full_return_preds')
        
        clauses['optional_match'], clauses['optional_where'], clauses['optional_return'], clauses['optional_with'] = self._process_optional_clauses(query_clauses)
        
        return clauses

    def _get_clause_part(self, key, query_clauses, join_type=None):
        if key in query_clauses and query_clauses[key]:
            if join_type:
                return f"{key.upper()} {' '.join(query_clauses[key])}"
            return f"MATCH {', '.join(query_clauses[key])}"
        return ''

    def _get_return_clause(self, query_clauses, key):
        if key in query_clauses:
            return "RETURN " + ', '.join(query_clauses[key])
        return ''

    def _process_optional_clauses(self, query_clauses):
        optional_match, optional_where, optional_return, optional_with = [], [], [], []
        
        if 'optional_match' in query_clauses and query_clauses['optional_match']:
            for match in query_clauses['optional_match']:
                optional_match.append(f"OPTIONAL MATCH {match}")
            
        if 'optional_where' in query_clauses and query_clauses['optional_where']:
            for where in query_clauses['optional_where']:
                optional_where.append(f"WHERE {where}")
        
        if 'optional_with' in query_clauses:
            for with_clause in query_clauses['optional_with']:
                optional_with.append(f"WITH {with_clause}")
        
        if 'optional_return' in query_clauses:
            for return_clause in query_clauses['optional_return']:
                optional_return.append(f"RETURN {', '.join(return_clause)}")
        
        return optional_match, optional_where, optional_return, optional_with
    # Static or class variables for reusable strings
    MATCH_TEMPLATE = "MATCH {}"
    WHERE_TEMPLATE = "WHERE {}"
    OPTIONAL_MATCH_TEMPLATE = "OPTIONAL MATCH {}"
    WITH_TEMPLATE = "WITH {}"
    RETURN_TEMPLATE = "RETURN {}"
    COALESCE_LABELS = "COALESCE(labels({}), [])"

    def construct_count_clause(self, query_clauses):
        # Initialize variables
        match_no_clause, where_no_clause, match_clause, where_clause = '', '', '', ''
        return_preds, optional_returns, query = [], [], ''
        
        # Optional match clause
        if 'optional_match' in query_clauses and query_clauses['optional_match']:
            query = self.construct_optional_match(query_clauses)

        # Construct clause for match with no predicates
        match_no_clause, where_no_clause = self.construct_match_no_preds(query_clauses)

        # Construct clause for match with predicates
        match_clause, where_clause = self.construct_match_preds(query_clauses)

        # Handle node returns
        if "return_no_preds" in query_clauses:
            query_clauses['list_of_node_ids'].extend(query_clauses['return_no_preds'])
        
        # Handle predicates
        if "return_preds" in query_clauses:
            return_preds = query_clauses['return_preds']
        
        if 'optional_match' in query_clauses:
            query_clauses['list_of_node_ids'].extend(optional_returns)

        # Label clause construction
        label_clause = self.construct_label_clause(query_clauses, return_preds)

        # UNWIND label clause
        unwind_label_clause = 'UNWIND all_labels AS label'

        # Count clause for labels
        count_clause = self.construct_count_label_clause(query_clauses, return_preds)

        # Construct count by label
        node_count_by_label = 'WITH COLLECT({label: label, count: node_count}) AS nodes_count_by_label'

        # Additional clauses for relationships
        if return_preds or 'optional_match' in query_clauses:
            count_relationships, unwind_relationships, count_edge_by_label, return_clause = \
                self.construct_relationship_clauses(query_clauses)
            query = self.combine_query(
                query, match_no_clause, where_no_clause, match_clause, where_clause, 
                label_clause, unwind_label_clause, count_clause, node_count_by_label,
                count_relationships, unwind_relationships, count_edge_by_label, return_clause
            )
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
            {count_edge_by_label}
            {return_clause}
            '''
        
        print("QUERY : ", query)
        return query

    # Helper method to construct optional match clause
    def construct_optional_match(self, query_clauses):
        optional_match, optional_where, optional_return, optional_with = [], [], [], []
        for match in query_clauses['optional_match']:
            optional_match.append(f"OPTIONAL MATCH {match}")
        if 'optional_where' in query_clauses and query_clauses['optional_where']:
            for where in query_clauses['optional_where']:
                optional_where.append(f"WHERE {where}")
        for with_clause in query_clauses['optional_with']:
            optional_with.append(f"WITH {with_clause}")
        for return_clause in query_clauses['optional_return']:
            #optional_returns.extend(return_clause)
            optional_return.append(f"RETURN {', '.join(return_clause)}")
        
        return " ".join([
            f'CALL() {{ {optional_with[i]} {optional_match[i]} {optional_where[i]} {optional_return[i]} }}'
            for i in range(len(optional_match))
        ])

    # Helper method to construct match clause for no predicates
    def construct_match_no_preds(self, query_clauses):
        match_no_clause, where_no_clause = '', ''
        if 'match_no_preds' in query_clauses and query_clauses['match_no_preds']:
            match_no_clause = self.MATCH_TEMPLATE.format(', '.join(query_clauses['match_no_preds']))
            if 'where_no_preds' in query_clauses and query_clauses['where_no_preds']:
                where_no_clause = self.WHERE_TEMPLATE.format(' AND '.join(query_clauses['where_no_preds']))
        return match_no_clause, where_no_clause

    # Helper method to construct match clause for predicates
    def construct_match_preds(self, query_clauses):
        match_clause, where_clause = '', ''
        if 'match_preds' in query_clauses and query_clauses['match_preds']:
            match_clause = self.MATCH_TEMPLATE.format(', '.join(query_clauses['match_preds']))
            if 'where_preds' in query_clauses and query_clauses['where_preds']:
                where_clause = self.WHERE_TEMPLATE.format(' AND '.join(query_clauses['where_preds']))
        return match_clause, where_clause

    # Helper method to construct label clause
    def construct_label_clause(self, query_clauses, return_preds):
        predicate_ids = [predicate['predicate_id'] for predicate in query_clauses['predicates']]
        label_clause = (
            'WITH DISTINCT ' +
            ' + '.join([self.COALESCE_LABELS.format(n) for n in query_clauses['list_of_node_ids'] if n not in predicate_ids]) +
            ' AS all_labels'
        )
        if not return_preds:
            label_clause += ', ' + ', '.join(query_clauses['list_of_node_ids'])
        else:
            label_clause += ', ' + ', '.join(return_preds)
        return label_clause

    # Helper method to construct count label clause
    def construct_count_label_clause(self, query_clauses, return_preds):
        count_clause = []
        if return_preds or 'optional_match' in query_clauses:
            for predicate in query_clauses['predicates']:
                count_clause.append(f'WHEN label IN labels(startNode({predicate["predicate_id"]})) THEN startNode({predicate["predicate_id"]})')
                count_clause.append(f'WHEN label IN labels(endNode({predicate["predicate_id"]})) THEN endNode({predicate["predicate_id"]})')
        else:
            for node_id in query_clauses['list_of_node_ids']:
                count_clause.append(f'WHEN label IN labels({node_id}) THEN {node_id}')
        count_clause = ' '.join(count_clause)
        return f'WITH label, count(DISTINCT CASE {count_clause} ELSE null END) AS node_count'

    # Helper method to construct relationship clauses
    def construct_relationship_clauses(self, query_clauses):
        count_relationships = (
            'WITH nodes_count_by_label, ' +
            ' + '.join([f'COLLECT(DISTINCT {predicate["predicate_id"]})' for predicate in query_clauses['predicates']]) +
            ' AS relationships'
        )
        unwind_relationships = 'UNWIND relationships AS rel'
        count_edge_by_label = (
            'WITH nodes_count_by_label, TYPE(rel) AS relationship_type, COUNT(rel) AS edge_count '
            'WITH nodes_count_by_label, COLLECT(DISTINCT {relationship_type: relationship_type, count: edge_count}) AS edges_count_by_type'
        )
        return count_relationships, unwind_relationships, count_edge_by_label, (
            'RETURN nodes_count_by_label, edges_count_by_type, '
            'REDUCE(total = 0, n IN nodes_count_by_label | total + n.count) AS total_nodes, '
            'REDUCE(total_edges = 0, e IN edges_count_by_type | total_edges + e.count) AS total_edges'
        )

    # Helper method to combine all query components
    def combine_query(self, query, match_no_clause, where_no_clause, match_clause, where_clause, label_clause, unwind_label_clause,
                      count_clause, node_count_by_label, count_relationships, unwind_relationships, count_edge_by_label, return_clause):
        return f'''
        {query}
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
    
    OR_TEMPLATE = " OR "
    WHERE_TEMPLATE = "{}.{} = '{}'"

    def construct_or_operation(self, logic, node_map, predicate_map, node_with_predicates, commands):
        source, target = [], []
        
        # Handle nodes logic
        if 'nodes' in logic:
            where_clause = self.construct_node_where_clause(logic['nodes'], node_with_predicates, commands)
        
        # Handle predicates logic
        if 'predicates' in logic:
            commands, node_map = self.construct_predicate_operations(logic['predicates'], node_map, predicate_map, commands, source, target)

        return commands, node_map

    # Helper method to construct where clause for nodes
    def construct_node_where_clause(self, nodes_logic, node_with_predicates, commands):
        properties_or = []
        where_clause = ''
        
        node_id = nodes_logic['node_id']
        properties = nodes_logic['properties']

        for property, value in properties.items():
            for single_value in value:
                properties_or.append(self.WHERE_TEMPLATE.format(node_id, property, single_value))
        
        where_clause = self.OR_TEMPLATE.join(properties_or)
        
        if node_id in node_with_predicates:
            commands['preds']['where'].append(where_clause)
        else:
            commands['no_preds']['where'].append(where_clause)

        return where_clause

    # Helper method to handle predicate operations
    def construct_predicate_operations(self, predicate_ids, node_map, predicate_map, commands, source, target):
        for predicate_id in predicate_ids:
            optional_where = []
            predicate = predicate_map[predicate_id]
            source_node = node_map[predicate['source']]
            target_node = node_map[predicate['target']]
            predicate_type = predicate['type'].replace(" ", "_").lower()

            source.append(source_node['node_id'])
            target.append(target_node['node_id'])

            # Construct match for source and target nodes
            source_match = self.match_node(source_node, None, True, source_node['type'], target_node['type'])
            target_match = self.match_node(target_node, None, True, source_node['type'], target_node['type'])

            optional_match = f"{source_match}-[{predicate_id}:{predicate_type}]->{target_match}"

            commands['preds']['optional_match'].append(optional_match)

            # Construct where clauses
            optional_where.extend(self.where_construct(source_node, None, source_node['type'], target_node['type']))
            optional_where.extend(self.where_construct(target_node, None, source_node['type'], target_node['type']))

            source_id = f'{source_node["type"]}_{source_node["node_id"]}_{target_node["type"]}'
            target_id = f'{source_node["type"]}_{source_node["node_id"]}_{target_node["type"]}'

            commands['preds']['optional_where'].append(f"{' AND '.join(optional_where)}")
            commands['preds']['optional_return'].append([source_id, target_id, predicate_id])
            commands['preds']['with'].append('true As always_true')

        # Remove processed nodes from node_map
        node_map = self.remove_processed_nodes(node_map, source, target)

        return commands, node_map

    # Helper method to remove processed nodes from node_map
    def remove_processed_nodes(self, node_map, source, target):
        for source_id in source:
            if source_id in node_map:
                node_map.pop(source_id)
        for target_id in target:
            if target_id in node_map:
                node_map.pop(target_id)
        return node_map

    # Placeholder for match_node method
    def match_node(self, source_node, target_node, optional, source_type, target_type):
        # Add logic to match nodes here
        return f"({source_node['node_id']}:{source_type})"

    # Placeholder for where_construct method
    def where_construct(self, source_node, target_node, source_type, target_type):
        # Add logic to construct where clauses here
        return [f"{source_node['node_id']}={target_node['node_id']}"]
    
    NOT_TEMPLATE = "NOT {}"
    TYPE_TEMPLATE = "type({}) <> '{}'"

    def construct_not_operation(self, logic, node_map, predicate_map, node_with_predicates, command):
        if 'nodes' in logic:
            command = self.handle_nodes_not_operation(logic['nodes'], node_map, node_with_predicates, command)
        elif 'predicates' in logic:
            command = self.handle_predicates_not_operation(logic['predicates'], predicate_map, command)

        print("NOT COMMANDS: ", command)
        return command

    # Helper method to handle nodes in the NOT operation
    def handle_nodes_not_operation(self, nodes_logic, node_map, node_with_predicates, command):
        node_id = nodes_logic['node_id']
        nodes = nodes_logic

        if 'properties' in nodes:
            where_clause = self.where_construct(nodes, "NOT")
            if node_id in node_with_predicates:
                command['preds']['where'].extend(where_clause)
            else:
                command['no_preds']['where'].extend(where_clause)
        else:
            node_type = node_map[node_id]['type']
            where_clause = self.NOT_TEMPLATE.format(f"({node_id}: {node_type})")
            if node_id in node_with_predicates:
                command['preds']['no_node_labels'].add(node_id)
                command['preds']['where'].append(where_clause)
            else:
                command['no_preds']['no_node_labels'].add(node_id)
                command['no_preds']['where'].append(where_clause)

        return command

    # Helper method to handle predicates in the NOT operation
    def handle_predicates_not_operation(self, predicates_logic, predicate_map, command):
        predicate_id = predicates_logic['predicate_id']
        predicate = predicate_map[predicate_id]
        label = predicate['type'].replace(" ", "_").lower()

        # Update labels and add predicate to the command
        command['preds']['no_node_labels'].update([predicate['source'], predicate['target']])
        command['preds']['no_predicate_labels'].add(predicate_id)

        where_clause = self.TYPE_TEMPLATE.format(predicate_id, label)
        command['preds']['where'].append(where_clause)

        return command

    # Placeholder for where_construct method
    def where_construct(self, nodes_logic, operation_type):
        # Logic for constructing where clauses
        return [f"{operation_type} ({nodes_logic['node_id']}:{nodes_logic['type']})"]
    
    

    def limit_query(self, limit):
        if limit:
            curr_limit = min(1000, int(limit))
        else:
            curr_limit = 1000
        return f"LIMIT {curr_limit}"

    def build_call_clause(self, match_clause, where_clause, return_clause, limit, is_count_sum):
        limit_part = self.limit_query(limit) if not is_count_sum else ""
        return f'CALL() {{ {match_clause} {where_clause} {return_clause} {limit_part} }}'

    def construct_call_clause(self, clauses, limit=None):
        if not ("match_no_clause" in clauses or "match_clause" in clauses or 'optional_match' in clauses):
            raise Exception("Either 'match_clause' or 'match_no_clause' must be present")

        # Initialize list to hold call clauses
        call_clauses = []

        # Handle 'match_no_clause' if it exists
        if "match_no_clause" in clauses and clauses["match_no_clause"]:
            call_clauses.append(
                self.build_call_clause(
                    clauses["match_no_clause"], 
                    clauses.get("where_no_clause", ""), 
                    clauses["return_no_clause"], 
                    limit, 
                    "return_count_sum" in clauses
                )
            )

        # Handle 'match_clause' if it exists
        if "match_clause" in clauses and clauses["match_clause"]:
            call_clauses.append(
                self.build_call_clause(
                    clauses["match_clause"], 
                    clauses.get("where_clause", ""), 
                    clauses["return_clause"], 
                    limit, 
                    "return_count_sum" in clauses
                )
            )

        # Handle 'optional_match' if it exists
        if "optional_match" in clauses and clauses["optional_match"]:
            for i in range(len(clauses["optional_match"])):
                call_clauses.append(
                    self.build_call_clause(
                        clauses["optional_match"][i], 
                        clauses["optional_where"][i], 
                        clauses["optional_return"][i], 
                        limit, 
                        "return_count_sum" in clauses
                    )
                )

        # Final return clause (with or without count sum)
        final_clause = clauses.get("return_count_sum", "RETURN *")
        call_clauses.append(final_clause)

        # Join all clauses into a single string
        return " ".join(call_clauses)
    
    # Placeholder for limit_query method
    def limit_query(self, limit):
        return f"LIMIT {limit}" if limit else ""

    def match_node(self, node, no_label_ids=None, unique=False, source=None, target=None):
        if no_label_ids and node['node_id'] in no_label_ids:
            return f"({node['node_id']})"

        if node['id']:
            if unique:
                return f"({source}_{node['node_id']}_{target}:{node['type']} {{id: '{node['id']}'}})"
            return f"({node['node_id']}:{node['type']} {{id: '{node['id']}'}})"
        else:
            if unique:
                return f"({source}_{node['node_id']}_{target}:{node['type']})"
            return f"({node['node_id']}:{node['type']})"

    def where_construct(self, node, operation=None, source=None, target=None):
        properties = []
        if 'id' in node and node['id']: 
            return properties
        
        if operation == "NOT":
            for key, property in node['properties'].items():
                if source and target:
                    properties.append(f"{source}_{node['node_id']}_{target}.{key} <> '{property}'")
                else:
                    properties.append(f"{node['node_id']}.{key} <> '{property}'")
        else:
            for key, property in node['properties'].items():
                if source and target:
                    properties.append(f"{source}_{node['node_id']}_{target}.{key} = '{property}'")
                else:
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

    def build_node_data(self,item, all_properties, named_types):
        """
        Builds the node data and returns both node ID and the corresponding node data structure.
        """
        node_id = f"{list(item.labels)[0]} {item['id']}"
        node_data = {"data": {"id": node_id, "type": list(item.labels)[0]}}

        for key, value in item.items():
            if all_properties:
                if key != "id" and key != "synonyms":
                    node_data["data"][key] = value
            else:
                if key in named_types:
                    node_data["data"]["name"] = value
        if "name" not in node_data["data"]:
            node_data["data"]["name"] = node_id
        
        return node_id, node_data


    def build_edge_data(self,item, visited_relations):
        """
        Builds the edge data while avoiding duplicates, and returns the edge data.
        """
        source_label = list(item.start_node.labels)[0]
        target_label = list(item.end_node.labels)[0]
        source_id = f"{source_label} {item.start_node['id']}"
        target_id = f"{target_label} {item.end_node['id']}"
        
        # Avoid duplicate edges
        temp_relation_id = f"{source_id} - {item.type} - {target_id}"
        if temp_relation_id in visited_relations:
            return None
        visited_relations.add(temp_relation_id)

        edge_data = {"data": {
            "id": f"{source_label}_{item.type}_{target_label}",
            "label": item.type,
            "source": source_id,
            "target": target_id
        }}

        for key, value in item.items():
            if key == 'source':
                edge_data["data"]["source_data"] = value
            else:
                edge_data["data"][key] = value

        return edge_data


    def process_result(self,results, all_properties):
        """
        Processes the result to build nodes and edges while counting and categorizing them.
        """
        match_result = results[0]
        count_result = results[1] if len(results) > 1 else None
        
        node_count, edge_count = 0, 0
        node_count_by_label, edge_count_by_label = [], []
        nodes, edges = [], []
        node_dict, node_to_dict, edge_to_dict = {}, {}, {}
        node_type, edge_type, visited_relations = set(), set(), set()

        # Named types for properties
        named_types = ['gene_name', 'transcript_name', 'protein_name', 'pathway_name', 'term_name']

        for record in match_result:
            for key, item in record.items():
                if item is None:
                    continue
                elif isinstance(item, list):
                    for sub_item in item:
                        node_id, node_data = self.build_node_data(sub_item, all_properties, named_types)
                        nodes.append(node_data)
                        node_dict[node_id] = node_data
                        if node_data["data"]["type"] not in node_type:
                            node_type.add(node_data["data"]["type"])
                            node_to_dict[node_data['data']['type']] = [node_data]
                        else:
                            node_to_dict[node_data['data']['type']].append(node_data)

                elif isinstance(item, neo4j.graph.Node):
                    node_id, node_data = self.build_node_data(item, all_properties, named_types)
                    nodes.append(node_data)
                    node_dict[node_id] = node_data
                    if node_data["data"]["type"] not in node_type:
                        node_type.add(node_data["data"]["type"])
                        node_to_dict[node_data['data']['type']] = [node_data]
                    else:
                        node_to_dict[node_data['data']['type']].append(node_data)

                elif isinstance(item, neo4j.graph.Relationship):
                    edge_data = self.build_edge_data(item, visited_relations)
                    if edge_data:
                        edges.append(edge_data)
                        if edge_data["data"]["label"] not in edge_type:
                            edge_type.add(edge_data["data"]["label"])
                            edge_to_dict[edge_data['data']['label']] = [edge_data]
                        else:
                            edge_to_dict[edge_data['data']['label']].append(edge_data)

        # Process counts if available
        if count_result:
            count_record = count_result[0]
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
        
        return nodes, edges, node_to_dict, edge_to_dict, meta_data


    def parse_id(self,request):
        """
        Parses and modifies node IDs in the request, especially for named types.
        """
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
                node['id'] = ''  # Reset the ID to empty
            node["id"] = node["id"].lower()  # Convert ID to lowercase

        return request

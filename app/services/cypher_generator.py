from typing import List
import logging
from dotenv import load_dotenv
import neo4j
from app.services.query_generator_interface import QueryGeneratorInterface
from neo4j import GraphDatabase
import glob
import os
from neo4j.graph import Node, Relationship
from app.error import TaskCancelledException

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CypherQueryGenerator(QueryGeneratorInterface):
    def __init__(self, dataset_path: str):
        self.human_driver = GraphDatabase.driver(
            os.getenv('HUMAN_NEO4J_URI'),
            auth=(os.getenv('HUMAN_NEO4J_USERNAME'), os.getenv('HUMAN_NEO4J_PASSWORD'))
        )
        self.fly_driver = GraphDatabase.driver(
            os.getenv('FLY_NEO4J_URI'),
            auth=(os.getenv('FLY_NEO4J_USERNAME'), os.getenv('FLY_NEO4J_PASSWORD'))
        )

    def close(self):
        self.driver.close()

    def load_dataset(self, path: str) -> None:
        if not os.path.exists(path):
            raise ValueError(f"Dataset path '{path}' does not exist.")

        paths = glob.glob(os.path.join(path, "**/*.cypher"), recursive=True)
        if not paths:
            raise ValueError(
                f"No .cypher files found in dataset path '{path}'.")

        # Separate nodes and edges
        nodes_paths = [p for p in paths if p.endswith("nodes.cypher")]
        edges_paths = [p for p in paths if p.endswith("edges.cypher")]

        # Helper function to process files
        def process_files(file_paths, file_type):
            for file_path in file_paths:
                logger.info(
                    f"Start loading {file_type} dataset from '{file_path}'...")
                try:
                    with open(file_path, 'r') as file:
                        data = file.read()
                        for line in data.splitlines():
                            self.run_query(line)
                except Exception as e:
                    logger.error(
                        f"Error loading {file_type} dataset from '{file_path}': {e}")

        # Process nodes and edges files
        process_files(nodes_paths, "nodes")
        process_files(edges_paths, "edges")

        logger.info(
            f"Finished loading {len(nodes_paths)} nodes and {len(edges_paths)} edges datasets.")

    def run_query(self, query_code, stop_event=None,  species="human"):
        results = []
        driver = self.human_driver if species == "human" else self.fly_driver
        # use lazy loading for improved performance
        with driver.session() as session:
            result = session.run(query_code)
            for record in result:
                if stop_event is not None and stop_event.is_set():
                    raise TaskCancelledException()
                results.append(record)
        return results

    def query_Generator(self, requests, node_map, limit=None, node_only=False):
        nodes = requests['nodes']
        predicate_map = {}

        if "predicates" in requests and len(requests["predicates"]) > 0:
            predicates = requests["predicates"]

            init_pred = predicates[0]

            if 'predicate_id' not in init_pred:
                for idx, pred in enumerate(predicates):
                    pred['predicate_id'] = f'p{idx}'
                for predicate in predicates:
                    predicate_map[predicate['predicate_id']] = predicate
            else:
                for predicate in predicates:
                    predicate_map[predicate['predicate_id']] = predicate
        else:
            predicates = None

        cypher_queries = []
        match_preds = []
        return_preds = []
        where_preds = []
        match_no_preds = []
        return_no_preds = []
        where_no_preds = []
        node_ids = set()
        clause_list = []
        
        virtual_defs = []

        if not predicates:
            list_of_node_ids = []
            # Case when there are no predicates
            for node in nodes:
                var_name = f"{node['node_id']}"
                match_no_preds.append(self.match_node(node, var_name))
                if node['properties']:
                    where_no_preds.extend(self.where_construct(node, var_name))
                return_no_preds.append(var_name)
                list_of_node_ids.append(var_name)
            if node_only:
                cypher_query = self.construct_optional_clause(
                    match_no_preds, return_no_preds, where_no_preds, limit)
            else:
                cypher_query = self.construct_clause(
                    match_no_preds, return_no_preds, where_no_preds, limit)
            cypher_queries.append(cypher_query)
            query_clauses = {
                "match_no_preds": match_no_preds,
                "return_no_preds": return_no_preds,
                "where_no_preds": where_no_preds,
                "list_of_node_ids": list_of_node_ids,
                "predicates": predicates
            }
            count = self.construct_count_clause(
                query_clauses, node_map, predicate_map)
            cypher_queries.extend(count)
        else:
            for i, predicate in enumerate(predicates):
                predicate_id = predicate['predicate_id']
                predicate_type = predicate['type'].replace(" ", "_").lower()
                source_node = node_map[predicate['source']]
                target_node = node_map[predicate['target']]
                source_var = source_node['node_id']
                target_var = target_node['node_id']

                source_match = self.match_node(source_node, source_var)
                target_match = self.match_node(target_node, target_var)
                
                is_virtual = (predicate_type == 'overlaps_with')

                tmp_where_preds = []
                overlap_constraints = self.construct_overlap_clause(source_var, target_var, predicate_type)
                if overlap_constraints:
                    tmp_where_preds.extend(overlap_constraints)
                    where_preds.extend(overlap_constraints)
                if source_var not in node_ids:
                    tmp_where_preds.extend(self.where_construct(source_node, source_var))
                    where_preds.extend(
                        self.where_construct(source_node, source_var))
                if target_var not in node_ids:
                    tmp_where_preds.extend(self.where_construct(target_node, target_var))
                    where_preds.extend(
                        self.where_construct(target_node, target_var))

                node_ids.add(source_var)
                node_ids.add(target_var)

                # Initialize variable for virtual relationship creation
                virtual_creation = ""

                if is_virtual:
                    # Virtual: Match nodes implicitly
                    match_clause = f"MATCH {source_match}, {target_match}"
                    match_preds.append(f"{source_match}, {target_match}")
                    
                    return_preds.append(predicate_id)

                    # 1. Create string for Main Query
                    virtual_creation = f"WITH *, apoc.create.vRelationship({source_var}, '{predicate_type}', {{source:'virtual'}}, {target_var}) AS {predicate_id}"
                    
                    # 2. Store definition for Count Query (without WITH *)
                    virtual_defs.append(f"apoc.create.vRelationship({source_var}, '{predicate_type}', {{source:'virtual'}}, {target_var}) AS {predicate_id}")

                else:
                    # Physical: Match with explicit relationship
                    return_preds.append(predicate_id) 
                    match_pattern = f"{source_match}-[{predicate_id}:{predicate_type}]->{target_match}"
                    match_clause = f"MATCH {match_pattern}"
                    match_preds.append(match_pattern)

                # Construct the WHERE clause if there are conditions
                where_clause = f"WHERE {' AND '.join(tmp_where_preds)}" if len(tmp_where_preds) >= 1 else ''

                if i == len(predicates) - 1:
                    if return_preds:
                        return_clause = f"RETURN {', '.join(return_preds)}, {', '.join(node_ids)}"
                    else:
                        return_clause = f"RETURN {', '.join(node_ids)}"

                    # Combine all clauses
                    clause_list.append(f"{match_clause} {where_clause} {virtual_creation} {return_clause}")
                else:
                    with_clause = f"WITH {', '.join(return_preds)}, {', '.join(node_ids)}"
                    clause_list.append(f"{match_clause} {where_clause} {virtual_creation} {with_clause}")

            list_of_node_ids = list(node_ids)
            list_of_node_ids.sort()
            full_return_preds = return_preds + list_of_node_ids


            cypher_query = ' '.join(clause_list)
            cypher_queries.append(cypher_query)
            query_clauses = {
                "match_preds": match_preds,
                "full_return_preds": full_return_preds,
                "where_preds": where_preds,
                "list_of_node_ids": list_of_node_ids,
                "return_preds": return_preds,
                "predicates": predicates,
                "virtual_defs": virtual_defs # Pass virtual definitions to count clause
            }
            count = self.construct_count_clause(
                query_clauses, node_map, predicate_map)
            cypher_queries.extend(count)
            
        return cypher_queries

    def construct_clause(self, match_clause, return_clause, where_no_preds, limit):
        match_clause = f"MATCH {', '.join(match_clause)}"
        return_clause = f"RETURN {', '.join(return_clause)}"
        if len(where_no_preds) > 0:
            where_clause = f"WHERE {' AND '.join(where_no_preds)}"
            return f"{match_clause} {where_clause} {return_clause} {self.limit_query(limit)}"
        return f"{match_clause} {return_clause} {self.limit_query(limit)}"

    def construct_optional_clause(self, match_clause, return_clause, where_no_preds, limit):
        optional_clause = ""

        for match in match_clause:
            optional_clause += f"OPTIONAL MATCH {match} "

        return_clause = f"RETURN {', '.join(return_clause)}"
        if len(where_no_preds) > 0:
            where_clause = f"WHERE {' AND '.join(where_no_preds)}"
            return f"{optional_clause} {where_clause} {return_clause} {self.limit_query(limit)}"
        return f"{optional_clause} {return_clause} {self.limit_query(limit)}"

    def construct_count_clause(self, query_clauses, node_map, predicate_map):
        match_no_clause = ''
        where_no_clause = ''
        match_clause = ''
        where_clause = ''
        virtual_setup = ''

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


        if 'virtual_defs' in query_clauses and query_clauses['virtual_defs']:
            virtual_setup = f"WITH *, {', '.join(query_clauses['virtual_defs'])}"

        # 1. Total Count Query
        node_counts = [f"COUNT(DISTINCT {node_id})" for node_id in query_clauses['list_of_node_ids']]
        total_nodes_expr = " + ".join(node_counts) if node_counts else "0"
        
        edge_counts = []
        if 'predicates' in query_clauses and query_clauses['predicates']:
            edge_counts = [f"COUNT(DISTINCT {pred['predicate_id']})" for pred in query_clauses['predicates']]
        total_edges_expr = " + ".join(edge_counts) if edge_counts else "0"

        total_count = f'''
            {match_no_clause}
            {where_no_clause}
            {match_clause}
            {where_clause}
            {virtual_setup}
            RETURN ({total_nodes_expr}) AS total_nodes, ({total_edges_expr}) AS total_edges
        '''

        # 2. Label Count Query
        label_count_parts = []
        for node_id in query_clauses['list_of_node_ids']:
            node_type = node_map[node_id]['type']
            label_count_parts.append(f"COUNT(DISTINCT {node_id}) AS {node_id}_{node_type}")
            
        if 'predicates' in query_clauses and query_clauses['predicates']:
            for pred in query_clauses['predicates']:
                pred_id = pred['predicate_id']
                pred_type = predicate_map[pred_id]['type'].replace(' ', '_')
                label_count_parts.append(f"COUNT(DISTINCT {pred_id}) AS {pred_id}_{pred_type}")

        return_label_clause = "RETURN " + ", ".join(label_count_parts) if label_count_parts else "RETURN 0 as count"

        label_count_query = f'''
            {match_no_clause}
            {where_no_clause}
            {match_clause}
            {where_clause}
            {virtual_setup}
            {return_label_clause}
        '''

        return [total_count, label_count_query]

    def limit_query(self, limit):
        '''
        for now remove the limit from the backend
        and handle it from the client side
        '''
        # if limit:
            # curr_limit = min(1000, int(limit))
        # else:
            # curr_limit = 1000
        if limit:
            return f"LIMIT {limit}"
        return f""

    def match_node(self, node, var_name):
        if node['id']:
            return f"({var_name}:{node['type']} {{id: '{node['id']}'}})"
        else:
            return f"({var_name}:{node['type']})"

    def construct_overlap_clause(self, source_var, target_var, predicate_type):
        """
        Generates WHERE clauses for general genomic overlaps.
        Two intervals overlap if: (StartA < EndB) AND (StartB < EndA)
        """
        conditions = []
    
        if predicate_type == 'overlaps_with':
            # 1. Chromosome Check
            conditions.append(f"{source_var}.chr = {target_var}.chr")
        
            # 2. General Overlap Logic
            # (Source Start < Target End) AND (Target Start < Source End)
            source_start = f"toInteger({source_var}.start)"
            source_end = f"toInteger({source_var}.end)"
            target_start = f"toInteger({target_var}.start)"
            target_end = f"toInteger({target_var}.end)"
        
            conditions.append(f"{source_start} < {target_end}")
            conditions.append(f"{target_start} < {source_end}")

        return conditions

    def where_construct(self, node, var_name):
        """
        Construct WHERE clauses for a node, supporting genomic interval filters.
        - Converts start/end to integers using toInteger() because they may be stored as strings.
        - Supports interval_type: 'within', 'intersects', 'upstream', 'downstream'.
        - Supports offsets for upstream/downstream: 'upstream_distance', 'downstream_distance'.
        """
        properties = []
    
        if node['id']:
            return properties
    
        start = node['properties'].get('start')
        end = node['properties'].get('end')
        interval_type = node['properties'].get('interval_type', 'within')
        upstream_distance = node['properties'].get('upstream_distance', 0)
        downstream_distance = node['properties'].get('downstream_distance', 0)
    
        # Normal properties (NOT start/end/interval fields)
        for key, value in node['properties'].items():
            if key in ['start', 'end', 'interval_type', 'upstream_distance', 'downstream_distance']:
                continue
            properties.append(f"{var_name}.{key} =~ '(?i){value}'")
    
        # Interval logic with start and end
        if start is not None and end is not None:
            start_int = f"toInteger({var_name}.start)"
            end_int = f"toInteger({var_name}.end)"
    
            if interval_type == 'within':
                # Fully contained
                properties.append(f"{start_int} >= {start} AND {end_int} <= {end}")
    
            elif interval_type == 'intersects':
                # Overlaps any part of interval
                properties.append(f"{end_int} >= {start} AND {start_int} <= {end}")
    
            elif interval_type == 'upstream':
                # Node ends before region-start - offset
                properties.append(f"{end_int} <= ({start} - {upstream_distance})")
    
            elif interval_type == 'downstream':
                # Node starts after region-end + offset
                properties.append(f"{start_int} >= ({end} + {downstream_distance})")
    
            else:
                # Fallback: within
                properties.append(f"{start_int} >= {start} AND {end_int} <= {end}")
    
        return properties

    def parse_neo4j_results(self, results, graph_components, result_type):
        (nodes, edges, _, _, meta_data) = self.process_result(
            results, graph_components, result_type)
        return {"nodes": nodes, "edges": edges,
                "node_count": meta_data.get('node_count', 0),
                "edge_count": meta_data.get('edge_count', 0),
                "node_count_by_label": meta_data.get('node_count_by_label', []),
                "edge_count_by_label": meta_data.get('edge_count_by_label', [])
                }

    def parse_and_serialize(self, input, schema, graph_components, result_type):
        parsed_result = self.parse_neo4j_results(
            input, graph_components, result_type)
        return parsed_result

    def convert_to_dict(self, results, schema, graph_components):
        graph_components['properties'] = True
        (_, _, node_dict, edge_dict, _) = self.process_result(
            results, graph_components)
        return (node_dict, edge_dict)

    def process_result_graph(self, results, graph_components):
        node_dict = {}
        visited_relations = set()
        nodes = []
        edges = []
        node_dict = {}
        node_to_dict = {}
        edge_to_dict = {}
        node_type = set()
        edge_type = set()

        named_types = ['gene_name', 'transcript_name',
                       'protein_name', 'pathway_name', 'term_name']
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
                        node_to_dict[node_data['data']
                                     ['type']].append(node_data)
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
                    edge_to_dict[edge_data['data']
                                 ['label']].append(edge_data)

        return (nodes, edges, node_to_dict, edge_to_dict)

    def process_result_count(self, node_and_edge_count, count_by_label, graph_components):
        node_count_by_label = []
        edge_count_by_label = []
        node_count = 0
        edge_count = 0

        node_count += node_and_edge_count.get('total_nodes', 0)
        edge_count += node_and_edge_count.get('total_edges', 0)
        # build edge type set
        node_count_aggregate = {}
        ege_count_aggregate = {}

        if len(count_by_label) != 0:
            # initialize node count aggreate dictionary where the key is the label.
            for node in graph_components['nodes']:
                node_type = node['type']
                node_count_aggregate[node_type] = {'count': 0}

            # initialize edge count aggreate dictionary where the key is the label.
            for predicate in graph_components['predicates']:
                edge_type = predicate['type'].replace(" ", "_").lower()
                ege_count_aggregate[edge_type] = {'count': 0}

            # update node count aggregate dictionary with the count of each label
            for key, value in count_by_label.items():
                node_type_key = '_'.join(key.split('_')[1:])
                if node_type_key in node_count_aggregate:
                    node_count_aggregate[node_type_key]['count'] += value

            # update edge count aggregate dictionary with the count of each label
            for key, value in count_by_label.items():
                edge_type_key = '_'.join(key.split('_')[1:])
                if edge_type_key in ege_count_aggregate:
                    ege_count_aggregate[edge_type_key]['count'] += value

            # update the way node count by label and edge count by label are represented
            for key, value in node_count_aggregate.items():
                node_count_by_label.append(
                    {'label': key, 'count': value['count']})

            for key, value in ege_count_aggregate.items():
                edge_count_by_label.append(
                    {'label': key, 'count': value['count']})

        meta_data = {
            "node_count": node_count,
            "edge_count": edge_count,
            "node_count_by_label": node_count_by_label,
            "edge_count_by_label": edge_count_by_label
        }

        return meta_data

    def process_result(self, results, graph_components, result_type):
        match_result = results
        node_and_edge_count = {}
        count_by_label = {}
        nodes = []
        edges = []
        node_to_dict = {}
        edge_to_dict = {}
        meta_data = {}

        if len(results) > 0:
            node_and_edge_count = results[0]

        if len(results) > 1:
            count_by_label = results[1]

        if result_type == 'graph':
            nodes, edges, node_to_dict, edge_to_dict = self.process_result_graph(
                match_result, graph_components)

        if result_type == 'count':
            meta_data = self.process_result_count(
                node_and_edge_count, count_by_label, graph_components)

        return (nodes, edges, node_to_dict, edge_to_dict, meta_data)

    def parse_id(self, request):
        nodes = request["nodes"]
        named_types = {"gene": "gene_name", "transcript": "transcript_name"}
        prefixes = ["ensg", "enst"]

        for node in nodes:
            is_named_type = node['type'] in named_types
            id = node["id"].lower()
            is_name_as_id = all(not id.startswith(prefix)
                                for prefix in prefixes)
            no_id = node["id"] != ''
            if is_named_type and is_name_as_id and no_id:
                node_type = named_types[node['type']]
                node['properties'][node_type] = node["id"]
                node['id'] = ''
            node["id"] = node["id"].lower()
        return request

    def list_query_generator_source_target(self, source, target, target_ids, relationship):
        source_node = self.match_node(source, "source")
        target_node = self.match_node(target, "target")

        where_clause = ""
        for key, properties in source['properties'].items():
            where_clause += f"source.{key} = '{properties}' AND "

        where_clause += f"target.id IN target_ids"

        where_clause = f"WHERE {where_clause}"

        with_clause = f"WITH {str(target_ids)} AS target_ids"

        match_clause = f"MATCH {source_node}-[{relationship}]->{target_node}"

        return_clause = f"RETURN COLLECT(DISTINCT source.id) AS source_ids, target.id AS target_ids"

        query= f"""
        {with_clause}
        {match_clause}
        {where_clause}
        {return_clause}
        """

        return query

    def list_query_generator_both(self, source, target, source_ids, target_ids, relationship):
        source_node = self.match_node(source, "source")
        target_node = self.match_node(target, "target")

        where_clause = f"source.id IN source_ids AND "
        where_clause += f"target.id IN target_ids"
        where_clause = f"WHERE {where_clause}"

        with_clause = f"WITH {str(source_ids)} AS source_ids, {str(target_ids)} AS target_ids"

        match_clause = f"MATCH {source_node}-[{relationship}]->{target_node}"

        return_clause = "RETURN target.id AS target_ids, COLLECT(DISTINCT source.id) AS source_ids"

        query= f"""
        {with_clause}
        {match_clause}
        {where_clause}
        {return_clause}
        """

        return query

    def parse_list_query(self, results):
        paresed_result = {}
        for result in results:
            source_ids = result['source_ids']
            target_ids = result['target_ids']

            paresed_result[target_ids] = {'node_ids': []}
            paresed_result[target_ids]['node_ids'] = source_ids

        return paresed_result

    def get_total_entity_query(self):
        # generate query to get total entityt count
        query = '''
        MATCH (n)
        RETURN count(n) as count
        ''' 
        return query

    def get_total_connection_query(self):
        # generate query to get total conenction count
        query = '''
        MATCH ()-[r]->()
        RETURN count(r) as count
        '''

        return query

    def get_node_count_by_label_query(self): 
        query = '''
        CALL apoc.meta.stats() YIELD labels
        RETURN labels
        '''     

        return query   

    def get_connection_count_by_label_source_target_query(self):
        query = '''
        CALL db.relationshipTypes() YIELD relationshipType AS type
        CALL apoc.cypher.run(
          '
            MATCH (source)-[r:`'+type+'`]->(target)
            UNWIND labels(source) AS srcLabel
            UNWIND labels(target) AS trgLabel
            RETURN srcLabel AS source, trgLabel AS target, count(r) AS count
          ', {}
        ) YIELD value
        RETURN 
          type,
          value.source AS source,
          value.target AS target,
          value.count AS count
        ORDER BY type, count DESC;
        '''     

        return query

    def get_total_connection_count_by_label_query(self):
        query = '''
        CALL db.relationshipTypes() YIELD relationshipType as type
        CALL apoc.cypher.run('MATCH ()-[:`'+type+'`]->() RETURN count(*) as count',{}) YIELD value
        RETURN type, value.count
        '''

        return query
import logging
from dotenv import load_dotenv
from app.services.query_generator_interface import QueryGeneratorInterface
import glob
import os
from collections import Counter
import re
from app.lib.db_resilience import ResilientDriver, RetryPolicy, QueryType, QueryTimeoutConfig
from app.lib.result_formatter import Result_Formatter
from collections import deque
from typing import Optional

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Shared retry policy
_DEFAULT_POLICY = RetryPolicy(
    max_attempts=5,
    base_delay_s=0.5,
    max_delay_s=30.0,
    backoff_factor=2.0,
    jitter=True,
    retry_on_unknown=True,
)

# Per-query-type timeout configuration.
# All timeouts default to None (indefinite) — original behaviour is preserved.
# Set values here (or at app startup) to enable timeouts, e.g.:
#   _TIMEOUT_CONFIG.timeouts[QueryType.COUNT] = 30.0
#   _TIMEOUT_CONFIG.timeouts[QueryType.GRAPH] = 120.0
#   _TIMEOUT_CONFIG.fallback_results[QueryType.COUNT] = []
_TIMEOUT_CONFIG = QueryTimeoutConfig(
    timeouts={
        QueryType.DEFAULT:   None,   # indefinite
        QueryType.GRAPH:     None,   # indefinite
        QueryType.COUNT:     None,   # indefinite
        QueryType.LIST: None,   # indefinite
        QueryType.LOAD:      None,   # indefinite
        QueryType.SCHEMA:    None,   # indefinite
    },
    fallback_results={},
    warn_threshold_s=None,           # set e.g. to 10.0 to log slow queries
)


class CypherQueryGenerator(QueryGeneratorInterface):
    def __init__(self, dataset_path: str):
        self.human_driver = ResilientDriver(
            uri=os.getenv('HUMAN_NEO4J_URI'),
            auth=(os.getenv('HUMAN_NEO4J_USERNAME'), os.getenv('HUMAN_NEO4J_PASSWORD')),
            retry_policy=_DEFAULT_POLICY,
            timeout_config=_TIMEOUT_CONFIG,
        )
       
        fly_uri = os.getenv('FLY_NEO4J_URI')
        if fly_uri:
            self.fly_driver = ResilientDriver(
                uri=fly_uri,
                auth=(os.getenv('FLY_NEO4J_USERNAME'), os.getenv('FLY_NEO4J_PASSWORD')),
                retry_policy=_DEFAULT_POLICY,
                timeout_config=_TIMEOUT_CONFIG,
            )
        else:
            logger.warning("FLY_NEO4J_URI not set — fly species queries will not be available.")
            self.fly_driver = None
        self.formatter = Result_Formatter()

    def close(self):
        self.human_driver.close()
        if self.fly_driver is not None:
            self.fly_driver.close()

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
                            self.run_query(line, query_type=QueryType.LOAD)
                except Exception as e:
                    logger.error(
                        f"Error loading {file_type} dataset from '{file_path}': {e}")

        # Process nodes and edges files
        process_files(nodes_paths, "nodes")
        process_files(edges_paths, "edges")

        logger.info(
            f"Finished loading {len(nodes_paths)} nodes and {len(edges_paths)} edges datasets.")

    def run_query(self, query_code, stop_event=None, species="human", query_type: QueryType = QueryType.DEFAULT):
        if species != "human":
            if self.fly_driver is None:
                raise RuntimeError("Fly Neo4j driver is not configured. Set FLY_NEO4J_URI.")
            driver = self.fly_driver
        else:
            driver = self.human_driver
        return driver.run_with_retry(query_code, stop_event=stop_event, query_type=query_type)

    def _escape_regex(self, value) -> str:
        """Escape regex special characters in a property value."""
        return re.escape(str(value))
    
    def _find_anchor_node(self, predicates, node_map):
        if not predicates or len(predicates) < 2:
            return None

        per_pred = Counter()
        for pred in predicates:
            for nid in {pred['source'], pred['target']}:
                per_pred[nid] += 1

        n = len(predicates)

        def has_filter(nid):
            node = node_map[nid]
            return bool(node.get('id')) or bool(node.get('properties'))

        # First priority: filtered node that appears in most predicates
        # Sort by: (has_filter DESC, count DESC)
        ranked = sorted(
            per_pred.items(),
            key=lambda x: (1 if has_filter(x[0]) else 0, x[1]),
            reverse=True
        )

        best_nid, best_cnt = ranked[0]

        # Only use as anchor if it appears in at least 2 predicates
        # OR if it's the only filtered node (chain pattern with filter at one end)
        if best_cnt >= 2:
            return best_nid

        # For chain patterns where no node appears in 2+ predicates,
        # pick the filtered node even if it appears in only 1 predicate
        filtered_nodes = [(nid, cnt) for nid, cnt in per_pred.items() if has_filter(nid)]
        if filtered_nodes:
            return max(filtered_nodes, key=lambda x: x[1])[0]

        return None

    def _build_call_subquery(self, predicates, node_map, predicate_map,
                            anchor_var, limit=None, node_only=False, inner_limit=None, strict=True):
        """
        Build a CALL-subquery-scoped Cypher query using independent CALL arms.

        The anchor node is always matched in the outer MATCH with its own
        filters. Every predicate goes into an independent CALL arm.
        This ensures 1 row per anchor node regardless of connection count,
        and avoids Cartesian product row explosion entirely.
        
        Returns:
            cypher_str   - the full query string
            aliases      - list of collect-alias names per arm
            outer_nodes  - [anchor_var]
        """
        anchor_node = node_map[anchor_var]
        anchor_where = self.where_construct(anchor_node, anchor_var)

        # Always use anchor as outer MATCH with its own filters
        outer_match = f"MATCH {self.match_node(anchor_node, anchor_var)}"
        outer_where = f"WHERE {' AND '.join(anchor_where)}" if anchor_where else ""

        # All predicates go into independent CALL arms
        remaining_predicates = predicates

        # Group predicates into independent arms.
        # An arm starts with a predicate touching the anchor.
        # It then greedily pulls in ALL predicates that touch any node
        # already in the arm (multi-branch chains like transcript->pathway
        # AND transcript->protein both get pulled into the same arm).
        # Predicates with NO connection to anchor go into their own arm.
        arms = []
        assigned = set()

        for pred in remaining_predicates:
            if pred['predicate_id'] in assigned:
                continue
            src = pred['source']
            tgt = pred['target']

            arm = [pred]
            assigned.add(pred['predicate_id'])

            # Collect all nodes introduced by this arm so far
            arm_nodes = {src, tgt}

            # Greedily pull in any unassigned predicate that shares a node
            # with the current arm — repeat until no more can be added
            changed = True
            while changed:
                changed = False
                for next_pred in remaining_predicates:
                    if next_pred['predicate_id'] in assigned:
                        continue
                    ns = next_pred['source']
                    nt = next_pred['target']
                    # Only pull in if it connects to a non-anchor arm node
                    # (prevents pulling in unrelated predicates that only
                    # share the anchor — those get their own arm)
                    non_anchor_arm_nodes = arm_nodes - {anchor_var}
                    if ns in non_anchor_arm_nodes or nt in non_anchor_arm_nodes:
                        arm.append(next_pred)
                        assigned.add(next_pred['predicate_id'])
                        arm_nodes.add(ns)
                        arm_nodes.add(nt)
                        changed = True

            arms.append(arm)

        # Build independent CALL arms
        call_blocks = []
        all_aliases = []

        for arm in arms:
            arm_pred_ids = [p['predicate_id'] for p in arm]
            arm_alias = '_'.join(arm_pred_ids)

            match_lines = []
            map_entries = {}
            seen_in_arm = {anchor_var}

            for pred in arm:
                pred_id = pred['predicate_id']
                pred_type = pred['type'].replace(' ', '_').lower()
                src = pred['source']
                tgt = pred['target']
                src_node = node_map[src]
                tgt_node = node_map[tgt]

                src_match_str = self.match_node(src_node, src)
                tgt_match_str = self.match_node(tgt_node, tgt)

                # Build MATCH pattern
                if src == anchor_var:
                    match_lines.append(f"  MATCH ({anchor_var})-[{pred_id}:{pred_type}]->{tgt_match_str}")
                elif tgt == anchor_var:
                    match_lines.append(f"  MATCH {src_match_str}-[{pred_id}:{pred_type}]->({anchor_var})")
                elif src in seen_in_arm:
                    match_lines.append(f"  MATCH ({src})-[{pred_id}:{pred_type}]->{tgt_match_str}")
                elif tgt in seen_in_arm:
                    match_lines.append(f"  MATCH {src_match_str}-[{pred_id}:{pred_type}]->({tgt})")
                else:
                    match_lines.append(f"  MATCH {src_match_str}-[{pred_id}:{pred_type}]->{tgt_match_str}")

                # WHERE conditions for new nodes introduced in this arm
                where_parts = []
                for var in [src, tgt]:
                    if var != anchor_var and var not in seen_in_arm:
                        conds = self.where_construct(node_map[var], var)
                        if conds:
                            where_parts.extend(conds)
                        seen_in_arm.add(var)

                if where_parts:
                    match_lines.append(f"  WHERE {' AND '.join(where_parts)}")

                # Add non-anchor vars and relationship to collect map
                for var in [src, tgt]:
                    if var != anchor_var:
                        map_entries[var] = var
                map_entries[pred_id] = pred_id

            # Build collect expression
            collect_map = '{' + ', '.join(f"{k}: {v}" for k, v in map_entries.items()) + '}'
            collect_expr = f"collect(DISTINCT {collect_map}) AS {arm_alias}"

            inner_lines = match_lines + [f"  RETURN {collect_expr}"]
            call_block = f"CALL ({anchor_var}) {{\n" + '\n'.join(inner_lines) + "\n}"
            call_blocks.append(call_block)
            all_aliases.append(arm_alias)

        # Build outer RETURN — anchor + all arm aliases
        outer_return = f"RETURN {anchor_var}, {', '.join(all_aliases)}"
        limit_clause = f"LIMIT {limit}" if limit else ""

        # strict=True (default): all arms must return data, otherwise the whole
        # result is empty. strict=False: return partial results even if some arms
        # have no data.
        size_checks = ' AND '.join(f"size({alias}) > 0" for alias in all_aliases)
        strict_where = f"WITH * WHERE {size_checks}" if strict else ""

        parts = [outer_match, outer_where] + call_blocks + [strict_where, outer_return, limit_clause]
        parts = [p for p in parts if p.strip()]
        cypher_str = '\n'.join(parts)

        return cypher_str, all_aliases, [anchor_var]

    def query_Generator(self, requests, node_map, limit=None, node_only=False):
        if self.is_in_list_request(requests):
            return self.in_list_query_generator(requests, limit)

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
        
        # Track virtual definitions for the count clause
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
            # Try CALL subquery pattern first — avoids Cartesian product row explosion
            anchor_var = self._find_anchor_node(predicates, node_map=node_map)

            if anchor_var is not None:
                cypher_query, aliases, outer_nodes = self._build_call_subquery(
                    predicates, node_map, predicate_map, anchor_var, limit, node_only,
                    inner_limit=None
                )
                cypher_queries.append(cypher_query)

                # Collect all node_ids touched by predicates for count clause
                all_node_ids = set()
                all_node_ids.add(anchor_var)
                for pred in predicates:
                    all_node_ids.add(pred['source'])
                    all_node_ids.add(pred['target'])
                list_of_node_ids = sorted(all_node_ids)

                # Build flattened match/where for count queries (old-style, no CALL)
                for pred in predicates:
                    pred_id   = pred['predicate_id']
                    pred_type = pred['type'].replace(' ', '_').lower()
                    source_var = pred['source']
                    target_var = pred['target']
                    source_node = node_map[source_var]
                    target_node = node_map[target_var]
                    source_match_str = self.match_node(source_node, source_var)
                    target_match_str = self.match_node(target_node, target_var)

                    is_virtual = (pred_type == 'overlaps_with')

                    overlap_constraints = self.construct_overlap_clause(source_var, target_var, pred_type)
                    if overlap_constraints:
                        where_preds.extend(overlap_constraints)
                    if source_var not in node_ids:
                        where_preds.extend(self.where_construct(source_node, source_var))
                    if target_var not in node_ids:
                        where_preds.extend(self.where_construct(target_node, target_var))
                    node_ids.add(source_var)
                    node_ids.add(target_var)

                    if is_virtual:
                        match_preds.append(f"{source_match_str}, {target_match_str}")
                        virtual_defs.append(
                            f"apoc.create.vRelationship({source_var}, '{pred_type}', "
                            f"{{source:'virtual'}}, {target_var}) AS {pred_id}"
                        )
                    else:
                        match_preds.append(
                            f"{source_match_str}-[{pred_id}:{pred_type}]->{target_match_str}"
                        )
                    return_preds.append(pred_id)

                full_return_preds = return_preds + list_of_node_ids
                query_clauses = {
                    "match_preds": match_preds,
                    "full_return_preds": full_return_preds,
                    "where_preds": where_preds,
                    "list_of_node_ids": list_of_node_ids,
                    "return_preds": return_preds,
                    "predicates": predicates,
                    "virtual_defs": virtual_defs,
                }
                count = self.construct_count_clause(query_clauses, node_map, predicate_map)
                cypher_queries.extend(count)

            else:
                # Fallback: original multi-MATCH WITH chain 
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
                    "virtual_defs": virtual_defs
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
        virtual_setup = '' # To hold the APOC definitions

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

        # Define virtual relationships so the variable 'p0' exists for the RETURN clause
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
    
    def is_in_list_request(self, requests):
        """
        Returns True if any node in the request has a 'ids' list property,
        indicating this is a mixed or pure list query.
        """
        for node in requests['nodes']:
            if isinstance(node.get('ids'), list) and len(node['ids']) > 0:
                return True
            id_val = node.get('id', '')
            if isinstance(id_val, str) and ',' in id_val:
                return True
            for val in node.get('properties', {}).values():
                if isinstance(val, str) and ',' in val:
                    return True
        return False
    
    def _topological_sort_predicates(self, predicates, list_vars):
        """
        Reorders predicates so that every node is matched before it is
        referenced in a WHERE filter. List nodes must be introduced via a
        MATCH before their list filter can be applied.
        """

        pred_ids = [p['predicate_id'] for p in predicates]
        pred_map = {p['predicate_id']: p for p in predicates}

        # Find which predicate first introduces each node as a target
        # A node is only truly "introduced" when it appears as a target
        # in a MATCH — being a source doesn't introduce it
        target_introducer = {}   # node_var -> pred_id that matches it as target
        source_introducer = {}   # node_var -> pred_id that uses it as source

        for pred in predicates:
            src = pred['source']
            tgt = pred['target']
            if tgt not in target_introducer:
                target_introducer[tgt] = pred['predicate_id']
            if src not in source_introducer:
                source_introducer[src] = pred['predicate_id']

        # Build dependency graph
        # dep[pred_id] = set of pred_ids that must come before it
        dep = {pid: set() for pid in pred_ids}

        for pred in predicates:
            pred_id = pred['predicate_id']
            src = pred['source']
            tgt = pred['target']

            # If source is a list node and was introduced as a target
            # in another predicate, that predicate must come first
            if src in list_vars and src in target_introducer:
                introducer = target_introducer[src]
                if introducer != pred_id:
                    dep[pred_id].add(introducer)

            # If target is a list node and was introduced as a target
            # in another predicate, that predicate must come first
            if tgt in list_vars and tgt in target_introducer:
                introducer = target_introducer[tgt]
                if introducer != pred_id:
                    dep[pred_id].add(introducer)

            # If source was already seen as a target in another predicate
            # that predicate must come first
            if src in target_introducer:
                introducer = target_introducer[src]
                if introducer != pred_id:
                    dep[pred_id].add(introducer)

        # Kahn's algorithm
        in_degree = {pid: len(deps) for pid, deps in dep.items()}
        queue = deque(sorted([pid for pid, d in in_degree.items() if d == 0]))
        sorted_pred_ids = []

        while queue:
            pid = queue.popleft()
            sorted_pred_ids.append(pid)
            for other_pid in pred_ids:
                if pid in dep[other_pid]:
                    in_degree[other_pid] -= 1
                    if in_degree[other_pid] == 0:
                        queue.append(other_pid)

        # If cycle detected fall back to original order
        if len(sorted_pred_ids) != len(predicates):
            return predicates

        return [pred_map[pid] for pid in sorted_pred_ids]

    def in_list_query_generator(self, requests, limit=None):
        nodes = requests['nodes']
        predicates = requests.get('predicates', [])

        if not predicates:
            raise ValueError("in_list_query_generator requires at least 1 predicate.")

        # Assign predicate_ids if missing
        for idx, pred in enumerate(predicates):
            if 'predicate_id' not in pred:
                pred['predicate_id'] = f'p{idx}'
                
        node_map = {n['node_id']: n for n in nodes}

        # named_types mirrors parse_id logic — used to detect gene_name vs id
        named_types = {"gene": "gene_name", "transcript": "transcript_name"}
        ensembl_prefixes = ["ENSG", "ENST", "FBT", "FBG"]

        def get_list_prop(node, id_list):
            """
            Determines which property to filter on for a list node.
            - If values look like Ensembl IDs → use 'id'
            - If node type is in named_types → use gene_name / transcript_name
            - Otherwise fall back to 'id'
            """
            if not id_list:
                return 'id'
            sample = str(id_list[0]).upper()
            if any(sample.startswith(p) for p in ensembl_prefixes):
                return 'id'
            return named_types.get(node['type'], 'id')

        # Build list variables for WITH clause — only for list nodes
        list_vars = {}   # var_name -> (id_list, list_var_name, filter_prop)
        list_counter = 0
        for node in nodes:
            var_name = node['node_id']
            if isinstance(node.get('ids'), list) and len(node['ids']) > 0:
                id_list = node['ids']
                list_var = f"list{chr(65 + list_counter)}"
                filter_prop = get_list_prop(node, id_list)
                list_vars[var_name] = (id_list, list_var, filter_prop)
                list_counter += 1
            elif node.get('id', '') and ',' in node.get('id', ''):
                id_list = [i.strip().upper() for i in node['id'].split(',')]
                list_var = f"list{chr(65 + list_counter)}"
                filter_prop = get_list_prop(node, id_list)
                list_vars[var_name] = (id_list, list_var, filter_prop)
                list_counter += 1
            else:
                props = node.get('properties', {})
                for prop_key, prop_val in props.items():
                    if prop_val and isinstance(prop_val, str) and ',' in prop_val:
                        id_list = [i.strip() for i in prop_val.split(',')]
                        list_var = f"list{chr(65 + list_counter)}"
                        list_vars[var_name] = (id_list, list_var, prop_key)
                        list_counter += 1
                        break
        
        predicates = self._topological_sort_predicates(predicates, list_vars)
        # WITH clause — only list variables
        with_parts = [f"{id_list} AS {list_var}" for (id_list, list_var, _) in list_vars.values()]
        with_clause = f"WITH {', '.join(with_parts)}" if with_parts else ""

        def get_node_filter(node, var_name):
            """
            Returns WHERE conditions for a node:
            - list node: var.prop IN listX (prop detected via get_list_prop)
            - single id node: already in MATCH clause, no extra WHERE needed
            - property node: var.prop =~ value
            """
            reserved = {'start', 'end', 'interval_type', 'upstream_distance', 'downstream_distance'}
            conditions = []

            if var_name in list_vars:
                _, list_var, filter_prop = list_vars[var_name]
                conditions.append(f"{var_name}.{filter_prop} IN {list_var}")

            # Additional property filters (non-list, non-reserved)
            props = node.get('properties', {})
            for key, value in props.items():
                if key in reserved:
                    continue
                if not value:
                    continue
                if isinstance(value, str) and ',' in value:
                    continue
                conditions.append(f"{var_name}.{key} =~ '(?i){value}'")

            return conditions

        def get_match_node(node, var_name):
            """
            Returns MATCH node pattern.
            - single non-comma id: (var:Type {id: 'value'})
            - list or property node: (var:Type)
            """
            raw_id = node.get('id', '')
            if raw_id and ',' not in raw_id:
                return f"({var_name}:{node['type']} {{id: '{raw_id}'}})"
            return f"({var_name}:{node['type']})"

        clause_list = []
        all_node_vars = set()
        all_pred_vars = []
        all_where_conditions = []

        for i, predicate in enumerate(predicates):
            predicate_id = predicate['predicate_id']
            predicate_type = predicate['type'].replace(" ", "_").lower()

            source_node = node_map[predicate['source']]
            target_node = node_map[predicate['target']]
            source_var = source_node['node_id']
            target_var = target_node['node_id']

            source_match = get_match_node(source_node, source_var)
            target_match = get_match_node(target_node, target_var)

            match_pattern = (
                f"MATCH {source_match}"
                f"-[{predicate_id}:{predicate_type}]->"
                f"{target_match}"
            )

            # Collect WHERE conditions only for nodes being introduced for the first time
            tmp_conditions = []
            if source_var not in all_node_vars:
                filters = get_node_filter(source_node, source_var)
                tmp_conditions.extend(filters)
                all_where_conditions.extend(filters)
            if target_var not in all_node_vars:
                filters = get_node_filter(target_node, target_var)
                tmp_conditions.extend(filters)
                all_where_conditions.extend(filters)

            all_node_vars.add(source_var)
            all_node_vars.add(target_var)
            all_pred_vars.append(predicate_id)

            where_clause = f"WHERE {' AND '.join(tmp_conditions)}" if tmp_conditions else ""

            if i < len(predicates) - 1:
                # Carry forward list vars + all seen node vars + pred vars so far
                carry_parts = [lv for (_, lv, _) in list_vars.values()]
                with_parts_chain = carry_parts + all_pred_vars + sorted(all_node_vars)
                with_chain = f"WITH {', '.join(with_parts_chain)}"
                clause_list.append(f"{match_pattern} {where_clause} {with_chain}")
            else:
                # Final predicate — RETURN everything
                return_vars = all_pred_vars + sorted(all_node_vars)
                return_clause = f"RETURN {', '.join(return_vars)}"
                clause_list.append(f"{match_pattern} {where_clause} {return_clause}")

        query = f"{with_clause} {' '.join(clause_list)}"
        if limit:
            query += f" LIMIT {limit}"

        # Total count query
        sorted_nodes = sorted(all_node_vars)
        node_counts = " + ".join([f"COUNT(DISTINCT {v})" for v in sorted_nodes])
        edge_counts = " + ".join([f"COUNT(DISTINCT {v})" for v in all_pred_vars])

        # Rebuild match chain without WITH carry for count queries
        count_match_parts = []
        count_where_parts = list(all_where_conditions)
        for predicate in predicates:
            predicate_id = predicate['predicate_id']
            predicate_type = predicate['type'].replace(" ", "_").lower()
            source_node = node_map[predicate['source']]
            target_node = node_map[predicate['target']]
            source_var = source_node['node_id']
            target_var = target_node['node_id']
            source_match = get_match_node(source_node, source_var)
            target_match = get_match_node(target_node, target_var)
            count_match_parts.append(
                f"{source_match}-[{predicate_id}:{predicate_type}]->{target_match}"
            )

        count_match_clause = f"MATCH {', '.join(count_match_parts)}"
        count_where_clause = f"WHERE {' AND '.join(count_where_parts)}" if count_where_parts else ""

        total_count_query = (
            f"{with_clause} {count_match_clause} {count_where_clause} "
            f"RETURN {node_counts} AS total_nodes, {edge_counts} AS total_edges"
        )

        # Count by label query
        label_parts = []
        for v in sorted_nodes:
            node_type = node_map[v]['type']
            label_parts.append(f"COUNT(DISTINCT {v}) AS {v}_{node_type}")
        for pred in predicates:
            pred_id = pred['predicate_id']
            pred_type = pred['type'].replace(' ', '_')
            label_parts.append(f"COUNT(DISTINCT {pred_id}) AS {pred_id}_{pred_type}")

        label_count_query = (
            f"{with_clause} {count_match_clause} {count_where_clause} "
            f"RETURN {', '.join(label_parts)}"
        )

        return [query, total_count_query, label_count_query]

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
            escaped = self._escape_regex(value)
            properties.append(f"{var_name}.{key} =~ '(?i){escaped}'")
    
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

    def parse_and_serialize(self, input, schema, graph_components, result_type):
        return self.formatter.format_result(input, "neo4j", graph_components, result_type)

    def convert_to_dict(self, results, schema, graph_components):
        graph_components['properties'] = True
        res = self.formatter.format_result(results, "neo4j", graph_components, result_type='graph')
        return (res['nodes'], res['edges'])

    def parse_id(self, request):
        nodes = request["nodes"]
        named_types = {"gene": "gene_name", "transcript": "transcript_name"}
        prefixes = ["ENSG", "ENST", "FBT", "FBG"]

        for node in nodes:
            is_named_type = node['type'] in named_types
            id = node["id"].upper()
            is_name_as_id = all(not id.startswith(prefix)
                                for prefix in prefixes)
            no_id = node["id"] != ''
            if is_named_type and is_name_as_id and no_id:
                node_type = named_types[node['type']]
                node['properties'][node_type] = node["id"]
                node['id'] = ''
            node["id"] = node["id"].upper()
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
    
    def get_index_query(self, label: str, name_prop: Optional[str]) -> str:
        """
        Build a Cypher query that returns (id, name) for every node of
        the given label.

        - If name_prop is provided: return it as `name`, skip nodes where
          the property is NULL.
        - If name_prop is None: fall back to `id` as the display name.
        """
        if name_prop:
            return (
                f"MATCH (n:{label}) "
                f"WHERE n.{name_prop} IS NOT NULL AND n.id IS NOT NULL "
                f"RETURN n.id AS id, n.{name_prop} AS name"
            )
        return (
            f"MATCH (n:{label}) "
            f"WHERE n.id IS NOT NULL "
            f"RETURN n.id AS id, n.id AS name"
        )

    def fetch_nodes_for_index(
        self,
        label: str,
        name_prop, 
        species: str,
    ) -> list:
        """
        Run get_index_query for the given label + species and return a
        list of dicts with keys: id, name, label, species.

        Uses the existing run_query() so retry / resilience logic is
        inherited automatically.
        """
        query = self.get_index_query(label, name_prop)
        try:
            records = self.run_query(query, species=species)
        except Exception as e:
            logger.error(f"[Error] fetch_nodes_for_index failed [{label}/{species}]: {e}")
            return []

        docs = []
        for record in records:
            node_id = record.get("id")
            name    = record.get("name")
            if not node_id:
                continue
            # Meilisearch primary key must be a string with no spaces / slashes
            meili_id = f"{label}__{species}__{str(node_id).replace(' ', '_')}"
            docs.append({
                "id": meili_id,
                "neo4j_id": str(node_id),
                "name": str(name) if name else str(node_id),
                "label": label,
                "species": species,
            })
        return docs
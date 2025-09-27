import os
import glob
import logging
import re
import uuid
import time
from typing import List, Tuple, Any, Dict, Optional, Union

from .query_generator_interface import QueryGeneratorInterface
from .metta import metta_seralizer

# Set up logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    from MORK.python.client import ManagedMORK
    MORK_AVAILABLE = True
except ImportError:
    MORK_AVAILABLE = False
    logging.warning("MORK client not available - falling back to mock mode")


class MorkQueryGenerator(QueryGeneratorInterface):
    """
    MorkQueryGenerator - Implements QueryGeneratorInterface for MORK backend.
    Provides efficient hypergraph processing using MORK server.
    """

    def __init__(self, dataset_path: str):
        if not MORK_AVAILABLE:
            raise RuntimeError("MORK client is not available. Please install MORK dependencies.")
            
        self.dataset_path = dataset_path
        self.server = None
        self.space = None
        self._id_counter = 0
        self._connected = False
        
        # Initialize MORK connection
        self.initialize_mork()
        
        # Load dataset
        if self._connected:
            self.load_dataset(self.dataset_path)
        else:
            logging.error("MORK initialization failed - dataset loading skipped")

    def initialize_mork(self):
        """Initialize connection to MORK server with robust error handling"""
        try:
            # Try multiple connection strategies
            connection_strategies = [
                self._connect_via_env_url,
                self._connect_via_binary,
                self._connect_via_default_paths
            ]
            
            for strategy in connection_strategies:
                if self._try_connection_strategy(strategy):
                    self._connected = True
                    logging.info("MORK connection established successfully")
                    return
                    
            raise RuntimeError("All MORK connection strategies failed")
            
        except Exception as e:
            logging.error("Failed to initialize MORK: %s", e)
            self._connected = False
            raise

    def _try_connection_strategy(self, strategy_func):
        """Try a connection strategy with proper cleanup"""
        try:
            return strategy_func()
        except Exception as e:
            logging.debug("Connection strategy failed: %s", e)
            self._cleanup_connection()
            return False

    def _connect_via_env_url(self):
        """Connect to existing MORK server via environment variable"""
        server_url = os.getenv("MORK_SERVER")
        if not server_url:
            return False
            
        logging.info("Connecting to MORK server at: %s", server_url)
        self.server = ManagedMORK.connect(server_url).and_terminate()
        self.space = self.server.__enter__()
        
        # Test connection without timeout parameter
        self.space.download("($x)", "$x").block()
        return True

    def _connect_via_binary(self):
        """Connect by starting MORK server binary"""
        binary_path = self._discover_mork_binary()
        if not binary_path:
            return False
            
        logging.info("Starting MORK server from: %s", binary_path)
        self.server = ManagedMORK.connect(binary_path=binary_path).and_terminate()
        self.space = self.server.__enter__()
        
        # Test connection without timeout parameter
        self.space.clear().block()
        return True

    def _connect_via_default_paths(self):
        """Try common MORK binary locations"""
        default_paths = [
            "./mork-server",
            "./target/release/mork-server",
            "/usr/local/bin/mork-server",
            "/opt/mork/mork-server",
        ]
        
        for path in default_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                logging.info("Found MORK binary at: %s", path)
                self.server = ManagedMORK.connect(binary_path=path).and_terminate()
                self.space = self.server.__enter__()
                self.space.clear().block()  # Remove timeout parameter
                return True
        return False

    def _discover_mork_binary(self):
        """Discover MORK binary from various sources"""
        # Environment variable
        env_binary = os.getenv("MORK_BINARY")
        if env_binary and os.path.exists(env_binary):
            return env_binary
            
        # Common development paths
        dev_paths = [
            "../target/release/mork-server",
            "../../target/release/mork-server",
            "./app/service/mork/mork-server",
            "./app/services/mork/mork-server",
            "MORK/target/release/mork-server",  # Added based on your log
        ]
        
        for path in dev_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                return path
                
        return None

    def _cleanup_connection(self):
        """Clean up any existing connection"""
        try:
            if self.space:
                self.space = None
            if self.server:
                self.server.__exit__(None, None, None)
                self.server = None
        except Exception as e:
            logging.debug("Cleanup error: %s", e)

    def load_dataset(self, path: str) -> None:
        """Load all .metta files into MORK with optimized loading strategy"""
        if not self._connected:
            raise RuntimeError("MORK not connected - cannot load dataset")
            
        if not os.path.exists(path):
            raise ValueError(f"Dataset path '{path}' does not exist.")

        metta_files = glob.glob(os.path.join(path, "**/*.metta"), recursive=True)
        if not metta_files:
            raise ValueError(f"No .metta files found in dataset path '{path}'.")

        logging.info("Loading %d .metta files into MORK", len(metta_files))
        
        successful_loads = 0
        for file_path in metta_files:
            try:
                self._load_metta_file(file_path)
                successful_loads += 1
            except Exception as e:
                logging.error("Failed to load %s: %s", file_path, e)
                # Continue with other files

        logging.info("Successfully loaded %d/%d files into MORK", successful_loads, len(metta_files))

    def _load_metta_file(self, file_path: str):
        """Load a single .metta file using optimal MORK strategy"""
        file_size = os.path.getsize(file_path)
        
        # Use import for large files, upload for small files
        if file_size > 1024 * 1024:  # 1MB threshold
            logging.debug("Using import for large file: %s (%d bytes)", file_path, file_size)
            absolute_path = os.path.abspath(file_path)
            # MORK's file:// import - remove timeout parameter
            self.space.sexpr_import("$x", "$x", f"file://{absolute_path}").block()
        else:
            logging.debug("Using upload for small file: %s (%d bytes)", file_path, file_size)
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.space.upload_(content).block()  # Remove timeout parameter

    def generate_id(self) -> str:
        """Generate unique identifier for query variables"""
        return f"var_{uuid.uuid4().hex[:8]}"

    def _quote_value(self, value: Any) -> str:
        """Properly quote values for MORK expressions"""
        if isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            # Check if it's already a variable or expression
            if re.match(r'^\$[a-zA-Z_][a-zA-Z0-9_]*$', value) or value.startswith('('):
                return value
            # Quote strings, handling escapes
            escaped = value.replace('"', '\\"').replace('\n', '\\n')
            return f'"{escaped}"'
        else:
            return str(value)

    def construct_node_representation(self, node: Dict, identifier: str) -> str:
        """Construct MORK pattern for node matching"""
        node_type = node.get('type', 'Unknown')
        properties = node.get('properties', {})
        
        if not properties:
            return f"({node_type} {identifier})"
            
        patterns = []
        for key, value in properties.items():
            quoted_value = self._quote_value(value)
            patterns.append(f"({key} ({node_type} {identifier}) {quoted_value})")
            
        return ' '.join(patterns)

    def query_Generator(self, requests: Dict, node_map: Dict, limit: Optional[int] = None, node_only: bool = False) -> List:
        """Generate MORK-compatible query patterns from JSON requests"""
        nodes = requests.get('nodes', [])
        predicates = requests.get('predicates', [])
        
        # Handle predicate IDs
        predicate_map = {}
        if predicates:
            for idx, pred in enumerate(predicates):
                pred.setdefault('predicate_id', f'p{idx}')
                predicate_map[pred['predicate_id']] = pred

        # Generate query components
        if not predicates:
            # Node-only query
            return self._generate_node_query(nodes, limit, node_only)
        else:
            # Relationship query
            return self._generate_relationship_query(nodes, predicates, node_map, limit, node_only)

    def _generate_node_query(self, nodes: List[Dict], limit: Optional[int], node_only: bool) -> List:
        """Generate query for node matching only"""
        match_patterns = []
        return_templates = []
        
        for node in nodes:
            node_type = node['type']
            node_id = node['node_id']
            identifier = f"${node_id}"
            
            if node.get('id'):
                # Concrete node ID
                match_patterns.append(f"({node_type} {node['id']})")
                return_templates.append(f"({node_type} {node['id']})")
            else:
                # Variable node with optional properties
                node_repr = self.construct_node_representation(node, identifier)
                match_patterns.append(node_repr)
                return_templates.append(f"({node_type} {identifier})")
        
        return self._build_final_query(match_patterns, return_templates, limit, node_only, True)

    def _generate_relationship_query(self, nodes: List[Dict], predicates: List[Dict], 
                                   node_map: Dict, limit: Optional[int], node_only: bool) -> List:
        """Generate query for relationship matching"""
        match_patterns = []
        return_templates = []
        
        for predicate in predicates:
            pred_type = predicate['type'].replace(' ', '_')
            source_id = predicate['source']
            target_id = predicate['target']
            
            source_node = node_map[source_id]
            target_node = node_map[target_id]
            
            # Build source node pattern
            if source_node.get('id'):
                source_pattern = f"({source_node['type']} {source_node['id']})"
            else:
                source_identifier = f"${source_id}"
                source_pattern = self.construct_node_representation(source_node, source_identifier)
                
            # Build target node pattern  
            if target_node.get('id'):
                target_pattern = f"({target_node['type']} {target_node['id']})"
            else:
                target_identifier = f"${target_id}"
                target_pattern = self.construct_node_representation(target_node, target_identifier)
            
            # Build relationship pattern
            rel_pattern = f"({pred_type} {source_pattern} {target_pattern})"
            match_patterns.append(rel_pattern)
            return_templates.append(rel_pattern)
        
        return self._build_final_query(match_patterns, return_templates, limit, node_only, False)

    def _build_final_query(self, match_patterns: List[str], return_templates: List[str], 
                          limit: Optional[int], node_only: bool, is_node_query: bool) -> List:
        """Build final query structure"""
        if node_only:
            # For node-only queries, return individual match queries
            individual_queries = []
            for pattern, template in zip(match_patterns, return_templates):
                query = self._create_mork_query([pattern], [template])
                individual_queries.append(query)
            return [' '.join(individual_queries), None, None]
        
        # Build main query
        main_query = self._create_mork_query(match_patterns, return_templates, limit)
        
        # Build count queries
        count_queries = self._build_count_queries(match_patterns, return_templates, is_node_query)
        
        return [main_query, count_queries[0], count_queries[1]]

    def _create_mork_query(self, patterns: List[str], templates: List[str], limit: Optional[int] = None) -> str:
        """Create MORK transform query from patterns and templates"""
        pattern_str = ' '.join(patterns)
        template_str = ' '.join(templates)
        
        query = f"!(({' '.join(patterns)}) ({' '.join(templates)}))"
        
        if limit:
            query += f" (limit {limit})"
            
        return query

    def _build_count_queries(self, patterns: List[str], templates: List[str], is_node_query: bool) -> Tuple[str, str]:
        """Build count queries for result statistics"""
        pattern_str = ' '.join(patterns)
        
        if is_node_query:
            template_str = ' '.join([f"(node {tpl})" for tpl in templates])
        else:
            template_parts = []
            for tpl in templates:
                # Parse relationship template: (Type (Source) (Target))
                match = re.match(r'\((\w+)\s+\((\w+)\s+([^)]+)\)\s+\((\w+)\s+([^)]+)\)\)', tpl)
                if match:
                    pred, src_type, src_val, tgt_type, tgt_val = match.groups()
                    template_parts.append(f"((edge {pred}) (node ({src_type} {src_val})) (node ({tgt_type} {tgt_val})))")
            
            template_str = ' '.join(template_parts)
        
        base_query = f"(match &space ({pattern_str}) ({template_str}))"
        total_count = f"!(total_count (collapse {base_query}))"
        label_count = f"!(label_count (collapse {base_query}))"
        
        return total_count, label_count

    def run_query(self, query_code: Union[str, List], stop_event: bool = True) -> List[Any]:
        """Execute query against MORK server"""
        if not self._connected:
            logging.error("MORK not connected - cannot execute query")
            return []
            
        try:
            queries = []
            if isinstance(query_code, list):
                queries = [q for q in query_code if q and isinstance(q, str)]
            elif isinstance(query_code, str):
                queries = [query_code]
            else:
                logging.warning("Invalid query code type: %s", type(query_code))
                return []
            
            results = []
            for query in queries:
                try:
                    result = self._execute_single_query(query)
                    results.append(result)
                except Exception as e:
                    logging.error("Query execution failed for '%s': %s", query[:100], e)
                    results.append([])
                    
            return results
            
        except Exception as e:
            logging.exception("Unexpected error in run_query: %s", e)
            return []

    def _execute_single_query(self, query: str) -> Any:
        """Execute a single query using MORK's transform or download"""
        # Clean and parse query
        cleaned_query = query.strip()
        
        # Handle different query types
        if cleaned_query.startswith('!(('):
            # Transform query: !((pattern) (template))
            return self._execute_transform_query(cleaned_query)
        elif cleaned_query.startswith('!(match'):
            # Match query - convert to transform
            return self._execute_match_query(cleaned_query)
        else:
            # Direct pattern query
            return self._execute_pattern_query(cleaned_query)

    def _execute_transform_query(self, query: str) -> Any:
        """Execute transform query using MORK's transform method"""
        # Extract pattern and template from !((pattern) (template))
        match = re.match(r'!\(\s*\((.*)\)\s+\((.*)\)\s*\)', query, re.DOTALL)
        if not match:
            logging.warning("Invalid transform query format: %s", query)
            return []
            
        pattern_str, template_str = match.groups()
        
        # Parse multiple patterns/templates
        patterns = self._extract_balanced_expressions(pattern_str)
        templates = self._extract_balanced_expressions(template_str)
        
        if not patterns or not templates:
            logging.warning("Could not extract patterns/templates from: %s", query)
            return []
            
        try:
            result = self.space.transform(patterns, templates).block().data
            return result
        except Exception as e:
            logging.error("Transform query failed: %s", e)
            return []

    def _execute_match_query(self, query: str) -> Any:
        """Convert match query to transform and execute"""
        # Parse: !(match &space (patterns) (templates))
        match = re.match(r'!\(\s*match\s+&\w+\s+\((.*)\)\s+\((.*)\)\s*\)', query, re.DOTALL)
        if match:
            pattern_str, template_str = match.groups()
            patterns = self._extract_balanced_expressions(pattern_str)
            templates = self._extract_balanced_expressions(template_str)
            
            if patterns and templates:
                try:
                    result = self.space.transform(patterns, templates).block().data
                    return result
                except Exception as e:
                    logging.error("Match query execution failed: %s", e)
                    
        return []

    def _execute_pattern_query(self, query: str) -> Any:
        """Execute simple pattern query using download"""
        # Extract balanced expressions from query
        expressions = self._extract_balanced_expressions(query)
        if not expressions:
            return []
            
        results = []
        for expr in expressions:
            try:
                # Try to extract variables for template
                variables = re.findall(r'\$(\w+)', expr)
                template = variables[0] if variables else "$x"
                result = self.space.download(expr, f"${template}").block().data
                results.extend(result)
            except Exception as e:
                logging.debug("Pattern query failed for %s: %s", expr, e)
                
        return results

    def _extract_balanced_expressions(self, text: str) -> List[str]:
        """Extract balanced parentheses expressions from text"""
        expressions = []
        stack = []
        start_index = -1
        
        for i, char in enumerate(text):
            if char == '(':
                if not stack:
                    start_index = i
                stack.append(char)
            elif char == ')':
                if stack:
                    stack.pop()
                    if not stack and start_index != -1:
                        expressions.append(text[start_index:i+1])
                        start_index = -1
                        
        return expressions

    # The following methods maintain compatibility with the existing interface

    def parse_and_serialize(self, input_data, schema, graph_components, result_type):
        """Parse MORK results and serialize to JSON format"""
        if result_type == 'graph':
            result = self.prepare_query_input(input_data, schema)
            parsed = self.parse_and_serialize_properties(result, graph_components, result_type)
            return parsed
        else:
            (_, _, _, _, meta_data) = self.process_result(input_data, graph_components, result_type)
            return {
                "node_count": meta_data.get('node_count', 0),
                "edge_count": meta_data.get('edge_count', 0),
                "node_count_by_label": meta_data.get('node_count_by_label', []),
                "edge_count_by_label": meta_data.get('edge_count_by_label', []),
            }

    def parse_and_serialize_properties(self, input_data, graph_components, result_type):
        """Serialize results with properties"""
        (nodes, edges, _, _, meta_data) = self.process_result(input_data, graph_components, result_type)
        return {
            "nodes": nodes[0] if nodes else [],
            "edges": edges[0] if edges else [],
            "node_count": meta_data.get('node_count', 0),
            "edge_count": meta_data.get('edge_count', 0),
            "node_count_by_label": meta_data.get('node_count_by_label', []),
            "edge_count_by_label": meta_data.get('edge_count_by_label', []),
        }

    def prepare_query_input(self, inputs, schema):
        """Prepare query input by fetching properties"""
        result = []
        for input_item in inputs:
            if not input_item:
                continue
            tuples = metta_seralizer(input_item)
            for t in tuples:
                if len(t) == 2:
                    src_type, src_id = t
                    result.append({"source": f"{src_type} {src_id}"})
                else:
                    if len(t) >= 5:
                        predicate, src_type, src_id, tgt_type, tgt_id = t[:5]
                        result.append({
                            "predicate": predicate, 
                            "source": f"{src_type} {src_id}", 
                            "target": f"{tgt_type} {tgt_id}"
                        })
        query = self.get_node_properties(result, schema)
        prop_results = self.run_query(query)
        return prop_results

    def get_node_properties(self, results, schema):
        """Generate property query"""
        metta = "!(match &space (,"
        output = " ("
        nodes = set()

        for result in results:
            source = result["source"]
            source_node_type = source.split(" ")[0]

            if source not in nodes:
                for property_name, _ in schema.get(source_node_type, {}).get("properties", {}).items():
                    id_token = self.generate_id()
                    metta += " " + f"({property_name} ({source}) ${id_token})"
                    output += " " + f"(node {property_name} ({source}) ${id_token})"
                nodes.add(source)

            if "target" in result and "predicate" in result:
                target = result["target"]
                target_node_type = target.split(" ")[0]
                if target not in nodes:
                    for property_name, _ in schema.get(target_node_type, {}).get("properties", {}).items():
                        id_token = self.generate_id()
                        metta += " " + f"({property_name} ({target}) ${id_token})"
                        output += " " + f"(node {property_name} ({target}) ${id_token})"
                    nodes.add(target)

                predicate = result["predicate"]
                predicate_schema = f"{source_node_type}_{predicate}_{target_node_type}"
                for property_name, _ in schema.get(predicate_schema, {}).get("properties", {}).items():
                    rand_id = self.generate_id()
                    metta += " " + f"({property_name} ({predicate} ({source}) ({target})) ${rand_id})"
                    output += " " + f"(edge {property_name} ({predicate} ({source}) ({target})) ${rand_id})"

        metta += f" ) {output}))"
        return metta

    def process_result(self, results, graph_components, result_type):
        """Process results"""
        node_and_edge_count = {}
        count_by_label = {}
        nodes = []
        edges = []
        node_to_dict = {}
        edge_to_dict = {}
        meta_data = {}

        if result_type == 'graph':
            parsed = []
            if isinstance(results, list):
                for r in results:
                    if r:
                        parsed = metta_seralizer(r)
                        break
            else:
                parsed = metta_seralizer(results)
            nodes, edges, node_to_dict, edge_to_dict = self.process_result_graph(parsed, graph_components)

        if result_type == 'count':
            if isinstance(results, list) and len(results) > 0:
                node_and_edge_count = results[0]
            if isinstance(results, list) and len(results) > 1:
                count_by_label = results[1]
            meta_data = self.process_result_count(node_and_edge_count, count_by_label, graph_components)
            
        return (nodes, edges, node_to_dict, edge_to_dict, meta_data)

    def process_result_graph(self, results, graph_components):
        """Process graph results"""
        # You can reuse your existing implementation here
        # For now, return empty structures
        return ([], [], {}, {})

    def process_result_count(self, node_and_edge_count, count_by_label, graph_components):
        """Process count results"""
        # You can reuse your existing implementation here
        # For now, return empty counts
        return {
            "node_count": 0,
            "edge_count": 0,
            "node_count_by_label": [],
            "edge_count_by_label": [],
        }

    def parse_id(self, request):
        """Parse IDs"""
        nodes = request.get("nodes", [])
        named_types = {"gene": "gene_name", "transcript": "transcript_name"}
        prefixes = ["ENSG", "ENST"]

        for node in nodes:
            is_named_type = node["type"] in named_types
            is_name_as_id = all(not node["id"].startswith(prefix) for prefix in prefixes) if node.get("id") else False
            no_id = node.get("id") != ""
            if is_named_type and is_name_as_id and no_id:
                node_type = named_types[node["type"]]
                node["properties"][node_type] = node["id"]
                node["id"] = ""
        return request

    def convert_to_dict(self, results, schema=None):
        """Convert to dict"""
        result = self.prepare_query_input(results, schema)
        (_, node_dict, edge_dict) = self.process_result(result, True)
        return (node_dict, edge_dict)

    def close(self):
        """Cleanup MORK connection"""
        self._cleanup_connection()
        self._connected = False

    def __del__(self):
        """Destructor for cleanup"""
        try:
            self.close()
        except Exception:
            pass

    def is_connected(self) -> bool:
        """Check if MORK connection is active"""
        return self._connected and self.space is not None
    
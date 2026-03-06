from .mork import MORK, ManagedMORK, get_total_counts, get_count_by_label
import os
import glob
from pathlib import Path
from hyperon import MeTTa
from .metta import metta_seralizer
from app import app, perf_logger
from dotenv import load_dotenv
import time
import datetime

load_dotenv()


class MorkQueryGenerator:
    def __init__(self, dataset_path):
        self.server = self.connect()
        self.metta = MeTTa()
        self.current_id = None
        # self.clear_space()
        # self.load_dataset(dataset_path)

    def connect(self):
        mork_url = os.getenv('MORK_URL')
        server = ManagedMORK.connect(url=mork_url)
        return server

    def clear_space(self):
        self.server.clear()

    def load_dataset(self, path):
        if not os.path.exists(path):
            raise ValueError(f"Dataset path '{path}' does not exist.")
        paths = glob.glob(os.path.join(path, "**/*.metta"), recursive=True)
        if not paths:
            raise ValueError(
                f"No .metta files found in dataset path '{path}'.")
        with self.server.work_at("annotation") as annotation:
            for path in paths:
                path = Path(path)
                file_url = path.resolve().as_uri()
                try:
                    annotation.sexpr_import_(file_url).block()
                except Exception as e:
                    print(f"Error loading data: {e}")

    def generate_id(self):
        import uuid
        return str(uuid.uuid4())[:8]

    def construct_node_representation(self, node, identifier):
        node_type = node['type']
        node_representation = ''
        for key, value in node['properties'].items():
            node_representation += f' ({key} ({node_type + " " + identifier}) {value})'
        return node_representation

    def run_query(self, query, stop_event=None, species='human'):
        if isinstance(query, tuple) and len(query) == 3:
            with app.config["annotation_lock"]:
                start_time = time.time()
                timestamp = datetime.datetime.utcnow().isoformat()
                pattern, template, type = query

                with self.server.work_at("annotation") as annotation:
                    annotation.transform(pattern, template).block()
                    result = annotation.download(f"({self.current_id} $x)", "($x)")
                    with annotation.work_at(f"{self.current_id}") as tmp:
                        tmp.clear()

                metta_result = self.metta.parse_all(result.data)
                # Success log
                duration = (time.time() - start_time) * 1000 # in ms

                perf_logger.info(
                    "Query executed",
                    extra={
                        "query": str(query),
                        "timestamp": timestamp,
                        "duration_ms": duration,
                        "species": species,
                        "status": "success"
                    }
                )
                return [metta_result]
        elif isinstance(query, list):
            queries = query
            metta_results = []
            start_time = time.time()
            timestamp = datetime.datetime.utcnow().isoformat()

            for pattern, template, _ in queries:
                # Ensure pattern/template are tuples
                if isinstance(pattern, str):
                    pattern = (pattern,)
                if isinstance(template, str):
                    template = (template,)

                try:
                    with self.server.work_at("annotation") as annotation:
                        annotation.transform(pattern, template).block()
                        result = annotation.download(f"({self.current_id} $x)", "($x)")
                        with annotation.work_at(f"{self.current_id}") as tmp:
                            tmp.clear()
                    metta_result = self.metta.parse_all(result.data)
                    metta_results.extend(metta_result)
                except Exception as e:
                    print("Query failed:", pattern, template)
                    print(e)

            duration = (time.time() - start_time) * 1000  # in ms

            perf_logger.info(
                "Query executed",
                extra={
                    "query": str(query),
                    "timestamp": timestamp,
                    "duration_ms": duration,
                    "species": species,
                    "status": "success"
                }
            )

            return metta_results
        else:
            raise ValueError("query must be a tuple or a list of tuples")

    def query_Generator(self, requests, node_map, limit=None, node_only=False):
        # this will do only transfomration
        nodes = requests['nodes']
        predicate_map = {}

        pattern = []
        template = []

        node_representation = ''
        self.current_id = self.generate_id()

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

        # if there is no predicate
        if not predicates:
            for node in nodes:
                node_type = node["type"]
                node_id = node["node_id"]
                node_identifier = '$' + node["node_id"]

                if node["id"]:
                    essemble_id = node["id"]
                    pattern.append(f'({node_type} {essemble_id})')
                    template.append(f'({self.current_id} ({node_type} {essemble_id}))')
                else:
                    if len(node["properties"]) == 0:
                        pattern.append(f'({node_type} ${node_id})')
                    else:
                        pattern.append(self.construct_node_representation(
                            node, node_identifier))
                    template.append(f'({self.current_id} ({node_type} {node_identifier}))')

            query = (tuple(pattern), tuple(template), 'query')
            total_count_query = (
                tuple(pattern), tuple(template), 'total_count')
            label_count_query = (
                tuple(pattern), tuple(template), 'label_count')

            return [query, total_count_query, label_count_query]
        for predicate in predicates:
            predicate_type = predicate['type'].replace(" ", "_")
            source_id = predicate['source']
            target_id = predicate['target']

            # Handle source node
            source_node = node_map[source_id]
            if not source_node['id']:
                node_identifier = "$" + source_id
                node_representation = self.construct_node_representation(
                    source_node, node_identifier)
                if node_representation != '':
                    pattern.append(node_representation)
                source = f'({source_node["type"]} {node_identifier})'
            else:
                source = f'({str(source_node["type"])} {str(source_node["id"])})'

            # Handle target node
            target_node = node_map[target_id]
            if not target_node['id']:
                target_identifier = "$" + target_id
                node_representation = self.construct_node_representation(
                    target_node, target_identifier)
                if node_representation != '':
                    pattern.append(node_representation)
                target = f'({target_node["type"]} {target_identifier})'
            else:
                target = f'({str(target_node["type"])} {str(target_node["id"])})'

            # Add relationship
            pattern.append(f'({predicate_type} {source} {target})')
            template.append(f'({self.current_id} ({predicate_type} {source} {target}))')

        query = (tuple(pattern), tuple(template), 'query')
        total_count_query = (tuple(pattern), tuple(template), 'total_count')
        label_count_query = (tuple(pattern), tuple(template), 'label_count')
        return [query, total_count_query, label_count_query]

    def prepare_query_input(self, inputs, schema):
        result = []

        for input in inputs:
            if len(input) == 0:
                continue
            tuples = metta_seralizer(input)
            for tuple in tuples:
                if len(tuple) == 2:
                    src_type, src_id = tuple
                    result.append({
                        "source": f"{src_type} {src_id}"
                    })
                else:
                    predicate, src_type, src_id, tgt_type, tgt_id = tuple
                    result.append({
                        "predicate": predicate,
                        "source": f"{src_type} {src_id}",
                        "target": f"{tgt_type} {tgt_id}"
                    })

        if len(result) == 0:
            return "()", [[]], []

        query = self.get_node_properteis(result, schema)
        res = self.run_query(query)
        return query, res, result

    def get_node_properteis(self, results, schema, species="human"):
        pattern = []
        template = []
        nodes = set()
        to_be_removed = ['synonyms', 'accessions']

        for result in results:
            source = result['source']
            source_node_type = result['source'].split(' ')[0]

            if source not in nodes:
                for property in schema[species]['nodes'][source_node_type]['properties']:
                    if property in to_be_removed:
                        continue
                    id = self.generate_id()
                    pattern.append(f'({property} ({source}) ${id})')
                    template.append(f'(tmp (node {property} ({source}) ${id}))')
                nodes.add(source)

            if "target" in result and "predicate" in result:
                target = result['target']
                target_node_type = result['target'].split(' ')[0]

                if target not in nodes:
                    for property in schema[species]['nodes'][target_node_type]['properties']:
                        id = self.generate_id()
                        pattern.append(f'({property} ({target}) ${id})')
                        template.append(f'(tmp (node {property} ({target}) ${id}))')
                    nodes.add(target)

                predicate = result['predicate']
                for property in schema[species]['edges'][predicate]:
                    random = self.generate_id()
                    pattern.append(f'({property} ({predicate} ({source}) ({target})) ${random})')
                    template.append(f'(tmp (edge {property} ({predicate} ({source}) ({target})) ${random}))')

        query = (tuple(pattern), tuple(template), 'query')
        return query

    def parse_and_serialize(self, input, schema, graph_components, result_type):
        if result_type == 'graph':
            query, result, prev_result = self.prepare_query_input(
                input, schema)
            tuples = metta_seralizer(result[0])

            if not tuples:
                nodes, edges = self.parse_and_seralize_no_properties(
                    prev_result)
                return {"nodes": nodes, "edges": edges,
                        "node_count": 0,
                        "edge_count": 0,
                        "node_count_by_label": [],
                        "edge_count_by_label": []
                        }
            else:
                result = self.parse_and_serialize_properties(
                    result, graph_components, result_type)
            return result
        else:
            tt_res = input[0]
            cbl_res = input[1]
            meta_data = {}  # Initialize to avoid unbound variable

            if tt_res:
                meta_data = get_total_counts(input[0])

            if cbl_res:
                meta_data = get_count_by_label(input[1])

            return {
                "node_count": meta_data.get('node_count', 0),
                "edge_count": meta_data.get('edge_count', 0),
                "node_count_by_label": meta_data.get('node_count_by_label', []),
                "edge_count_by_label": meta_data.get('edge_count_by_label', []),
            }

    def parse_and_serialize_properties(self, input, graph_components, result_type):
        (nodes, edges, _, _, meta_data) = self.process_result(
            input, graph_components, result_type)
        return {"nodes": nodes[0], "edges": edges[0],
                "node_count": meta_data.get('node_count', 0),
                "edge_count": meta_data.get('edge_count', 0),
                "node_count_by_label": meta_data.get('node_count_by_label', []),
                "edge_count_by_label": meta_data.get('edge_count_by_label', [])
                }

    def parse_and_seralize_no_properties(self, results):
        nodes = set()
        edges = []

        for result in results:
            if len(result) == 0:
                return [], []
            source = result.get('source')
            target = result.get('target')
            if source:
                nodes.add(source)
            if target:
                nodes.add(target)

            if source and target:
                source_label = source.split(' ')[0]
                target_label = target.split(' ')[0]
                edges.append({
                    "data": {
                        "id": self.generate_id(),
                        "edge_id": f'{source_label}_{result["predicate"]}_{target_label}',
                        "label": result['predicate'],
                        "source": source,
                        "target": target
                    }
                })

        nodes_list = []

        for node in nodes:
            nodes_list.append({
                "data": {
                    "id": node,
                    "type": node.split(' ')[0]
                }
            })

        return nodes_list, edges

    def process_result(self, results, graph_components, result_type):
        node_and_edge_count = {}
        count_by_label = {}
        nodes = []
        edges = []
        node_to_dict = {}
        edge_to_dict = {}
        meta_data = {}

        if result_type == 'graph':
            nodes, edges, node_to_dict, edge_to_dict = self.process_result_graph(
                results[0], graph_components)

        if result_type == 'count':
            if len(results) > 0:
                node_and_edge_count = results[0]

            if len(results) > 1:
                count_by_label = results[1]

            meta_data = self.process_result_count(
                node_and_edge_count, count_by_label, graph_components)

        return (nodes, edges, node_to_dict, edge_to_dict, meta_data)

    def process_result_graph(self, results, graph_components):
        nodes = {}
        relationships_dict = {}
        node_result = []
        edge_result = []
        node_to_dict = {}
        edge_to_dict = {}
        node_type = set()
        edge_type = set()
        tuples = metta_seralizer(results)

        named_types = ['gene_name', 'transcript_name', 'protein_name',
                       'pathway_name', 'term_name']

        for match in tuples:
            graph_attribute = match[0]
            match = match[1:]

            if graph_attribute == "node":
                if len(match) > 4:
                    predicate = match[0]
                    src_type = match[1]
                    src_value = match[2]
                    tgt = list(match[3:])
                else:
                    predicate, src_type, src_value, tgt = match
                if (src_type, src_value) not in nodes:
                    nodes[(src_type, src_value)] = {
                        "id": f"{src_type} {src_value}",
                        "type": src_type,
                    }

                if graph_components['properties']:
                    nodes[(src_type, src_value)][predicate] = tgt
                else:
                    if predicate in named_types:
                        nodes[(src_type, src_value)]['name'] = tgt

                if 'synonyms' in nodes[(src_type, src_value)]:
                    del nodes[(src_type, src_value)]['synonyms']

                if src_type not in node_type:
                    node_type.add(src_type)
                    node_to_dict[src_type] = []
                node_data = {}
                node_data["data"] = nodes[(src_type, src_value)]
                node_to_dict[src_type].append(node_data)
            elif graph_attribute == "edge":
                property_name, predicate, source, source_id, target, target_id = match[:6]
                value = ' '.join(match[6:])

                key = (predicate, source, source_id, target, target_id)
                if key not in relationships_dict:
                    relationships_dict[key] = {
                        "edge_id": f'{source}_{predicate}_{target}',
                        "label": predicate,
                        "source": f"{source} {source_id}",
                        "target": f"{target} {target_id}",
                    }

                if property_name == "source":
                    relationships_dict[key]["source_data"] = value
                else:
                    relationships_dict[key][property_name] = value

                if predicate not in edge_type:
                    edge_type.add(predicate)
                    edge_to_dict[predicate] = []
                edge_data = {}
                edge_data['data'] = relationships_dict[key]
                edge_to_dict[predicate].append(edge_data)
        node_list = [{"data": node} for node in nodes.values()]
        relationship_list = [{"data": relationship}
                             for relationship in relationships_dict.values()]

        node_result.append(node_list)
        edge_result.append(relationship_list)
        return (node_result, edge_result, node_to_dict, edge_to_dict)

    def process_result_count(self, node_and_edge_count, count_by_label, graph_components):
        if len(node_and_edge_count) != 0:
            node_and_edge_count = node_and_edge_count[0].get_object().value
        node_count_by_label = []
        edge_count_by_label = []

        if len(count_by_label) != 0:
            count_by_label = count_by_label[0].get_object().value
            node_label_count = count_by_label['node_label_count']
            edge_label_count = count_by_label['edge_label_count']

            # update the way node count by label and edge count by label are represented
            for key, value in node_label_count.items():
                node_count_by_label.append(
                    {'label': key, 'count': value['count']})
            for key, value in edge_label_count.items():
                edge_count_by_label.append(
                    {'label': key, 'count': value['count']})

        meta_data = {
            "node_count": node_and_edge_count.get('total_nodes', 0),
            "edge_count": node_and_edge_count.get('total_edges', 0),
            "node_count_by_label": node_count_by_label if node_count_by_label else [],
            "edge_count_by_label": edge_count_by_label if edge_count_by_label else []
        }

        return meta_data

    def parse_id(self, request):
        nodes = request["nodes"]
        named_types = {"gene": "gene_name", "transcript": "transcript_name"}
        prefixes = ["ENSG", "ENST"]

        for node in nodes:
            is_named_type = node['type'] in named_types
            is_name_as_id = all(not node["id"].startswith(
                prefix) for prefix in prefixes)
            no_id = node["id"] != ''
            if is_named_type and is_name_as_id and no_id:
                node_type = named_types[node['type']]
                node['properties'][node_type] = node["id"]
                node['id'] = ''
        return request

    def list_query_generator_source_target(
        self, source, target, target_ids, relationship
    ):
        pattern = []
        template = []

        for target_id in target_ids:
            target_id = ":".join(target_id.split("_")).upper()
            go_id = self.generate_id()
            source_type = source["type"]
            target_type = target["type"]
            key = list(source["properties"].keys())[0]
            value = list(source["properties"].values())[0]

            # Single string per logical unit
            pattern.append(f"({key} ({source_type} ${go_id}) {value}) ")
            pattern.append(
                f"({relationship} ({source_type} ${go_id}) ({target_type} {target_id}))"
            )
            template.append(
                f"({self.current_id} ({relationship} ({source_type} ${go_id}) ({target_type} {target_id})))"
            )

        return (tuple(pattern), tuple(template), 'query')

    def list_query_generator_both(
        self, source, target, source_ids, target_ids, relationship
    ):
        exec_list = []
        for source_id in source_ids:
            for target_id in target_ids:
                source_type = source["type"]
                target_type = target["type"]

                pattern = f"({relationship} ({source_type} {source_id}) ({target_type} {target_id}))"
                template = f"({self.current_id} ({relationship} ({source_type} {source_id}) ({target_type} {target_id})))"

                exec_list.append((pattern, template, 'query'))
        return exec_list

    def parse_list_query(self, results):

        # If empty list → return empty
        if not results:
            return {}

        # Detect if it's a double list (list containing a list)
        # Example: [ [...something...] ]
        if len(results) == 1 and isinstance(results[0], list):
            inner = results[0]
        else:
            # Single list case: [...something...]
            inner = results

        # If still empty after normalization → return empty
        if not inner:
            return {}

        tuples = metta_seralizer(inner)
        parsed_result = {}

        for res in tuples:
            type, value_label, value, key_label, key = res

            if key not in parsed_result:
                parsed_result[key] = {"node_ids": []}

            parsed_result[key]["node_ids"].append(value)

        return parsed_result

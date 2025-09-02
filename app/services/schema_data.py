import json
from biocypher import BioCypher
import logging
import yaml
import os
from pathlib import Path

# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

class SchemaManager:
    def __init__(self, schema_config_path: str,
                 biocypher_config_path: str,
                 config_path: str,
                 fly_schema_config_path: str):
        self.human_bcy = BioCypher(schema_config_path=schema_config_path, biocypher_config_path=biocypher_config_path)
        self.fly_bcy = BioCypher(schema_config_path=fly_schema_config_path, biocypher_config_path=biocypher_config_path)
        self.human_schema = self.process_schema(self.human_bcy._get_ontology_mapping()._extend_schema())
        self.fly_schema = self.process_schema(self.fly_bcy._get_ontology_mapping()._extend_schema())
        self.fly_schema_represetnation = self.get_fly_schema_representation(self.fly_bcy._get_ontology_mapping()._extend_schema())
        self.schema = self.merge_schema(self.human_schema, self.fly_schema)
        self.parent_nodes =self.parent_nodes()
        self.parent_edges =self.parent_edges()
        self.graph_info = self.get_graph_info()
        self.filter_schema = self.filter_schema(self.schema)
        self.config_path = config_path
        self.schema_list = self.get_schema_list()
        self.biocypher_config_path = biocypher_config_path
        self.schmea_representation = self.get_schema_represnetion_per_source(self.schema_list)

    def merge_schema(self, human_schema, fly_schema):
        merged_schema = {"fly": {}, "human": {}}

        merged_schema["human"] = human_schema
        merged_schema["fly"] = fly_schema

        return merged_schema

    def get_schema_list(self):
        schema_list = []

        for file in os.listdir(self.config_path):
            schema_dir = Path(__file__).parent / ".." / ".." / "config" / "schema" / file
            with open(schema_dir, 'r') as f:
                file_output = yaml.safe_load(f)
            url = file_output.get('website', None)
            name = file_output.get('name', None)
            file_name = os.path.splitext(file)[0]
            data = {
                'id': name,
                'url': url,
                'name': name,
                'file_name': file_name
            }
            schema_list.append(data)

        return schema_list

    def get_schema_representation(self, schema_list: list):
        schema_representation = {"nodes": {}, "edges": {}}
        schema_dir = Path(__file__).parent / ".." / ".." / "config" / "schema"
        to_remove_nodes = {'ontology term', 'biological process', 'molecular function', 'cellular component'}

        for schema in schema_list:
            schema_file = schema.get("file_name")
            if not schema_file:
                continue

            schema_path = schema_dir / f"{schema_file}.yaml"
            if not schema_path.exists():
                continue

            with open(schema_path, 'r') as file:
                file_output = yaml.safe_load(file)

            nodes = file_output.get('nodes', {})
            edges = file_output.get('relationships', {})

            # Process nodes
            for key, value in nodes.items():
                if key.lower() in to_remove_nodes:
                    continue

                node_key = nodes[key].get('input_label') if nodes[key].get('input_label') else nodes[key].get('output_label')
                if node_key not in schema_representation["nodes"]:
                    schema_representation["nodes"][node_key] = {
                        "label": value.get("input_label", ''),
                        "properties": value.get("properties", {})
                    }

            # Process edges
            for key, value in edges.items():
                edge_key = value.get('input_label') or value.get('output_label')
                source = value.get("source", "").replace('_', ' ').lower()
                target = value.get("target", "").replace('_', ' ').lower()
                if source in to_remove_nodes or target in to_remove_nodes:
                    continue

                if key not in schema_representation["edges"]:
                    schema_representation["edges"][edge_key] = {
                        "source": value.get("source", ''),
                        "target": value.get("target", ''),
                        "label": value.get("output_label") or value.get("input_label", ''),
                        "properties": value.get("properties", {})
                    }

        return schema_representation

    def get_schema_represnetion_per_source(self, schema_list: list):
        schema_representation = {}
        whole_schema = self.get_schema_representation(schema_list)
        schema_dir = Path(__file__).parent /".."/ ".."/ "config" / "schema"
        to_remove_node = ['ontology term', 'biological process', 'molecular function', 'cellular component']
        for schema in schema_list:
            schema_abs_path = str((schema_dir / f"{schema['file_name']}.yaml").resolve())
            with open(schema_abs_path, 'r') as file:
                file_output = yaml.safe_load(file)
                edges = file_output.get('relationships', {})
                name = file_output.get('name', None).upper()

                if name:
                    if name not in schema_representation:
                        schema_representation[name]= {'nodes': {}, 'edges': {}}

                    for key, value in edges.items():
                        edge_key = value.get('input_label') or value.get('output_label')
                        source = value.get('source').replace('_', ' ')
                        target = value.get('target').replace('_', ' ')
                        if source in to_remove_node or target in to_remove_node:
                            continue

                        # Schema-specific edge definition (per schema name)
                        if edge_key not in schema_representation[name]['edges']:
                            schema_representation[name]['edges'][edge_key] = {'source': '', 'target': ''}

                        schema_representation[name]['edges'][edge_key].update(value)
                        schema_representation[name]['edges'][edge_key]['source'] = value.get('source', '')
                        schema_representation[name]['edges'][edge_key]['target'] = value.get('target', '')
                        schema_representation[name]['edges'][edge_key]['label'] = value.get('output_label') if value.get('output_label') else value.get('input_label', '')

                    for key in schema_representation[name]['edges'].keys():
                        source_node_rep = schema_representation[name]['edges'][key]['source']
                        target_node_rep = schema_representation[name]['edges'][key]['target']
                        node_to_add_src = whole_schema['nodes'][source_node_rep]
                        node_to_add_trgt = whole_schema['nodes'][target_node_rep]

                        schema_representation[name]['nodes'][node_to_add_src['label']] = {
                            'label': node_to_add_src['label'],
                            'properties': node_to_add_src['properties']
                        }
                        schema_representation[name]['nodes'][node_to_add_trgt['label']] = {
                            'label': node_to_add_trgt['label'],
                            'properties': node_to_add_trgt['properties']
                        }

        return schema_representation

    def get_fly_schema_representation(self, prime_service):
        fly_schema = {'nodes': {}, 'edges': {}}

        for value in prime_service.values():
            if value.get('is_a') == 'biological entity' or value.get('is_a') == 'position entity':
                continue

            if value.get('represented_as') == 'node':
                if value.get('input_label') == 'ontology term' or value.get('output_label') == 'ontology term':
                    continue
                label = value.get('input_label') if value.get('input_label') else value.get('output_label')
                fly_schema['nodes'][label] = {
                    'label': label,
                    'properties': value.get('properties', {}),
                }
            elif value.get('represented_as') == 'edge':
                if value.get('source') == 'ontology term' or value.get('target') == 'ontology term':
                    continue
                if value.get('source') is not None and value.get('target') is not None:
                    label = value.get('input_label') if value.get('input_label') else value.get('output_label')
                    fly_schema['edges'][label] = {
                        'source': value.get('source'),
                        'target': value.get('target'),
                        'properties': value.get('properties', {}),
                        'input_label': label,
                    }

        return fly_schema

    def process_schema(self, schema):
        process_schema = {}

        for value in schema.values():
            input_label = value.get("input_label")
            output_label = value.get("output_label")
            source = value.get("source")
            target = value.get("target")

            labels = output_label or input_label
            labels = labels if isinstance(labels, list) else [labels]
            sources = source if isinstance(source, list) else [source]
            targets = target if isinstance(target, list) else [target]

            for i_label in labels:
                for s in sources:
                    if s is None:
                        continue
                    for t in targets:
                        s = s.replace(' ', '_')
                        t = t.replace(' ', '_')
                        key_label = f'{s}_{i_label}_{t}' if s and t else i_label
                        process_schema[key_label] = {**value, "key": key_label}

        return process_schema

    def filter_schema(self, schema):
        filtered_schema = {'human': {}, 'fly': {}}

        filtered_schema['human'] = self.filter_schema_by_species(self.human_schema)
        filtered_schema['fly'] = self.filter_schema_by_species(self.fly_schema)

        return filtered_schema

    def filter_schema_by_species(self, schema):
        filtered_schema = {}
        for key, value in schema.items():
            label_list = key.split('_')
            label = ' '.join(label_list)
            if label in self.parent_nodes or label in self.parent_edges:
                continue
            if value.get('represented_as') == 'node':
                continue

            if 'source' not in value or 'target' not in value:
                continue

            source = value.get('source')
            target = value.get('target')

            if source == "ontology term" or target == "ontology term":
                continue

            labels = value.get('output_label') or value.get('input_label')

            if isinstance(source, list) and label_list[0] in source:
                source = label_list[0]

            if isinstance(target, list) and label_list[-1] in target:
                target = label_list[-1]
            filtered_schema[key] = {'source': source,
                                    'target': target,
                                    'label': labels,
                                    'id': key
                                    }

        return filtered_schema

    def parent_nodes(self):
        human_parent_node = self.get_parent_nodes(self.human_schema)
        fly_parent_node = self.get_parent_nodes(self.fly_schema)
        return {"human": human_parent_node, "fly": fly_parent_node}

    def get_parent_nodes(self, schema):
        parent_nodes = set()
        for _, attributes in schema.items():
            if 'represented_as' in attributes and attributes['represented_as'] == 'node' \
                    and 'is_a' in attributes and attributes['is_a'] not in parent_nodes:
                parent_nodes.add(attributes['is_a'])
        return list(parent_nodes)

    def parent_edges(self):
        human_parent_edge = self.get_parent_edges(self.human_schema)
        fly_parent_edge = self.get_parent_edges(self.fly_schema)
        return {"human": human_parent_edge, "fly": fly_parent_edge}

    def get_parent_edges(self, schema):
        parent_edges = set()
        for _, attributes in schema.items():
            is_a_attribute = attributes.get('is_a')

            if isinstance(is_a_attribute, list):
                is_a_attribute = is_a_attribute[0]

            if 'represented_as' in attributes and attributes['represented_as'] == 'edge' \
                    and 'is_a' in attributes and is_a_attribute not in parent_edges:
                parent_edges.add(is_a_attribute)
        return list(parent_edges)

    def get_nodes(self):
        nodes = {"human": {}, "fly": {}}
        nodes["human"] = self.get_node_specied(self.human_schema, self.parent_nodes['human'])
        nodes["fly"] = self.get_node_specied(self.fly_schema, self.parent_nodes['fly'])

        return nodes

    def get_node_specied(self, schema, parent_nodes):
        nodes = {}
        for key, value in schema.items():
            if value['represented_as'] == 'node':
                if key in parent_nodes:
                    continue
                parent = value['is_a']
                currNode = {
                    'type': key,
                    'is_a': parent,
                    'label': value['input_label'],
                    'properties': value.get('properties', {})
                }
                if parent not in nodes:
                    nodes[parent] = []
                nodes[parent].append(currNode)

        return [{'child_nodes': nodes[key], 'parent_node': key} for key in nodes]


    def get_edges(self):
        edges = {"human": {}, "fly": {}}

        edges["human"] = self.get_edges_specied(self.human_schema, self.parent_edges['human'])
        edges["fly"] = self.get_edges_specied(self.fly_schema, self.parent_edges['fly'])

        return edges

    def get_edges_specied(self, schema, parent_edges):
        edges = {}
        for key, value in schema.items():
            if value['represented_as'] == 'edge':
                if key in parent_edges:
                    continue
                label = value.get('output_lable', value['input_label'])
                edge = {
                    'type': key,
                    'label': label,
                    'is_a': value['is_a'],
                    'source': value.get('source', ''),
                    'target': value.get('target', ''),
                    'properties': value.get('properties', {})
                }
                if isinstance(value['is_a'], list):
                    parent = value['is_a'][0]
                else:
                    parent = value['is_a']
                if parent not in edges:
                    edges[parent] = []
                edges[parent].append(edge)
        return [{'child_edges': edges[key], 'parent_edge': key} for key in edges]

    def get_relations_for_node(self, node, specieds='human'):
        if specieds == 'human':
            schema = self.human_schema
        elif specieds == 'fly':
            schema = self.fly_schema
        else:
            raise ValueError("Invalid species specified. Use 'human' or 'fly'.")

        return self.get_relations_for_nodes_specied(node, schema)

    def get_relations_for_nodes_specied(self, node, schema):
        relations = []
        node_label = node.replace('_', ' ')
        for key, value in schema.items():
            if value['represented_as'] == 'edge':
                if 'source' in value and 'target' in value:
                    if value['source'] == node_label or value['target'] == node_label:
                        label = value.get('output_lable', value['input_label'])
                        relation = {
                            'type': key,
                            'label': label,
                            'source': value.get('source', ''),
                            'target': value.get('target', '')
                        }
                        relations.append(relation)
        return relations

    def get_schema():
        with open('schema_config.yaml', 'r') as file:
            prime_service = yaml.safe_load(file)

        schema = {}

        for key in prime_service.keys():
            if type(prime_service[key]) == str:
                continue

            if any(keys in prime_service[key].keys() for keys in ('source', 'target')):
                schema[key] = {
                    'source': prime_service[key]['source'],
                    'target': prime_service[key]['target']
                }

        return schema

    def get_graph_info(self, file_path='./Data/graph_info.json'):
        try:
            with open(file_path, 'r') as file:
                graph_info = json.load(file)
                return graph_info
        except Exception as e:
            return {"error": str(e)}

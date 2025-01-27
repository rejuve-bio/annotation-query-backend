import json
from biocypher import BioCypher
import logging
import yaml

# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

class SchemaManager:
    def __init__(self, schema_config_path: str, biocypher_config_path: str):
        self.bcy = BioCypher(schema_config_path=schema_config_path, biocypher_config_path=biocypher_config_path)
        self.schema = self.process_schema(self.bcy._get_ontology_mapping()._extend_schema())
        self.parent_nodes =self.parent_nodes()
        self.parent_edges =self.parent_edges()
        self.graph_info = self.get_graph_info()
        self.filter_schema = self.filter_schema(self.schema)
    
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
                    for t in targets:
                        key_label = f'{s}_{i_label}_{t}' if s and t else i_label
                        process_schema[key_label] = {**value, "key": key_label}

        return process_schema
    
    def filter_schema(self, schema):
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
        parent_nodes = set()
        for _, attributes in self.schema.items():
            if 'represented_as' in attributes and attributes['represented_as'] == 'node' \
                    and 'is_a' in attributes and attributes['is_a'] not in parent_nodes:
                parent_nodes.add(attributes['is_a'])
        return list(parent_nodes)

    def parent_edges(self):
        parent_edges = set()
        for _, attributes in self.schema.items():
            if 'represented_as' in attributes and attributes['represented_as'] == 'edge' \
                    and 'is_a' in attributes and attributes['is_a'] not in parent_edges:
                parent_edges.add(attributes['is_a'])
        return list(parent_edges)
    
    def get_nodes(self):
        nodes = {}
        for key, value in self.schema.items():
            if value['represented_as'] == 'node':
                if key in self.parent_nodes:
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
        edges = {}
        for key, value in self.schema.items():
            if value['represented_as'] == 'edge':
                if key in self.parent_edges:
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
                parent = value['is_a']
                if parent not in edges:
                    edges[parent] = []
                edges[parent].append(edge)
        return [{'child_edges': edges[key], 'parent_edge': key} for key in edges]

    def get_relations_for_node(self, node):
        relations = []
        node_label = node.replace('_', ' ')
        for key, value in self.schema.items():
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

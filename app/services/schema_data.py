from biocypher import BioCypher
import logging
import yaml

# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

class SchemaManager:
    def __init__(self, schema_config_path: str, biocypher_config_path: str):
        self.bcy = BioCypher(schema_config_path=schema_config_path, biocypher_config_path=biocypher_config_path)
        self.schema = self.bcy._get_ontology_mapping()._extend_schema()
        self.parent_nodes = ["position entity", "coding element", "non coding element", "genomic variant", "epigenomic feature", "3d genome structure", "ontology term", "chromosome chain"]
        self.parent_edges = ["expression", "annotation", "regulatory association"]

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
        edges = []
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
                    'target': value.get('target', '')
                }
                edges.append(edge)
        return edges

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
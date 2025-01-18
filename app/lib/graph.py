from itertools import groupby
from nanoid import generate

class Graph:
    def __init__(self, graph, request):
        self.graph = graph
        self.request = request
        self.new_graph = None
        self.count = {}
    
    def group_graph(self):
        MINIMUM_EDGES_TO_COLLAPSE = 2

        edge_types = set(edge['type'] for edge in self.request['predicates'])

        edge_grouping = []

        for edge_type in edge_types:
            edge_of_types = [edge for edge in self.graph['edges'] if edge['data']['label'] == edge_type.replace(" ", "_")]

            edge_of_types.sort(key=lambda e: e['data']['source'])
            source_groups = {key: list(group) for key, group in groupby(edge_of_types, key=lambda e: e['data']['source'])}

            edge_of_types.sort(key=lambda e: e['data']['target'])
            target_groups = {key: list(group) for key, group in groupby(edge_of_types, key=lambda e: e['data']['target'])}

            grouped_by = "target" if len(source_groups) > len(target_groups) else "source"

            edge_grouping.append({
                'count': len(edge_of_types), 'edge_type': edge_type,
                'grouped_by': grouped_by,
                'groups': source_groups if grouped_by == "source" else target_groups
            })

        edge_groupings = sorted(
            edge_grouping,
            key=lambda x: (x['count'] - len(x['groups'])),
            reverse=True
        )

        self.new_graph = {**self.graph}

        for grouping in edge_groupings:
            sorted_groups = sorted(grouping['groups'].keys(), key=lambda k: len(grouping['groups'][k]), reverse=True)
            
            for key in sorted_groups:
                edges = grouping['groups'][key]

                if len(edges) < MINIMUM_EDGES_TO_COLLAPSE:
                    continue
                
                child_node_ids = [edge['data']['source'] if grouping['grouped_by'] == 'target' else edge['data']['target'] for edge in edges]

                child_nodes = [node for node in self.new_graph['nodes'] if node['data']['id'] in child_node_ids]
                
                parents_of_child_nodes = [node['data'].get('parent') for node in child_nodes]
                unique_parents = list(set(filter(None, parents_of_child_nodes)))

                if len(unique_parents) > 1:
                    continue
                
                all_child_nodes_of_parent = [node for node in self.new_graph['nodes'] 
                                           if node['data'].get('parent') == (unique_parents[0] if unique_parents else None)]

                if unique_parents and len(child_nodes) == len(all_child_nodes_of_parent):
                    self.add_new_edge(unique_parents[0], edges, grouping['grouped_by'])
                    continue

                parent_id = "n" + generate(size=10).replace("-", "")

                parent = {'data': {'id': parent_id, 'type': "parent", 
                                 'parent': unique_parents[0] if unique_parents else None}}

                self.new_graph["nodes"] = [
                    parent,
                    *[
                        {**n, 'data': {**n['data'], 'parent': parent_id}}
                        if n['data']['id'] in child_node_ids else n
                        for n in self.new_graph['nodes']
                    ]
                ]

                self.add_new_edge(parent_id, edges, grouping['grouped_by'])
        
        self.count_nodes()
        return {**self.new_graph, "entity_count_mapping": self.count}

    def add_new_edge(self, parent_id, edges, grouped_by):
        new_edge_id = "e" + generate(size=10).replace("-", "")
        
        new_edge = {
            "data": {
                **edges[0]['data'],
                "id": new_edge_id,
                "target" if grouped_by == "source" else "source": parent_id
            }
        }
        
        filtered_edges = [
            e for e in self.new_graph['edges']
            if not any(
                a['data']['label'] == e['data']['label'] and
                a['data']['target'] == e['data']['target'] and
                a['data']['source'] == e['data']['source']
                for a in edges
            )
        ]
        
        self.new_graph['edges'] = [new_edge] + filtered_edges

    def count_nodes(self):
        self.count = {}
        for node in self.new_graph['nodes']:
            if ('parent' in node['data'] and 
                node['data']['parent'] is not None and 
                node['data']['type'] != 'parent'):
                
                parent_id = node['data']['parent']
                node_type = node['data']['type']

                if parent_id not in self.count:
                    self.count[parent_id] = {}
                if node_type not in self.count[parent_id]:
                    self.count[parent_id][node_type] = {}
                    self.count[parent_id][node_type]['count'] = 0
                self.count[parent_id][node_type]['count'] += 1

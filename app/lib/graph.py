from itertools import groupby
from nanoid import generate

class Graph:
    def __init__(self, graph, request, node_map):
        self.graph = graph
        self.request = request
        self.node_map = node_map
        # minimum number of duplicate edges for which we group nodes together
        self.MINIMUM_EDGES_TO_COLLAPSE = 2
    
    def group_graph(self):
        
        # get all the unique edge types specified in the query
        edge_types = set(f'{self.node_map[edge["source"]]["type"]}_{edge["type"].replace(" ", "_")}_{self.node_map[edge["target"]]["type"]}' for edge in self.request['predicates'])
        print("Edge Types: ", edge_types)
        edge_grouping = []

        '''
        For each edge type in the query, try to group it according to source and then according 
        to target and then compare which grouping works best.
        '''
        for edge_type in edge_types:
            # find all edges of that type
            edge_of_types = [edge for edge in self.graph['edges'] if edge['data']['edge_id'] == edge_type]

            # we need to sort it based on source for the grouping with source to work
            edge_of_types.sort(key=lambda e: e['data']['source'])

            # for each type, try to group with source
            source_groups = {key: list(group) for key, group in groupby(edge_of_types, key=lambda e: e['data']['source'])}

            # we need to sort it based on target for the grouping with target to work
            edge_of_types.sort(key=lambda e: e['data']['target'])

            # for each type, try to group with target
            target_groups = {key: list(group) for key, group in groupby(edge_of_types, key=lambda e: e['data']['target'])}

            # compare which grouping to use. we prefer the one with fewer groups.
            grouped_by = "target" if len(source_groups) > len(target_groups) else "source"

            # append the best grouping for this edge type
            edge_grouping.append({
                'count': len(edge_of_types), 'edge_type': edge_type,
                'grouped_by': grouped_by,
                'groups': source_groups if grouped_by == "source" else target_groups
            })

        '''
        the result of the optimization depends on which edge types we consider 
        first when grouping nodes. We want to start from edges types that could 
        remove most complexity (most number of edges in this case) from the graph.
        '''
        edge_groupings = sorted(
            edge_grouping,
            key=lambda x: (x['count'] - len(x['groups'])),
            reverse=True
        )

        '''
        for each edge group, we create a parent edge that holds nodes with the 
        common edge, we add its id as 'parent' property in the nodes, we create a new edge
        of similar type that connects the newly created parent node instead of individual nodes, 
        we remove the individual edges from the graph.
        '''
        for grouping in edge_groupings:
            ''''
            we should sort the groups for a specific edge type, so that the 
            ones with the most number of  edges are taken care of first.
            '''
            sorted_groups = sorted(grouping['groups'].keys(), key=lambda k: len(grouping['groups'][k]), reverse=True)
            
            # get the duplicated edges
            for key in sorted_groups:
                edges = grouping['groups'][key]
                
                # ignore if there are too few edges to group
                if len(edges) < self.MINIMUM_EDGES_TO_COLLAPSE:
                    continue
                
                # get the IDs of the nodes to be grouped
                child_node_ids = [edge['data']['source'] if grouping['grouped_by'] == 'target' else edge['data']['target'] for edge in edges]
                
                '''
                make sure none ose child nodes have a parent that is already specified for them. 
                If they do have parent properties, it means they have already been grouped for a 
                different edge type and we should skip them.
                '''
                child_nodes = [node for node in self.graph['nodes'] if node['data']['id'] in child_node_ids]
                
                parents_of_child_nodes = [node['data'].get('parent') for node in child_nodes]
                unique_parents = list(set(filter(None, parents_of_child_nodes)))

                # the nodes have different parents, so we can not group them together.
                if len(unique_parents) > 1:
                    continue
                
                
                '''
                the nodes have a common parent. So we can create a new edge that points to
		        their parent rather than to individual nodes. but the parent might have other 
		        additional child nodes so we need to make sure the parent only contains the same nodes.
                '''
                all_child_nodes_of_parent = [node for node in self.graph['nodes'] 
                                           if node['data'].get('parent') == (unique_parents[0] if unique_parents else None)]

                '''
                if they all havere are no other nodes outside this group the the same parent 
                and that have the same parent, we can draw an edge to the existing parent.
                '''
                if unique_parents and len(child_nodes) == len(all_child_nodes_of_parent):
                    self.add_new_edge(unique_parents[0], edges, grouping['grouped_by'])
                    continue
                
                # create the parent node
                parent_id = "n" + generate(size=10).replace("-", "")


                if unique_parents:
                    parent = {'data': {'id': parent_id, 'type': "parent", 'parent': unique_parents[0]}}
                else:
                    parent = {'data': {'id': parent_id, 'type': "parent"}}

                # add the parent node to the graph and add "parent" propery to the child nodes
                self.graph["nodes"] = [
                    parent,
                    *[
                        {**n, 'data': {**n['data'], 'parent': parent_id}}
                        if n['data']['id'] in child_node_ids else n
                        for n in self.graph['nodes']
                    ]
                ]

                self.add_new_edge(parent_id, edges, grouping['grouped_by'])
        
        self.count_nodes()
        result = {**self.graph}
        self.graph = {}
        self.request = {}
        self.node_map = {}
        return result

    def add_new_edge(self, parent_id, edges, grouped_by):
        # add a new edge of the same type that points to the group
        new_edge_id = "e" + generate(size=10).replace("-", "")
        
        new_edge = {
            "data": {
                **edges[0]['data'],
                "id": new_edge_id,
                "target" if grouped_by == "source" else "source": parent_id
            }
        }
        
        filtered_edges = [
            e for e in self.graph['edges']
            if not any(
                a['data']['label'] == e['data']['label'] and
                a['data']['target'] == e['data']['target'] and
                a['data']['source'] == e['data']['source']
                for a in edges
            )
        ]
        
        self.graph['edges'] = [new_edge] + filtered_edges

    def count_nodes(self):
        # count the number of nodes inside each paretn based on its label
        for node in self.graph['nodes']:
            if ('parent' in node['data'] and 
                node['data']['parent'] is not None and 
                node['data']['type'] != 'parent'):
                
                parent_id = node['data']['parent']
                node_type = node['data']['type']


                for to_count in self.graph['nodes']:
                    if to_count['data']['id'] == parent_id:
                        # count the nodes
                        if 'name' in to_count['data']:
                            count = int(to_count['data']['name'].split(" ")[0])
                            label = to_count['data']['name'].split(" ")[1]
                            count += 1
                            to_count['data']['name'] = f"{count} {label}"
                        else:
                            count = 1
                            to_count['data']['name'] = f"{count} {node_type}"

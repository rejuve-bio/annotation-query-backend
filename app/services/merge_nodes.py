import hashlib
import json
from collections import defaultdict
from nanoid import generate
 
def get_connections_for_node(n, graph):
    connections = []
    
    for e in graph['edges']:
        if e['data']['source'] == n['data']['id']:
            connections.append({
                'type': e['data']['label'],
                'node': e['data']['target'],
                'isSource': False
            })
        elif e['data']['target'] == n['data']['id']:
            connections.append({
                'type': e['data']['label'],
                'node': e['data']['source'],
                'isSource': True
            })
    
    return sorted(connections, key=lambda x: json.dumps(x))

def hash_string(input_str):
    return hashlib.blake2b(input_str.encode(), digest_size=16).hexdigest()

def do_grouping(annotation):
    groups = {}
    ids = {}
     
    annotation=json.loads(annotation)
     
    for n in annotation.get('nodes', []):
         
        connections = get_connections_for_node(n, annotation)
         
        key = hash_string(json.dumps(connections))
         
        if key in groups:
            groups[key]['nodes'].append(n)
        else:
            groups[key] = {'connections': connections, 'nodes': [n]}
        
        ids[n['data']['id']] = key
         
    
    print("groups", json.dumps(groups, indent=2))
    
    new_graph = {'edges': [], 'nodes': []}
    
    for k, group in groups.items():
        type_ = group['nodes'][0]['data']['type']
        name = (group['nodes'][0]['data']['name'] if len(group['nodes']) == 1 
                else f"{len(group['nodes'])} {group['nodes'][0]['data']['type']} nodes")
        
        new_node = {'data': {'id': k, 'type': type_, 'name': name}}
        new_graph['nodes'].append(new_node)
        
        edges = [
            {
                'data': {
                    'id': generate(),
                    'label': c['type'],
                    'source': ids[c['node']] if c['isSource'] else k,
                    'target': k if c['isSource'] else ids[c['node']]
                }
            }
            for c in group['connections'] if c['isSource']
        ]
        
        new_graph['edges'].extend(edges)
    
    return new_graph

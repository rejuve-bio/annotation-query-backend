import json
from collections import defaultdict, deque

def find_paths(data, source, target, id=None, properties=None):
   
    graph = defaultdict(list)
     
    for relation, mapping in data.items():
        src_type = mapping["source"]
        tgt_type = mapping["target"]
        graph[src_type].append((tgt_type, relation))
         
    print("graph",graph)
    # BFS to find all paths from source to target
    def bfs_paths(graph, source, target):
        queue = deque([(source, [source])])
        print("queue",queue)
        all_paths = []
        while queue:
            current_node, path = queue.popleft()
            print("current_node",current_node)
            print("path",path)
            if current_node == target:
                all_paths.append(path)
            for neighbor, relation in graph.get(current_node, []):
                if neighbor not in path:  # Avoid cycles
                    queue.append((neighbor, path + [neighbor]))
                    print("queue",queue)
        return all_paths

    paths = bfs_paths(graph, source, target)
    print("paths))))))))))))))))))",paths)

    
    node_map = {}
    nodes = []
    predicates = []
    node_id_counter = 1
    predicate_id_counter = 1
    
    for path in paths:
        for i in range(len(path)):
            node = path[i]
            if node not in node_map:
                node_id = f"n{node_id_counter}"
                node_map[node] = node_id
                print("node",node_map)
                nodes.append({
                    "node_id": node_id,
                    "id": id if id else "",
                    "type": node,
                    "properties": properties if properties else {}
                })
                node_id_counter += 1
            if i < len(path) - 1:
                relation = next(
                    (r for n, r in graph[path[i]] if n == path[i + 1]), None
                )
                 

              
                predicates.append({
                    "predicate_id": f"p{predicate_id_counter}",
                    "type": relation,
                    "source": node_map[path[i]],
                     
                })
                predicate_id_counter += 1

    result = {
        "nodes": nodes,
        "predicates": predicates
    }
    return json.dumps(result, indent=2)

 
data = {
    "associated_with": {"source": "promoter", "target": "gene"},
    "includes": {"source": "transcript", "target": "exon"},
    "transcribed_from": {"source": "transcript", "target": "gene"},
    "transcribed_to": {"source": "gene", "target": "transcript"},
    "translates_to": {"source": "transcript", "target": "protein"},
    "translation_of": {"source": "protein", "target": "transcript"},
    "coexpressed_with": {"source": "gene", "target": "gene"},
    "interacts_with": {"source": "protein", "target": "protein"},
     
    "expressed_in":{"source": "gene", "target": "cl"},
    "expressed_in":{"source": "gene", "target": "clo"},
    "expressed_in":{"source": "gene", "target": "uberon"},
    "expressed_in":{"source": "gene", "target": "efo"},
    "capable_of": {"source": "cl", "target": "go"},
    "part_of": {"source": "cl", "target": "uberon"},
    "gtex_variant_gene": {"source": "snp", "target": "gene"},
    "snp_in_gene": {"source": "snp", "target": "gene"},
    "in_ld_with": {"source": "snp", "target": "snp"}
}

# Example usage: Find all paths from 'promoter' to 'protein'
result_json = find_paths(data, source="gene", target="efo", id=None, properties=None)
print(result_json)

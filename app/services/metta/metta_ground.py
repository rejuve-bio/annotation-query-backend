from hyperon import OperationAtom, SymbolAtom, ExpressionAtom, GroundedAtom, ValueAtom
from .metta_seralizer import recurssive_seralize, metta_seralizer
class Metta_Ground:
    def __init__(self, metta):
        self.metta = metta
        self.register_function()
        
    def register_function(self):
        """Register the function to be called when the metta is triggered."""
        # Create total count and label count operational atom
        total_count = OperationAtom("total_count", self.total_count, unwrap=False)
        label_count = OperationAtom("label_count", self.label_count, unwrap=False)
        
        # Register the operational atom into the atomspace
        self.metta.register_atom("total_count", total_count)
        self.metta.register_atom("label_count", label_count)
        
    def get_distinct_node_edge_count(self, result_list):
        nodes = set()
        edges = []
        
        for i in range(len(result_list)): 
            if result_list[i] == 'node' and i + 2 < len(result_list):
                nodes.add(f'{result_list[i + 1]} {result_list[i + 2]}')
            elif result_list[i] == 'edge' and i + 1 < len(result_list):
                edges.append(result_list[i + 1])
                
        return nodes, edges
        

    def total_count(self, pattern):
        """Count the total number of nodes and edges in the atomspace."""
        expression = pattern.get_children()
        res = recurssive_seralize(expression, [])

        nodes, edges = self.get_distinct_node_edge_count(res)

        result ={'total_nodes': len(nodes), 'total_edges': len(edges)}
        return [ValueAtom(result)]


    def label_count(self, pattern):
        """Count the number of nodes and edges with a specific label in the atomspace."""
        expression = pattern.get_children()
        res = recurssive_seralize(expression, [])

        node_label = {}
        edge_label = {}
        
        nodes, edges = self.get_distinct_node_edge_count(res)
                
        for node in nodes:
            label = node.split(' ')[0]
            
            if label not in node_label:
                node_label[label] = {}
                node_label[label]['count'] = 1
            else:
                node_label[label]['count'] += 1
        
        for edge in edges:
       
            if label not in edge_label:
                edge_label[edge] = {}
                edge_label[edge]['count'] = 1
            else:
                edge_label[edge]['count'] += 1
                
        result = {'node_label_count': node_label, 'edge_label_count': edge_label}
        return [ValueAtom(result)]
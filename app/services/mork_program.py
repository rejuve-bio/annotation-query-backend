"""Staged joins for tree-shaped MORK requests."""

from app.lib.logic import LogicValidationError, POSITIONAL_PROPERTIES, require_safe_property_name
from app.lib.mork_values import normalize_mork_value


class MorkProgram:
    def __init__(self, space):
        self.space = space
        self.lines = []
        self.heads = []

    def head(self):
        name = f"join_{len(self.heads)}"
        self.heads.append(name)
        return name

    def act(self, pattern):
        return f"(ACT {self.space} {pattern})"

    def emit(self, sources, outputs=(), remove=None):
        location = len(self.lines) + 1
        sink = f"(O (- {remove}))" if remove else f"(, {' '.join(outputs)})"
        self.lines.append(f"(exec {location} (I {' '.join(sources)}) {sink})")

    def finish(self):
        # MORK dumps every atom still in the space, including temporary sets.
        for head in self.heads:
            atom = f"({head} $x)"
            self.emit([f"(BTM {atom})"], remove=atom)
        return "\n".join(self.lines) + "\n"


class MorkJoinCompiler:
    def __init__(self, request, space, result_id, safe_atom):
        self.nodes = {node['node_id']: node for node in request['nodes']}
        self.predicates = request.get('predicates', [])
        self.result_id = result_id
        self.safe_atom = safe_atom
        self.program = MorkProgram(space)

    def node(self, node_id, value='$x'):
        return f"({self.safe_atom(self.nodes[node_id]['type'])} {value})"

    def edge(self, index, source='$a', target='$b'):
        predicate = self.predicates[index]
        label = self.safe_atom(predicate['type'].replace(' ', '_'))
        return f"({label} {self.node(predicate['source'], source)} {self.node(predicate['target'], target)})"

    def member(self, head, node_id, value='$x'):
        return f"(BTM ({head} {self.node(node_id, value)}))"

    def filters(self, node_id):
        node = self.nodes[node_id]
        sources = []
        if node.get('ids') or (isinstance(node.get('id'), str) and ',' in node['id']):
            raise LogicValidationError('not supported yet: comma-separated or list node IDs on MORK')
        if node.get('id'):
            sources.append(self.program.act(self.node(node_id, self.safe_atom(node['id']))))
        properties = sorted(node.get('properties', {}).items(), key=lambda item: (
            not item[0].endswith('_name'), item[0] != 'chr', item[0]))
        for name, value in properties:
            require_safe_property_name(name, f"node '{node_id}'")
            if name in POSITIONAL_PROPERTIES:
                raise LogicValidationError(f"not supported yet: position filter '{name}' on MORK")
            if value in (None, '', []):
                continue
            if isinstance(value, (list, dict)) or (isinstance(value, str) and ',' in value):
                raise LogicValidationError('not supported yet: comma-separated or list property values on MORK')
            # A concrete ID must constrain the property patterns too.
            term = self.node(node_id, self.safe_atom(node['id']) if node.get('id') else '$x')
            sources.append(self.program.act(f"({name} {term} {normalize_mork_value(value)})"))
        return sources

    def compile(self):
        p = self.program
        adjacency = {node_id: [] for node_id in self.nodes}
        for index, predicate in enumerate(self.predicates):
            if predicate.get('properties'):
                raise LogicValidationError('not supported yet: edge properties on MORK')
            source, target = predicate['source'], predicate['target']
            adjacency[source].append((index, target))
            adjacency[target].append((index, source))

        filters = {node_id: self.filters(node_id) for node_id in self.nodes}
        # IDs and name filters usually select fewer candidates than type filters.
        def selectivity(node_id):
            node = self.nodes[node_id]
            return (not bool(node.get('id')), not bool(filters[node_id]),
                    not any(name.endswith('_name') and value not in (None, '', [])
                            for name, value in node.get('properties', {}).items()),
                    -len(filters[node_id]))

        root = min(self.nodes, key=selectivity)
        order, parent = [root], {root: None}
        children = {node_id: [] for node_id in self.nodes}
        for node_id in order:
            for index, other in adjacency[node_id]:
                if parent[node_id] == (other, index):
                    continue
                if other in parent:
                    raise LogicValidationError('not supported yet: cyclic or parallel request predicates on MORK')
                parent[other] = (node_id, index)
                children[node_id].append((index, other))
                order.append(other)
        if len(order) != len(self.nodes):
            raise LogicValidationError('not supported yet: disconnected request graphs on MORK')

        # Materialize only filtered node sets; unfiltered sets come from edges.
        selected = {}
        for node_id in order:
            if not filters[node_id] and node_id != root:
                continue
            head = p.head()
            selected[node_id] = head
            value = self.safe_atom(self.nodes[node_id]['id']) if self.nodes[node_id].get('id') else '$x'
            sources = filters[node_id] or [p.act(self.node(node_id, value))]
            p.emit(sources, [f"({head} {self.node(node_id, value)})"])

        reached, edges = {root: selected[root]}, {}
        for node_id in order:
            for index, other in children[node_id]:
                is_source = self.predicates[index]['source'] == node_id
                a, b = ('$a', '$b') if is_source else ('$b', '$a')
                edge = self.edge(index)
                edge_head, node_head = p.head(), p.head()
                sources = [self.member(reached[node_id], node_id, a), p.act(edge)]
                # A bound target is not an ACT prefix; scan once rather than
                # repeating the predicate scan for every candidate target.
                if not is_source:
                    sources.reverse()
                if other in selected:
                    sources.append(self.member(selected[other], other, b))
                p.emit(sources, [f"({edge_head} {edge})", f"({node_head} {self.node(other, b)})"])
                edges[index], reached[other] = edge_head, node_head

        # Reduce from leaves: every child edge must reach a surviving child.
        surviving = {}
        for node_id in reversed(order):
            current = reached[node_id]
            for index, other in children[node_id]:
                is_source = self.predicates[index]['source'] == node_id
                edge = self.edge(index, '$x', '$y') if is_source else self.edge(index, '$y', '$x')
                head = p.head()
                p.emit([self.member(current, node_id), f"(BTM ({edges[index]} {edge}))",
                        self.member(surviving[other], other, '$y')], [f"({head} {self.node(node_id)})"])
                current = head
            surviving[node_id] = current

        # Propagate the reduced root back down so sibling failures also remove
        # edges that looked valid during expansion.
        final = {root: surviving[root]}
        for node_id in order:
            for index, other in children[node_id]:
                is_source = self.predicates[index]['source'] == node_id
                a, b = ('$a', '$b') if is_source else ('$b', '$a')
                edge, head = self.edge(index), p.head()
                p.emit([f"(BTM ({edges[index]} {edge}))", self.member(final[node_id], node_id, a),
                        self.member(surviving[other], other, b)],
                       [f"({head} {self.node(other, b)})", f"({self.result_id} {edge})"])
                final[other] = head
        return p.finish()

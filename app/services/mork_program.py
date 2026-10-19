"""Staged joins for tree-shaped MORK requests."""

from copy import deepcopy

from app.core.config import settings
from app.lib.logic import (
    LogicValidationError, POSITIONAL_PROPERTIES, ensure_has_positive_filter,
    logic_narrows, negated_predicate_ends, normalize_logic, or_predicate_ends,
    require_safe_property_name,
)
from app.lib.mork_values import normalize_mork_value
from app.services.mork_logic import MorkPropertyCompiler


class MorkProgram:
    def __init__(self, space):
        self.space = space
        self.lines = []
        self.heads = []
        self.constants = []

    def head(self):
        name = f"join_{len(self.heads)}"
        self.heads.append(name)
        return name

    def act(self, pattern):
        return f"(ACT {self.space} {pattern})"

    def emit(self, sources, outputs=(), remove=None, sinks=()):
        location = len(self.lines) + 1
        if remove:
            sink = f"(O (- {remove}))"
        elif sinks:
            sink = f"(O {' '.join(sinks)})"
        else:
            sink = f"(, {' '.join(outputs)})"
        self.lines.append(f"(exec {location} (I {' '.join(sources)}) {sink})")

    def finish(self):
        # MORK dumps every atom still in the space, including temporary sets.
        for head in self.heads:
            atom = f"({head} $x)"
            self.emit([f"(BTM {atom})"], remove=atom)
        return "\n".join(self.constants + self.lines) + "\n"


class MorkJoinCompiler:
    def __init__(self, request, space, result_id, safe_atom):
        request = deepcopy(request)
        self.request = request
        self.nodes = {node['node_id']: node for node in request['nodes']}
        self.predicates = request.get('predicates', [])
        self.result_id = result_id
        self.safe_atom = safe_atom
        self.program = MorkProgram(space)
        self.groups = {node_id: [] for node_id in self.nodes}
        self.small_candidates = set()
        if request.get('logic') is not None:
            by_id = {}
            for index, predicate in enumerate(self.predicates):
                predicate_id = predicate.setdefault('predicate_id', f'p{index}')
                if predicate_id in by_id:
                    raise LogicValidationError(f"duplicate predicate_id '{predicate_id}' when 'logic' is used")
                by_id[predicate_id] = predicate
            request['logic'] = normalize_logic(request['logic'], self.nodes, by_id)
            logic = request['logic']
            for group in logic['children'] if logic['operator'] == 'AND' else [logic]:
                if 'predicates' in group:
                    continue
                leaf = group
                while 'nodes' not in leaf:
                    leaf = leaf['children'][0]
                self.groups[leaf['nodes']['node_id']].append(group)
        self.properties = MorkPropertyCompiler(self.program, self.node, self.member, self.candidate_first)

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

    def candidate_first(self, node_id):
        node = self.nodes[node_id]
        names = node.get('properties', {})
        return bool(node_id in self.small_candidates or node.get('id') or any(
            (name.endswith('_name') or name == 'chr') and value not in (None, '', [])
            for name, value in names.items()))

    def select_node(self, node_id, filters, universe=None):
        p = self.program
        current = universe
        if filters:
            current = p.head()
            value = self.safe_atom(self.nodes[node_id]['id']) if self.nodes[node_id].get('id') else '$x'
            sources = [self.member(universe, node_id, value)] if universe else []
            p.emit(sources + filters, [f'({current} {self.node(node_id, value)})'])
        for group in sorted(self.groups[node_id], key=lambda group: not logic_narrows(group)):
            current = self.properties.compile(node_id, group, current)
        return current

    def predicate_groups(self):
        negated, alternatives = {}, []
        logic = self.request.get('logic') or {}
        if logic.get('operator') != 'AND':
            return negated, alternatives
        indexes = {pred['predicate_id']: index for index, pred in enumerate(self.predicates)}
        for group in logic['children']:
            if 'predicates' not in group:
                continue
            if group['operator'] == 'NOT':
                for predicate_id in group['predicates']:
                    index = indexes[predicate_id]
                    negated[index] = negated_predicate_ends(self.predicates[index], self.predicates)
            elif group['operator'] == 'OR' and len(group['predicates']) > 1:
                kept, far = or_predicate_ends(group['predicates'], self.predicates)
                alternatives.append((kept, {indexes[pid] for pid in far}))
        if len({kept for kept, _ in alternatives}) > 1:
            raise LogicValidationError('not supported yet: OR groups on different nodes on MORK')
        return negated, alternatives

    def tree(self, root, node_ids, indexes):
        adjacency = {node_id: [] for node_id in node_ids}
        for index in indexes:
            predicate = self.predicates[index]
            source, target = predicate['source'], predicate['target']
            adjacency[source].append((index, target))
            adjacency[target].append((index, source))
        order, parent = [root], {root: None}
        children = {node_id: [] for node_id in node_ids}
        for node_id in order:
            for index, other in adjacency[node_id]:
                if parent[node_id] == (other, index):
                    continue
                if other in parent:
                    raise LogicValidationError('not supported yet: cyclic or parallel request predicates on MORK')
                parent[other] = (node_id, index)
                children[node_id].append((index, other))
                order.append(other)
        if len(order) != len(node_ids):
            raise LogicValidationError('not supported yet: disconnected request graphs on MORK')
        return order, children

    def exclude_predicate(self, index, kept, far, current, selected, filters):
        p = self.program
        head = p.head()
        node = self.node(kept)
        p.emit([self.member(current, kept)], [f'({head} {node})'])
        forward = self.predicates[index]['source'] == kept
        edge = self.edge(index, '$x', '$f') if forward else self.edge(index, '$f', '$x')

        def sources(candidates):
            terms = [self.member(candidates, kept), p.act(edge)]
            # A bound target is not an ACT prefix: scan this predicate once.
            return terms if forward else list(reversed(terms))

        far_set = selected.get(far)
        if far_set is None and self.groups[far]:
            reached = p.head()
            p.emit(sources(current), [f'({reached} {self.node(far, "$f")})'])
            if self.candidate_first(kept):
                self.small_candidates.add(far)
            far_set = self.select_node(far, filters[far], reached)
        terms = sources(head)
        if far_set:
            terms.append(self.member(far_set, far, '$f'))
        p.emit(terms, remove=f'({head} {node})')
        return head

    def compile(self, properties=False, schema=None, counts=False, limit=None):
        p = self.program
        if not self.nodes:
            raise LogicValidationError('MORK requests need at least one node')
        if settings.REQUIRE_POSITIVE_FILTER:
            ensure_has_positive_filter(self.request)
        for predicate in self.predicates:
            if predicate.get('properties'):
                raise LogicValidationError('not supported yet: edge properties on MORK')
        filters = {node_id: self.filters(node_id) for node_id in self.nodes}
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
            raise LogicValidationError('limit must be a non-negative integer')
        negated, alternatives = self.predicate_groups()
        far_ids = {far for _, far in negated.values()}
        kept_ids = [node_id for node_id in self.nodes if node_id not in far_ids]
        active = [index for index in range(len(self.predicates)) if index not in negated]
        # Check the whole shape too, including predicates that will be negated.
        self.tree(next(iter(self.nodes)), self.nodes, range(len(self.predicates)))
        narrow = {node_id for node_id in self.nodes if filters[node_id] or
                  any(logic_narrows(group) for group in self.groups[node_id])}
        or_far = {self.predicates[index]['target'] if self.predicates[index]['source'] == kept
                  else self.predicates[index]['source'] for kept, indexes in alternatives for index in indexes}

        def selectivity(node_id):
            node = self.nodes[node_id]
            return (not bool(node.get('id')), node_id not in narrow,
                    not self.candidate_first(node_id),
                    not any(kept == node_id for kept, _ in alternatives), -len(filters[node_id]))

        roots = [node_id for node_id in kept_ids if node_id not in or_far]
        root = min(roots, key=selectivity)
        order, children = self.tree(root, kept_ids, active)

        selected = {}
        for node_id in [root] + [node_id for node_id in self.nodes if node_id != root and node_id in narrow]:
            universe = None
            if node_id not in narrow:
                # OR arms can constrain their own far nodes while the kept
                # node has no property filter of its own.
                universe = p.head()
                p.emit([p.act(self.node(node_id))], [f'({universe} {self.node(node_id)})'])
            selected[node_id] = self.select_node(node_id, filters[node_id], universe)

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
                if other not in selected and self.groups[other]:
                    if self.candidate_first(node_id):
                        self.small_candidates.add(other)
                    reached[other] = self.select_node(other, filters[other], node_head)

        # Reduce from leaves: every child edge must reach a surviving child.
        surviving = {}
        for node_id in reversed(order):
            current = reached[node_id]
            for index, (kept, far) in negated.items():
                if kept == node_id:
                    current = self.exclude_predicate(index, kept, far, current, selected, filters)
            grouped = [indexes for kept, indexes in alternatives if kept == node_id]
            optional = set().union(*grouped) if grouped else set()

            def semijoin(index, other, head):
                is_source = self.predicates[index]['source'] == node_id
                edge = self.edge(index, '$x', '$y') if is_source else self.edge(index, '$y', '$x')
                p.emit([self.member(current, node_id), f"(BTM ({edges[index]} {edge}))",
                        self.member(surviving[other], other, '$y')], [f"({head} {self.node(node_id)})"])

            for index, other in children[node_id]:
                if index in optional:
                    continue
                head = p.head()
                semijoin(index, other, head)
                current = head
            for indexes in grouped:
                head = p.head()
                for index, other in children[node_id]:
                    if index in indexes:
                        semijoin(index, other, head)
                current = head
            surviving[node_id] = current

        def propagate(root_head, edge_out):
            # Propagate the reduced root back down so sibling failures also
            # remove edges that looked valid during expansion.
            final = {root: root_head}
            for node_id in order:
                for index, other in children[node_id]:
                    is_source = self.predicates[index]['source'] == node_id
                    a, b = ('$a', '$b') if is_source else ('$b', '$a')
                    edge, head = self.edge(index), p.head()
                    p.emit([f"(BTM ({edges[index]} {edge}))", self.member(final[node_id], node_id, a),
                            self.member(surviving[other], other, b)],
                           [f"({head} {self.node(other, b)})", f"({edge_out} {edge})"])
                    final[other] = head
            return final

        def node_set(final):
            head = p.head()
            for node_id, members in final.items():
                p.emit([self.member(members, node_id)], [f"({head} {self.node(node_id)})"])
            return head

        if limit:
            # Like Cypher's one row per anchor: keep `limit` root nodes with
            # all of their complete matches. Counts still cover every match.
            if counts:
                all_edges = p.head()
                self.count_results(node_set(propagate(surviving[root], all_edges)), all_edges)
                counts = False
            limited = p.head()
            p.emit([self.member(surviving[root], root)],
                   sinks=[f"(head {limit} ({limited} {self.node(root)}))"])
            final = propagate(limited, self.result_id)
        else:
            final = propagate(surviving[root], self.result_id)
        if not active:
            p.emit([self.member(final[root], root)], [f"({self.result_id} {self.node(root)})"])
        if properties or counts:
            node_head = node_set(final)
            if counts:
                self.count_results(node_head, self.result_id)
            if properties:
                self.fetch_properties(node_head, schema or {})
        return p.finish()

    def count_results(self, node_head, edge_head):
        p = self.program
        count_head = f'{self.result_id}_cnt'
        p.emit([f'(BTM ({node_head} $node))'],
               sinks=[f'(count ({count_head} total node $count) $count $node)'])
        for node_type in sorted({node['type'] for node in self.nodes.values()}):
            node = f'({self.safe_atom(node_type)} $x)'
            p.emit([f'(BTM ({node_head} {node}))'],
                   sinks=[f'(count ({count_head} node {node_type} $count) $count $x)'])
        p.emit([f'(BTM ({edge_head} ($label $source $target)))'],
               sinks=[f'(count ({count_head} total edge $count) $count ($label $source $target))'])
        for label in sorted({pred['type'].replace(' ', '_') for pred in self.predicates}):
            label = self.safe_atom(label)
            p.emit([f'(BTM ({edge_head} ({label} $source $target)))'],
                   sinks=[f'(count ({count_head} edge {label} $count) $count ($source $target))'])

    def fetch_properties(self, node_head, schema):
        p = self.program
        for node_type in sorted({node['type'] for node in self.nodes.values()}):
            node = f"({self.safe_atom(node_type)} $x)"
            for name in schema.get('nodes', {}).get(node_type, {}).get('properties', {}):
                if name in ('synonym', 'synonyms', 'accessions'):
                    continue
                require_safe_property_name(name, f"schema for '{node_type}'")
                p.emit([f"(BTM ({node_head} {node}))", p.act(f"({name} {node} $value)")],
                       [f"(tmp (node {name} {node} $value))"])
        for index in range(len(self.predicates)):
            edge = self.edge(index)
            label = self.predicates[index]['type'].replace(' ', '_')
            for name in schema.get('edges', {}).get(label, {}).get('properties', {}):
                require_safe_property_name(name, f"schema for '{label}'")
                p.emit([f"(BTM ({self.result_id} {edge}))", p.act(f"({name} {edge} $value)")],
                       [f"(tmp (edge {name} {edge} $value))"])

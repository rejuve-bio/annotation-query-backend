"""Property logic as candidate-set operations inside a MORK program."""

from app.lib.logic import LogicValidationError, logic_narrows
from app.lib.mork_values import normalize_mork_value


class MorkPropertyCompiler:
    def __init__(self, program, node, member, candidate_first):
        self.program = program
        self.node = node
        self.member = member
        self.candidate_first = candidate_first

    def property_sources(self, node_id, name, value, universe=None):
        sources = [self.program.act(f'({name} {self.node(node_id)} {value})')]
        if universe:
            sources.insert(0, self.member(universe, node_id))
        return sources

    def property_set(self, node_id, name, values, universe):
        p = self.program
        head = p.head()
        values = sorted({normalize_mork_value(value) for value in values})
        if len(values) > 8:
            # ACT-first scans the property once instead of once per value.
            table = p.head()
            p.constants.extend(f'({table} {value})' for value in values)
            sources = [p.act(f'({name} {self.node(node_id)} $value)'), f'(BTM ({table} $value))']
            if universe:
                sources.append(self.member(universe, node_id))
            p.emit(sources, [f'({head} {self.node(node_id)})'])
        else:
            for value in values:
                p.emit(self.property_sources(node_id, name, value, universe),
                       [f'({head} {self.node(node_id)})'])
        return head

    def compile(self, node_id, group, universe=None):
        if 'nodes' in group:
            parts = [(name, values) for name, values in group['nodes']['properties'].items()]
            if any(',' in str(value) for _, values in parts for value in values):
                raise LogicValidationError('not supported yet: comma-separated property values on MORK; use a list in logic')
        else:
            parts = group['children']
        operator = group['operator']
        p = self.program
        node = self.node(node_id)

        def narrows(part):
            return isinstance(part, tuple) or logic_narrows(part)

        def compile_part(part, candidates):
            if isinstance(part, tuple):
                return self.property_set(node_id, *part, candidates)
            return self.compile(node_id, part, candidates)

        if operator == 'AND':
            parts = sorted(parts, key=lambda part: (
                not narrows(part),
                not (isinstance(part, tuple) and part[0].endswith('_name')),
                not (isinstance(part, tuple) and part[0] == 'chr')))
            simple = [part for part in parts if isinstance(part, tuple) and len(part[1]) == 1]
            current = universe
            if len(simple) > 1:
                current = p.head()
                sources = [self.member(universe, node_id)] if universe else []
                sources.extend(p.act(f'({name} {node} {normalize_mork_value(values[0])})')
                               for name, values in simple)
                p.emit(sources, [f'({current} {node})'])
                parts = [part for part in parts if part not in simple]
            for part in parts:
                current = compile_part(part, current)
            return current

        if operator == 'OR':
            head = p.head()
            for part in parts:
                child = compile_part(part, universe)
                p.emit([self.member(child, node_id)], [f'({head} {node})'])
            return head

        if universe is None:
            raise LogicValidationError('NOT on MORK needs a positive filter or a matching predicate')
        head = p.head()
        p.emit([self.member(universe, node_id)], [f'({head} {node})'])
        for part in parts:
            if isinstance(part, tuple) and len(part[1]) <= 8:
                name, values = part
                for value in sorted({normalize_mork_value(v) for v in values}):
                    sources = self.property_sources(node_id, name, value, head)
                    if not self.candidate_first(node_id):
                        sources.reverse()
                    p.emit(sources, remove=f'({head} {node})')
            else:
                child = compile_part(part, universe)
                p.emit([self.member(head, node_id), self.member(child, node_id)],
                       remove=f'({head} {node})')
        return head

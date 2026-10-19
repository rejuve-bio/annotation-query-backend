"""Small S-expression reader for MORK program output."""

import re


_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+')


def parse_mork_output(text):
    """Read atoms as nested tuples, preserving symbol and string spelling."""
    atoms, stack = [], []
    position = 0
    for match in _TOKEN.finditer(text):
        if text[position:match.start()].strip():
            raise ValueError('Invalid MORK output: unterminated string')
        position = match.end()
        token = match.group()
        if token == '(':
            stack.append([])
        elif token == ')':
            if not stack:
                raise ValueError('Invalid MORK output: unexpected closing parenthesis')
            atom = tuple(stack.pop())
            if stack:
                stack[-1].append(atom)
            else:
                atoms.append(atom)
        elif stack:
            stack[-1].append(token)
        else:
            raise ValueError('Invalid MORK output: expected a parenthesized atom')
    if text[position:].strip():
        raise ValueError('Invalid MORK output: unterminated string')
    if stack:
        raise ValueError('Invalid MORK output: unclosed expression')
    return atoms


def serialize_mork_atom(atom):
    if isinstance(atom, tuple):
        return '(' + ' '.join(serialize_mork_atom(child) for child in atom) + ')'
    return atom


def flatten_mork_value(value):
    """Keep compound property values in the existing flat list representation."""
    if isinstance(value, tuple):
        result = []
        for child in value:
            item = flatten_mork_value(child)
            result.extend(item if isinstance(item, list) else [item])
        return result
    return value


def parse_mork_counts(inputs):
    """Read distinct counts; empty MORK count sinks produce no atom."""
    totals, nodes, edges = {}, {}, {}
    found = False
    for atoms in inputs:
        for atom in atoms:
            if len(atom) != 4 or not isinstance(atom[0], str) or not atom[0].endswith('_cnt'):
                continue
            _, kind, label, value = atom
            if kind not in ('total', 'node', 'edge'):
                continue
            if not isinstance(value, str) or not value.isascii() or not value.isdigit():
                raise ValueError(f'Invalid MORK count: {value!r}')
            found = True
            target = totals if kind == 'total' else nodes if kind == 'node' else edges
            target[label] = int(value)
    if not found:
        return None
    return {
        'node_count': totals.get('node', sum(nodes.values())),
        'edge_count': totals.get('edge', sum(edges.values())),
        # MORK output order follows set iteration; sort for stable responses.
        'node_count_by_label': [{'label': label, 'count': count} for label, count in sorted(nodes.items())],
        'edge_count_by_label': [{'label': label, 'count': count} for label, count in sorted(edges.items())],
    }

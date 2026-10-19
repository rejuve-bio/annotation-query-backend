"""Neighbourhood expansion on MORK.

Same request and result shape as CypherQueryGenerator.expand_neighbourhood.
Each hop is one MORK program: the frontier goes in as atoms, the program
finds the frontier's edges (at most `node_limit + 1` per node, so a hub cannot
flood the output), then fetches the properties of the returned nodes and
edges. Python applies the hop and per-node limits exactly like the Cypher
version, so truncation means the same on both backends.
"""

import logging
import time
from collections import Counter, defaultdict

from app.constants import NEIGHBOURHOOD_HOP_TIMEOUT_S, NEIGHBOURHOOD_MAX_TOTAL_NODES
from app.error import NeighbourhoodUnavailableError, TaskCancelledException
from app.services.mork_neighbourhood_index import READY, SYMMETRIC_LABELS
from app.services.mork_output import serialize_mork_atom
from app.services.mork_program import MorkProgram

logger = logging.getLogger(__name__)

# Property keys tried, in order, for a node's display name (as on Cypher).
NAME_KEYS = ("gene_name", "transcript_name", "protein_name", "pathway_name",
             "term_name", "allele_symbol", "group_name", "reaction_name", "name")
# 'synonym(s)' can be thousands of characters per node.
SKIP_NODE_PROPERTIES = frozenset({"id", "synonym", "synonyms"})

INDEX_NOT_READY = ("The MORK neighbourhood index for {species} is being built from the current data; "
                   "try again in a few minutes")


def _check_cancelled(stop_event):
    if stop_event is not None and stop_event.is_set():
        raise TaskCancelledException()


def _symbol(value):
    """A request value as a single MeTTa symbol, or None if it can't be one."""
    value = str(value)
    if not value or value[0] in "$;" or any(ch in "()\"' \t\r\n\\" for ch in value):
        return None
    return value


def _value(values):
    """One value as a string; several (one atom each in MORK) as a sorted list."""
    values = sorted({serialize_mork_atom(v) if isinstance(v, tuple) else v for v in values})
    return values[0] if len(values) == 1 else values


class MorkNeighbourhood:
    def __init__(self, generator, species):
        self.generator = generator
        self.species = species
        self.index = generator.neighbourhood_index
        self.space = generator.space

    def vocabulary(self):
        """The index's vocabulary; until the whole index is built, requests are refused."""
        vocabulary = self.index.vocabulary()
        if vocabulary is None or self.index.status() != READY:
            from app.workers.neighbourhood_task import request_index_build
            request_index_build(self.species)
            raise NeighbourhoodUnavailableError(INDEX_NOT_READY.format(species=self.species))
        return vocabulary

    # -- validation --------------------------------------------------------

    def validate(self, request):
        vocabulary = self.vocabulary()
        node_types = set(vocabulary["node_types"])
        labels = {label for _, label, _ in vocabulary["triples"]}
        property_keys = {key for keys in vocabulary["node_properties"].values() for key in keys}
        property_keys |= {key for keys in vocabulary["edge_properties"].values() for key in keys}
        species = self.species
        errors = []
        if request["seed"]["type"] not in node_types:
            errors.append(f"Unknown node type for {species}: {request['seed']['type']!r}")
        for i, hop in enumerate(request.get("hops") or []):
            for edge_type in hop.get("edge_types") or []:
                if edge_type not in labels:
                    errors.append(f"hops[{i}]: unknown edge type for {species}: {edge_type!r}")
            for node_type in hop.get("node_types") or []:
                if node_type not in node_types:
                    errors.append(f"hops[{i}]: unknown node type for {species}: {node_type!r}")
            for prop in [c["property"] for c in hop.get("where") or []] + [hop.get("order_by")]:
                if prop and prop not in property_keys:
                    errors.append(f"hops[{i}]: unknown edge property for {species}: {prop!r}")
            if hop.get("where") or hop.get("order_by"):
                errors.append(f"hops[{i}]: not supported yet on MORK: 'where' and 'order_by'")
        return errors

    def _incoming_sources(self, vocabulary, node_type, labels, neighbour_types):
        """(source type, label, ACT space, stored target-first?) for edges into node_type."""
        sources = []
        for source, label, target in vocabulary["triples"]:
            if target != node_type or (labels and label not in labels) or \
                    (neighbour_types and source not in neighbour_types):
                continue
            if label in SYMMETRIC_LABELS and source == target:
                # Stored in both directions: incoming = outgoing.
                sources.append((source, label, self.space, False))
                continue
            space = self.index.reverse_space((source, label, target))
            if space is None:
                continue    # no edges of this type
            sources.append((source, label, space, True))
        return sources

    # -- one hop -----------------------------------------------------------

    def _hop_program(self, vocabulary, hop_filter, frontier, node_limit, seed, properties):
        p = MorkProgram(self.space)
        act = p.act
        direction = hop_filter.get("direction", "both")
        labels = hop_filter.get("edge_types") or []
        neighbour_types = hop_filter.get("node_types") or []
        frontier_types = sorted({node_type for node_type, _ in frontier})
        incoming = {t: self._incoming_sources(vocabulary, t, labels, neighbour_types)
                    for t in frontier_types} if direction != "out" else {}

        if seed is not None:
            seed_atom = f"({seed[0]} {seed[1]})"
            p.emit([act(seed_atom)], [f"(seed {seed_atom})"])
            for prop in self._node_props(vocabulary, seed[0], properties):
                p.emit([act(f"({prop} {seed_atom} $v)")], [f"(np {prop} {seed_atom} $v)"])
            self._seed_degree(p, vocabulary, seed)

        # Edges per frontier node, capped inside MORK at node_limit + 1: the
        # extra row only tells Python that more exist (truncated). Incoming
        # edges are read target-first from the reverse index.
        head = node_limit + 1
        for node_type, node_id in frontier:
            node = f"({node_type} {node_id})"
            if direction != "in":
                for label in labels or ["$l"]:
                    for neighbour_type in neighbour_types or ["$t"]:
                        edge = f"({label} {node} ({neighbour_type} $x))"
                        p.emit([act(edge)], sinks=[f"(head {head} (out {node} ({neighbour_type} $x) {edge}))"])
            for source, label, space, reverse in incoming.get(node_type, []):
                stored = f"({label} {node} ({source} $x))"
                edge = f"({label} ({source} $x) {node})"
                p.emit([f"(ACT {space} {stored})"], sinks=[f"(head {head} (out {node} ({source} $x) {edge}))"])

        # Properties of what is returned, by name: a variable property name
        # also matches every edge of the node and is far slower.
        returned_edges, returned_nodes = p.head(), p.head()
        p.emit(["(BTM (out $n $m $e))"], [f"({returned_edges} $e)", f"({returned_nodes} $m)"])
        triples, neighbours = set(), set()
        for source, label, target in vocabulary["triples"]:
            matches = (not labels or label in labels)
            if direction != "in" and source in frontier_types and matches and \
                    (not neighbour_types or target in neighbour_types):
                triples.add((source, label, target))
                neighbours.add(target)
            if direction != "out" and target in frontier_types and matches and \
                    (not neighbour_types or source in neighbour_types):
                triples.add((source, label, target))
                neighbours.add(source)
        if properties:
            for source, label, target in sorted(triples):
                edge = f"({label} ({source} $a) ({target} $b))"
                for prop in vocabulary["edge_properties"].get(label, []):
                    p.emit([f"(BTM ({returned_edges} {edge}))", act(f"({prop} {edge} $v)")],
                           [f"(ep {prop} {edge} $v)"])
        for neighbour_type in sorted(neighbours):
            node = f"({neighbour_type} $x)"
            for prop in self._node_props(vocabulary, neighbour_type, properties):
                p.emit([f"(BTM ({returned_nodes} {node}))", act(f"({prop} {node} $v)")], [f"(np {prop} {node} $v)"])
        return p.finish()

    def _seed_degree(self, p, vocabulary, seed):
        """Count sinks for the seed's edges by (edge type, neighbour type, direction)."""
        seed_atom = f"({seed[0]} {seed[1]})"
        p.emit([p.act(f"($l {seed_atom} ($t $x))")], sinks=["(count (deg out $l $t $c) $c ($t $x))"])
        for source, label, space, reverse in self._incoming_sources(vocabulary, seed[0], [], []):
            pattern = f"({label} {seed_atom} ({source} $x))"
            p.emit([f"(ACT {space} {pattern})"], sinks=[f"(count (deg in {label} {source} $c) $c $x)"])

    @staticmethod
    def _node_props(vocabulary, node_type, properties):
        props = vocabulary["node_properties"].get(node_type, [])
        if properties:
            return [prop for prop in props if prop not in SKIP_NODE_PROPERTIES]
        return [prop for prop in props if prop in NAME_KEYS]   # still needed for 'name'

    # -- expansion ---------------------------------------------------------

    def expand(self, request, stop_event=None, on_hop_complete=None):
        vocabulary = self.vocabulary()
        seed = request["seed"]
        properties = request.get("properties", True)
        hop_filters = request.get("hops") or [{}]
        per_node_limit = request["per_node_limit"]
        result = {
            "seed": {"type": seed["type"], "id": seed["id"], "found": False},
            "nodes": [], "edges": [], "hops": [], "seed_degree": [],
            "node_count": 0, "edge_count": 0,
            "node_count_by_label": [], "edge_count_by_label": [],
            "truncated": False,
        }
        seed_id = _symbol(seed["id"])
        if seed_id is None or seed["type"] not in vocabulary["node_types"]:
            return result
        seed_key = (seed["type"], seed_id)

        node_props = defaultdict(lambda: defaultdict(list))
        nodes, edges = {}, {}
        frontier = [seed_key]

        def make_node(key, hop):
            data = {"id": f"{key[0]} {key[1]}", "type": key[0], "hop": hop}
            props = node_props.get(key, {})
            if properties:
                data.update({name: _value(values) for name, values in props.items()
                             if name not in SKIP_NODE_PROPERTIES})
            data["name"] = next((_value(props[k]) for k in NAME_KEYS if props.get(k)), data["id"])
            return data

        for hop in range(1, request["max_hops"] + 1):
            if not frontier:
                break
            _check_cancelled(stop_event)
            hop_filter = hop_filters[min(hop - 1, len(hop_filters) - 1)]
            hop_limit = hop_filter["limit"]
            # per_node_limit spreads a hop's budget across many frontier nodes;
            # from a single node (the seed) the hop limit alone applies.
            node_limit = per_node_limit if len(frontier) > 1 else hop_limit
            program = self._hop_program(vocabulary, hop_filter, frontier, node_limit,
                                        seed_key if hop == 1 else None, properties)
            started = time.monotonic()
            atoms = self.generator.run_program(program, NEIGHBOURHOOD_HOP_TIMEOUT_S, stop_event)

            rows, edge_props, found = defaultdict(list), defaultdict(lambda: defaultdict(list)), False
            for atom in atoms:
                if atom[0] == "out":
                    rows[atom[1]].append((atom[2], atom[3]))
                elif atom[0] == "np":
                    node_props[atom[2]][atom[1]].append(atom[3])
                elif atom[0] == "ep":
                    edge_props[atom[2]][atom[1]].append(atom[3])
                elif atom[0] == "seed":
                    found = True
                elif atom[0] == "deg":
                    _, direction, label, neighbour_type, count = atom
                    result["seed_degree"].append({"edge_type": label, "neighbour_type": neighbour_type,
                                                  "direction": direction, "count": int(count)})
            if hop == 1:
                if not found:
                    return result
                result["seed"].update(found=True, node_id=f"{seed['type']} {seed['id']}")
                result["seed_degree"].sort(key=lambda row: (-row["count"], row["edge_type"],
                                                            row["neighbour_type"], row["direction"]))
                nodes[seed_key] = make_node(seed_key, 0)

            # Same order and limits as the Cypher query: frontier order, at
            # most node_limit rows per node, at most hop_limit edges per hop.
            fetched = [(node, *row) for node in frontier for row in rows.get(node, [])[:node_limit + 1]]
            fetched = fetched[:hop_limit + len(frontier) + 1]
            per_node_seen = Counter()
            new_frontier, hop_edges, truncated = [], 0, False
            for node, neighbour, edge in fetched:
                per_node_seen[node] += 1
                if per_node_seen[node] > node_limit:
                    truncated = True    # the extra row only signals "more exist"
                    continue
                if hop_edges >= hop_limit or len(nodes) >= NEIGHBOURHOOD_MAX_TOTAL_NODES:
                    truncated = True
                    break
                if neighbour not in nodes:
                    nodes[neighbour] = make_node(neighbour, hop)
                    new_frontier.append(neighbour)
                if edge in edges:
                    continue
                label, source, target = edge
                data = {"source": f"{source[0]} {source[1]}", "target": f"{target[0]} {target[1]}",
                        "label": label, "hop": hop, "edge_id": f"{source[0]}_{label}_{target[0]}"}
                if properties:
                    for name, values in edge_props.get(edge, {}).items():
                        data["source_data" if name == "source" else name] = _value(values)
                edges[edge] = data
                hop_edges += 1

            logger.info("[neighbourhood] MORK hop %s: %s frontier nodes, %s edges, %.2f s",
                        hop, len(frontier), hop_edges, time.monotonic() - started)
            summary = {"hop": hop, "node_count": len(new_frontier), "edge_count": hop_edges,
                       "truncated": truncated, "ranked_by": hop_filter.get("order_by")}
            result["hops"].append(summary)
            result["truncated"] = result["truncated"] or truncated
            if on_hop_complete is not None:
                on_hop_complete(summary)
            frontier = new_frontier

        node_list, edge_list = list(nodes.values()), list(edges.values())
        result["nodes"] = [{"data": n} for n in node_list]
        result["edges"] = [{"data": e} for e in edge_list]
        result["node_count"], result["edge_count"] = len(node_list), len(edge_list)
        result["node_count_by_label"] = [
            {"label": k, "count": v} for k, v in Counter(n["type"] for n in node_list).items()]
        result["edge_count_by_label"] = [
            {"label": k, "count": v} for k, v in Counter(e["label"] for e in edge_list).items()]
        return result

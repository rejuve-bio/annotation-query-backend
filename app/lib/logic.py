"""
Boolean logic (AND / OR / NOT) in query requests: validation and normalization.

A request may carry an optional 'logic' section next to 'nodes' and
'predicates'. It is a tree of groups; each group has an 'operator' (AND, OR or
NOT) and exactly one of:
  - 'nodes':      conditions on the properties of one node,
  - 'predicates': a list of predicate ids,
  - 'children':   nested groups.

    "logic": {
      "operator": "AND",
      "children": [
        {"operator": "OR",  "nodes": {"node_id": "n0", "properties": {"gene_name": ["FTO", "BRCA1"]}}},
        {"operator": "NOT", "nodes": {"node_id": "n0", "properties": {"gene_type": "lncRNA"}}},
        {"operator": "NOT", "predicates": ["p1"]},
        {"operator": "OR",  "predicates": ["p2", "p3"]}
      ]
    }

Meaning:
  properties  AND: all match        OR: at least one matches
              NOT: none match (a missing property counts as not matching)
  predicates  AND: all exist        OR: at least one exists
              NOT: none exist; the far node is not returned or counted

Everything here is backend-independent, so every query generator interprets a
request the same way. Validation normalizes the section in place so later
steps (canonicalization, fingerprinting, query generation) can rely on one
shape: upper-case operators, an AND root with 'children', cleaned node ids,
and every property value as a non-empty list of strings.
"""
import difflib
import re

LOGIC_OPERATORS = frozenset({"AND", "OR", "NOT"})

# A logic group holds exactly one of these keys, plus 'operator'.
GROUP_KINDS = ("nodes", "predicates", "children")
GROUP_KEYS = frozenset({"operator", *GROUP_KINDS})
NODE_TARGET_KEYS = frozenset({"node_id", "properties"})

# Size limits, so a malformed or hostile request cannot make an unbounded query.
MAX_LOGIC_DEPTH = 5
MAX_LOGIC_GROUPS = 50
MAX_VALUES_PER_PROPERTY = 100

# Genomic-position filters have interval semantics in the query generators,
# so they cannot be combined with OR/NOT yet.
POSITIONAL_PROPERTIES = frozenset(
    {"start", "end", "interval_type", "upstream_distance", "downstream_distance"}
)

# Property names are written into generated queries as identifiers (they
# cannot be query parameters), so they are restricted to plain identifiers.
_PROPERTY_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LogicValidationError(ValueError):
    """Raised when the optional 'logic' section of a request is invalid or not supported."""


class QueryTooBroadError(ValueError):
    """Raised when a request would match (almost) the whole graph."""


def clean_node_id(node_id):
    """Clean a node id the same way validate_request cleans the nodes themselves."""
    return re.sub(r"[-_]", "", node_id)


def with_chr_prefix(value):
    """Return a chromosome value in the stored format, e.g. '16' -> 'chr16'."""
    value = str(value)
    if value and not value.startswith("chr"):
        return "chr" + value
    return value


def is_safe_property_name(name):
    return isinstance(name, str) and bool(_PROPERTY_NAME_RE.match(name))


def require_safe_property_name(name, where):
    """Raise unless a property name is a plain identifier (letters, digits, '_')."""
    if not is_safe_property_name(name):
        raise ValueError(f"invalid property name {name!r} in {where}: use letters, digits and '_' only")


# ---------------------------------------------------------------------------
# Validation and normalization
# ---------------------------------------------------------------------------

def normalize_logic(logic, node_map, predicate_map):
    """Validate the 'logic' section and return its normalized form.

    A single group at the root is accepted and wrapped in an AND root.

    Args:
        logic: The value of request['logic'].
        node_map: node_id -> node, as built by validate_request.
        predicate_map: predicate_id -> predicate, after ids were assigned.

    Raises:
        LogicValidationError: If the section is malformed, too large, refers to
            unknown nodes or predicates, or uses a feature not supported yet.
    """
    if not isinstance(logic, dict):
        raise LogicValidationError("'logic' must be an object")

    if any(kind in logic for kind in ("nodes", "predicates")):
        logic = {"operator": "AND", "children": [logic]}

    _reject_unknown_keys(logic, {"operator", "children"}, "'logic'")
    logic["operator"] = _normalize_operator(logic.get("operator", "AND"))
    is_and_root = logic["operator"] == "AND"

    group_count = [0]
    for child in _require_children(logic):
        # Only children of an AND root may mix nodes and predicates.
        _validate_group(child, node_map, predicate_map, depth=1, at_and_root=is_and_root, group_count=group_count)

    _require_predicates_in_one_group(logic["children"])
    if not is_and_root:
        _require_single_node(logic)
    return logic


def _validate_group(group, node_map, predicate_map, depth, at_and_root, group_count):
    """Validate one logic group and, recursively, everything under it."""
    if depth > MAX_LOGIC_DEPTH:
        raise LogicValidationError(f"'logic' is nested too deeply: the maximum depth is {MAX_LOGIC_DEPTH}")
    group_count[0] += 1
    if group_count[0] > MAX_LOGIC_GROUPS:
        raise LogicValidationError(f"'logic' has too many groups: the maximum is {MAX_LOGIC_GROUPS}")
    if not isinstance(group, dict):
        raise LogicValidationError("each logic group must be an object")

    _reject_unknown_keys(group, GROUP_KEYS, "a logic group")
    group["operator"] = _normalize_operator(group.get("operator"))

    kinds = [kind for kind in GROUP_KINDS if kind in group]
    if len(kinds) != 1:
        raise LogicValidationError("each logic group needs exactly one of 'nodes', 'predicates', 'children'")

    if kinds[0] == "nodes":
        _validate_property_group(group, node_map)
    elif kinds[0] == "predicates":
        if not at_and_root:
            raise LogicValidationError(
                "not supported yet: predicate groups must sit directly under a root with operator AND"
            )
        _validate_predicate_group(group, predicate_map)
    else:
        for child in _require_children(group):
            _validate_group(child, node_map, predicate_map, depth + 1, at_and_root=False, group_count=group_count)
        _require_single_node(group)


def _validate_property_group(group, node_map):
    """Validate a group of conditions on one node's properties."""
    target = group["nodes"]
    if not isinstance(target, dict):
        raise LogicValidationError("'nodes' in a logic group must be an object with 'node_id' and 'properties'")
    _reject_unknown_keys(target, NODE_TARGET_KEYS, "'nodes' of a logic group")

    node_id = target.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        raise LogicValidationError("each property group needs a 'node_id'")
    node_id = clean_node_id(node_id)
    target["node_id"] = node_id
    if node_id not in node_map:
        raise LogicValidationError(f"logic refers to unknown node '{node_id}'")

    properties = target.get("properties")
    if not properties:
        if group["operator"] == "NOT":
            raise LogicValidationError(
                f"NOT on the whole node '{node_id}' is not allowed: it would match almost the whole graph; "
                "list the properties to exclude instead"
            )
        raise LogicValidationError(f"logic group on node '{node_id}' has no properties")
    if not isinstance(properties, dict):
        raise LogicValidationError(f"'properties' of the logic group on node '{node_id}' must be an object")

    own_properties = node_map[node_id].get("properties", {})
    for name, value in properties.items():
        try:
            require_safe_property_name(name, f"the logic group on node '{node_id}'")
        except ValueError as e:
            raise LogicValidationError(str(e)) from None
        if name in POSITIONAL_PROPERTIES:
            raise LogicValidationError(f"not supported yet: position filter '{name}' inside 'logic'")
        if name in own_properties:
            raise LogicValidationError(
                f"property '{name}' of node '{node_id}' is in both 'properties' and 'logic'; keep it in one place"
            )
        properties[name] = normalize_values(name, value)


def _validate_predicate_group(group, predicate_map):
    """Validate a group of predicate ids."""
    predicate_ids = group["predicates"]
    if not isinstance(predicate_ids, list) or not predicate_ids:
        raise LogicValidationError("'predicates' in a logic group must be a non-empty list of predicate ids")

    for predicate_id in predicate_ids:
        if not isinstance(predicate_id, str) or predicate_id not in predicate_map:
            raise LogicValidationError(f"logic refers to unknown predicate '{predicate_id}'")

    all_predicates = list(predicate_map.values())
    if group["operator"] == "NOT":
        for predicate_id in predicate_ids:
            negated_predicate_ends(predicate_map[predicate_id], all_predicates)
    if group["operator"] == "OR" and len(predicate_ids) > 1:
        or_predicate_ends(predicate_ids, all_predicates)


def normalize_values(name, value):
    """Turn a property value into a non-empty list of non-empty strings."""
    values = value if isinstance(value, list) else [value]
    if not values:
        raise LogicValidationError(f"property '{name}' in 'logic' must not be an empty list")
    if len(values) > MAX_VALUES_PER_PROPERTY:
        raise LogicValidationError(
            f"property '{name}' in 'logic' has too many values: the maximum is {MAX_VALUES_PER_PROPERTY}"
        )

    normalized = []
    for item in values:
        # bool is a subclass of int, so exclude it explicitly.
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise LogicValidationError(f"property '{name}' in 'logic' must be a string or a list of strings")
        text = str(item).strip()
        if not text:
            raise LogicValidationError(f"property '{name}' in 'logic' must not be empty")
        normalized.append(with_chr_prefix(text) if name == "chr" else text)
    return normalized


def _reject_unknown_keys(obj, allowed, where):
    unknown = sorted(set(obj) - set(allowed))
    if not unknown:
        return
    key = unknown[0]
    hint = difflib.get_close_matches(str(key), sorted(allowed), n=1)
    suggestion = f"; did you mean '{hint[0]}'?" if hint else f"; allowed keys: {', '.join(sorted(allowed))}"
    raise LogicValidationError(f"unknown key '{key}' in {where}{suggestion}")


def _normalize_operator(operator):
    """Return the operator in upper case, or raise if it is not AND, OR or NOT."""
    if not isinstance(operator, str) or operator.upper() not in LOGIC_OPERATORS:
        raise LogicValidationError(f"invalid operator {operator!r}; expected AND, OR or NOT")
    return operator.upper()


def _require_children(group):
    """Return a group's 'children', or raise if it is not a non-empty list."""
    children = group.get("children")
    if not isinstance(children, list) or not children:
        raise LogicValidationError("'children' must be a non-empty list")
    return children


def _require_predicates_in_one_group(groups):
    """Raise if a predicate id appears in more than one predicate group."""
    seen = set()
    for group in groups:
        for predicate_id in group.get("predicates", []):
            if predicate_id in seen:
                raise LogicValidationError(f"predicate '{predicate_id}' is used in more than one predicate group")
            seen.add(predicate_id)


def _require_single_node(group):
    """Raise unless every condition under the group is on the same node."""
    node_ids = _collect_node_ids(group)
    if len(node_ids) != 1:
        raise LogicValidationError(
            f"not supported yet: a combined group must refer to exactly one node, got {sorted(node_ids)}"
        )


def _collect_node_ids(group):
    """Return the node ids of all property groups under a group."""
    if "nodes" in group:
        return {group["nodes"]["node_id"]}
    node_ids = set()
    for child in group.get("children", []):
        node_ids |= _collect_node_ids(child)
    return node_ids


# ---------------------------------------------------------------------------
# Shared rules for NOT / OR on predicates (used by every backend)
# ---------------------------------------------------------------------------

def negated_predicate_ends(predicate, predicates):
    """Return (kept_node_id, far_node_id) for a predicate under NOT.

    "NOT p" returns the kept node only when no edge like p connects it to a
    node like the far node. The far node is never returned; it only describes
    the edge that must not exist:
      - the far node is the end that no other predicate uses;
      - if neither end is used elsewhere ("genes with no pathway"), the
        edge's source is kept;
      - if both ends are used elsewhere, it is not supported yet.
    """
    predicate_id = predicate["predicate_id"]
    source, target = predicate["source"], predicate["target"]
    if source == target:
        raise LogicValidationError(
            f"not supported yet: NOT on predicate '{predicate_id}', which starts and ends at the same node"
        )

    used_elsewhere = {
        node_id
        for other in predicates
        if other["predicate_id"] != predicate_id
        for node_id in (other["source"], other["target"])
    }
    if source in used_elsewhere and target in used_elsewhere:
        raise LogicValidationError(
            f"not supported yet: NOT on predicate '{predicate_id}', whose two nodes are both used by other predicates"
        )
    if target in used_elsewhere:
        return target, source
    return source, target


def or_predicate_ends(predicate_ids, predicates):
    """Return (kept_node_id, {predicate_id: far_node_id}) for an OR group of predicates.

    The predicates must share exactly one node, which is kept; each one's other
    end is its far node, and no other predicate may use it, so each
    alternative stands alone.
    """
    by_id = {predicate["predicate_id"]: predicate for predicate in predicates}
    group = [by_id[predicate_id] for predicate_id in predicate_ids]

    for predicate in group:
        if predicate["source"] == predicate["target"]:
            raise LogicValidationError(
                f"not supported yet: OR on predicate '{predicate['predicate_id']}', "
                "which starts and ends at the same node"
            )

    shared = set.intersection(*({predicate["source"], predicate["target"]} for predicate in group))
    if not shared:
        raise LogicValidationError(f"not supported yet: OR between predicates {predicate_ids} that share no node")
    if len(shared) > 1:
        raise LogicValidationError(f"not supported yet: OR between predicates {predicate_ids} that share both nodes")
    kept_id = shared.pop()

    far_ids = {}
    for predicate in group:
        predicate_id = predicate["predicate_id"]
        far_id = predicate["target"] if predicate["source"] == kept_id else predicate["source"]
        if any(far_id in (other["source"], other["target"])
               for other in predicates if other["predicate_id"] != predicate_id):
            raise LogicValidationError(
                f"not supported yet: OR on predicate '{predicate_id}', whose node '{far_id}' "
                "is also used by other predicates"
            )
        far_ids[predicate_id] = far_id
    return kept_id, far_ids


def counted_nodes_and_predicates(request):
    """Return (nodes, predicates) of a validated request that can appear in its results.

    Predicates under NOT and their far nodes only describe edges that must not
    exist, so they are left out of label counts.
    """
    nodes = request.get("nodes", [])
    predicates = request.get("predicates", [])
    negated_ids = negated_predicate_ids(request)
    if not negated_ids:
        return nodes, predicates
    far_ids = {
        negated_predicate_ends(predicate, predicates)[1]
        for predicate in predicates
        if predicate["predicate_id"] in negated_ids
    }
    return (
        [node for node in nodes if node["node_id"] not in far_ids],
        [predicate for predicate in predicates if predicate["predicate_id"] not in negated_ids],
    )


def negated_predicate_ids(request):
    logic = request.get("logic")
    if not logic or logic.get("operator") != "AND":
        return set()
    return {
        predicate_id
        for group in logic.get("children", [])
        if "predicates" in group and group.get("operator") == "NOT"
        for predicate_id in group["predicates"]
    }


# ---------------------------------------------------------------------------
# "Too broad" rule
# ---------------------------------------------------------------------------

def ensure_has_positive_filter(request):
    """Raise QueryTooBroadError unless some node is narrowed by a positive filter.

    A positive filter is a node id, a node property, or a logic condition that
    narrows the results. Predicates alone do not narrow ("all genes linked to
    any pathway"), and neither does anything under NOT ("everything except X"
    is close to everything), so a request made only of those would scan most
    of the graph.
    """
    for node in request.get("nodes", []):
        if node.get("id") or node.get("ids"):
            return
        if any(value not in (None, "", []) for value in (node.get("properties") or {}).values()):
            return
    logic = request.get("logic")
    if logic and _narrows(logic):
        return
    raise QueryTooBroadError(
        "this query is too broad: it would match almost the whole graph. "
        "Add a positive filter, such as an id or a property value (for example a gene name or type)."
    )


def _narrows(group):
    """Whether a logic group is guaranteed to narrow its node's results."""
    operator = group.get("operator", "AND")
    if operator == "NOT" or "predicates" in group:
        return False
    if "nodes" in group:
        return True
    children = group.get("children", [])
    if operator == "AND":
        return any(_narrows(child) for child in children)
    return bool(children) and all(_narrows(child) for child in children)

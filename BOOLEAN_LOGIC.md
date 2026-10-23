# Boolean logic (AND / OR / NOT) in query requests

Requests to `POST /query` can carry an optional `logic` section next to `nodes`
and `predicates`. Without it, every property filter and every predicate must
match (AND), exactly as before. With it you can express OR and NOT, on node
properties and on predicates (edges).

Supported on the **Cypher (Neo4j) backend**. On MeTTa and MORK a request with
`logic` is refused with a 400.

## Format

```json
{
  "requests": {
    "species": "human",
    "nodes": [
      {"node_id": "n0", "id": "", "type": "gene", "properties": {}},
      {"node_id": "n1", "id": "", "type": "biological_process", "properties": {}}
    ],
    "predicates": [
      {"predicate_id": "p0", "type": "involved in", "source": "n0", "target": "n1"}
    ],
    "logic": {
      "operator": "AND",
      "children": [
        {"operator": "OR",  "nodes": {"node_id": "n0", "properties": {"gene_type": ["lncRNA", "misc_RNA"]}}},
        {"operator": "NOT", "predicates": ["p0"]}
      ]
    }
  }
}
```
→ *lncRNA or misc_RNA genes that are not involved in any biological process.*

`logic` is a tree of **groups**. Each group has an `operator` (`AND`, `OR`,
`NOT`, any case) and exactly one of:

| Key | Meaning |
|---|---|
| `nodes` | conditions on the properties of **one** node: `{"node_id": ..., "properties": {...}}` |
| `predicates` | a list of predicate ids |
| `children` | nested groups |

- The top level is usually `{"operator": "AND", "children": [...]}`. A single
  group on its own is also accepted and treated as that one child.
- A property value can be a single value or a list. A list means **any of
  these values** (JSON cannot repeat a key).
- Predicates referred to from `logic` need unique `predicate_id`s.
- A property used in `logic` must not also appear in the node's own `properties`.

## Meaning

| | Properties | Predicates |
|---|---|---|
| **AND** | all properties match | all predicates exist |
| **OR** | at least one property matches | at least one predicate exists; results include whichever exist |
| **NOT** | none of the properties match — **a missing property counts as not matching** | none exist; the node at the far end is not returned or counted |

Inside one `nodes` group, each property matches if it equals any of its
values; the group's operator then combines the properties. Matching is
case-insensitive and exact, like normal property filters.

**Which node is kept** for predicate groups:
- `NOT p`: the end of `p` that other predicates use is kept; the other end
  only describes the edge that must not exist. If neither end is used
  elsewhere ("genes with no pathway"), the source is kept.
- `OR [p, q]`: the predicates must share exactly one node, which is kept.

## Examples

**OR across properties** — genes named N, or of type rRNA:
```json
"logic": {"operator": "OR", "nodes": {"node_id": "n0", "properties": {"gene_name": "N", "gene_type": "rRNA"}}}
```

**Same property, several values** — TP53 or BRCA1:
```json
"logic": {"operator": "OR", "nodes": {"node_id": "n0", "properties": {"gene_name": ["TP53", "BRCA1"]}}}
```

**NOT on a property, plus a normal filter** — genes on chr21 that are not lncRNA
(the node has `"properties": {"chr": "chr21"}`):
```json
"logic": {"operator": "NOT", "nodes": {"node_id": "n0", "properties": {"gene_type": "lncRNA"}}}
```

**OR between predicates** — rRNA genes involved in a biological process OR
enabling a molecular function (predicates `p0`, `p1` share the gene):
```json
"logic": {"operator": "AND", "children": [{"operator": "OR", "predicates": ["p0", "p1"]}]}
```

**Nested** — (named N and on chrX) or of type rRNA:
```json
"logic": {"operator": "OR", "children": [
  {"operator": "AND", "nodes": {"node_id": "n0", "properties": {"gene_name": "N", "chr": "X"}}},
  {"operator": "AND", "nodes": {"node_id": "n0", "properties": {"gene_type": "rRNA"}}}
]}
```

## Limits

| Limit | Value |
|---|---|
| Nesting depth | 5 |
| Groups | 50 |
| Values per property | 100 |
| Property names | letters, digits and `_` only |

## Refused requests (400)

**Too broad.** Every request (with or without `logic`) needs at least one
**positive filter**: a node `id`, a property value, or a `logic` condition
that narrows the results. Predicates alone do not count ("all genes linked to
any pathway"), and neither does anything under NOT ("everything except X").
NOT on a whole node is always refused. (Server setting:
`REQUIRE_POSITIVE_FILTER`.)

**Estimated too large.** Before running, the server asks Neo4j for an
estimate of the rows the query will produce. Above
`QUERY_COST_HARD_LIMIT` (default 30M) the request is refused; above
`QUERY_COST_SOFT_LIMIT` (default 5M) it runs on the slow queue. Requests
anchored by a single node id skip this check.

**Not supported yet:**
- position filters (`start`, `end`, `interval_type`, …) inside `logic`
- OR between a node condition and a predicate
- one combined group across two nodes
- predicate groups anywhere other than directly under an AND root
- OR between predicates that don't share exactly one node, or whose far
  node is used by another predicate; OR groups kept on different nodes
- NOT on a predicate whose two ends are both used by other predicates
- OR between predicates together with comma-separated values
- comma-separated values on the far node of a NOT predicate

## Error messages

| Situation | Message (start) |
|---|---|
| typo in a key | `unknown key 'operater' in a logic group; did you mean 'operator'?` |
| bad operator | `invalid operator 'XOR'; expected AND, OR or NOT` |
| unknown node / predicate | `logic refers to unknown node 'n9'` / `… unknown predicate 'p9'` |
| unsafe property name | `invalid property name '…' …: use letters, digits and '_' only` |
| NOT on a whole node | `NOT on the whole node 'n0' is not allowed: it would match almost the whole graph …` |
| property in both places | `property 'gene_type' of node 'n0' is in both 'properties' and 'logic' …` |
| over a limit | `'logic' is nested too deeply …` / `… too many groups …` / `… too many values …` |
| no positive filter | `this query is too broad: it would match almost the whole graph …` |
| estimate over the hard limit | `This query is too broad (about N rows estimated) …` |
| backend without logic | `boolean logic ('logic') is only supported on the Cypher backend for now` |
| not supported yet | `not supported yet: …` |

## Results, counts and caching

- Results use the normal response format. For NOT on a predicate, the far
  node type is not returned and does not appear in `node_count_by_label`.
- Titles and summaries describe the logic in plain English
  (e.g. *"…, where Gene has no 'involved in' link to a Biological Process"*).
- Equivalent requests (different order, case or single value vs. list) share
  a cache entry; requests without `logic` keep their existing cache keys.

## For backend developers

- Validation and normalization: `app/lib/logic.py` (backend-independent,
  including which end of a NOT / OR predicate is kept).
- Cypher generation: `CypherQueryGenerator._apply_logic` and friends in
  `app/services/cypher_generator.py`.
- A backend opts in with `supports_logic = True`.
- Tests: `tests/unit/test_logic.py`, `test_cypher_logic.py`,
  `test_query_canonical.py`, `test_query_cost.py`; live checks against Neo4j
  in `tests/integration/cypher/test_logic_live.py` (`LOGIC_LIVE_TESTS=1`).

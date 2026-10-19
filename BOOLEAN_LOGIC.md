# Boolean logic (AND / OR / NOT) in query requests

Requests to `POST /query` can carry an optional `logic` section next to `nodes`
and `predicates`. Without it, every property filter and every predicate must
match (AND), exactly as before. With it you can express OR and NOT, on node
properties and on predicates (edges).

Supported on **Cypher (Neo4j)** and **MORK CLI**. MeTTa and the separate MORK
HTTP backend refuse requests with `logic` with a 400.

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
values; the group's operator then combines the properties. Cypher matching is
case-insensitive and exact. MORK CLI matching is exact and case-sensitive.

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

**Estimated too large (Cypher only).** Before running, the server asks Neo4j for an
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
| backend without logic | `boolean logic ('logic') is only supported on the Cypher and MORK CLI backends` |
| not supported yet | `not supported yet: …` |

## Results, counts and caching

- Results use the normal response format. For NOT on a predicate, the far
  node type is not returned and does not appear in `node_count_by_label`.
- Titles and summaries describe the logic in plain English
  (e.g. *"…, where Gene has no 'involved in' link to a Biological Process"*).
- Equivalent requests (different order, operator casing or single value vs.
  list) share a cache entry. Property-value casing is preserved. Requests
  without `logic` keep their existing cache keys.

## MORK CLI

Select `type: mork_cli` in `config/config.yaml` and configure each available
species' `data_dir` and `act_file`. The live checks use the human v6 ACT;
there is no fly ACT in the current test environment.

MORK CLI supports nested property AND/OR/NOT and predicate AND/OR/NOT using
the same validation and kept-end rules as Cypher. NOT means **none match**;
nodes without the tested property are retained. Far-node conditions stay
inside a negated predicate's existence check, and that far node is excluded
from results and counts.

- Matching is case-sensitive: `TP53` matches, while `tp53` does not.
- Property values follow the BioCypher MeTTa writer: spaces become `_`,
  punctuation is normalized, CURIE prefixes are removed from property values,
  and stored symbols are limited to 63 UTF-8 bytes. URLs preserve their
  punctuation but must be valid single symbols. Identifiers use the existing
  ID preprocessing instead of property-value normalization.
- Multiple required predicates return complete matches. OR returns the arms
  that exist, while also requiring every ordinary predicate and every other
  OR group to match.
- One program fetches the graph, declared result properties and distinct
  total/per-label counts. The count tasks reuse those counts. Repeated roles
  referring to the same stored node or edge are counted once. Neo4j may
  count duplicate relationships separately.
- Missing display properties do not remove matching nodes. Property fetch
  skips `synonym`, `synonyms` and `accessions`; these can still be used as
  filters. Properties defined only on a schema parent are not yet fetched.
- Helper sets are removed before output. Empty results return zero totals
  and empty per-label lists.

The shared positive-filter rule applies to MORK CLI. Cypher's Neo4j cost
estimate does not run for this backend. MORK currently has no replacement
for the former raw-atom result cap, so a positive filter does not guarantee
a small result.

Additional MORK CLI restrictions return HTTP 400: cycles, parallel predicates,
disconnected request graphs, position/interval filters anywhere, edge-property
filters, comma-separated values, ordinary node-property lists, and ID lists.
Use value lists inside `logic` instead.

There is no default limit. An explicit `?limit=N` behaves like Cypher's one
row per anchor node: the graph keeps N matching root nodes with all of their
complete matches, including OR arms. Counts still describe every match.
`limit=0` means no limit; a negative limit returns HTTP 400.

The Docker build pins MORK to `ed57c6716d8c510296fb5fbb8be6fbfe2df241d7`
and its local PathMap dependency to
`ef0259152867ece8e85888acc49c238f264a0330`.

### Native live checks

The live suite runs the app's compiler, parser and count-reuse path against
the native binary. It skips unless `MORK_LIVE_TESTS=1`; it needs neither
Docker nor MongoDB/Redis. Run from the repository root:

```bash
MORK_LIVE_TESTS=1 \
MORK_TEST_BINARY="$PWD/dev-tools/mork/src/MORK/target/release/mork" \
MORK_TEST_DATA_DIR=/mnt/hdd_1/biocypher-kg/output/hsa/metta_out_v6 \
MORK_TEST_ACT_FILE=human_v6.act \
MORK_TEST_LOCK_FILE="$PWD/dev-tools/mork/.mork.lock" \
python -m pytest tests/integration/mork_cli -m mork_live --confcutdir=tests/integration/mork_cli -q
```

The lock serializes native executions; use the same lock file as other native
runners and run without parallel test workers. `MORK_TEST_TIMEOUT` defaults
to 300 seconds. `MORK_TEST_SOURCE_DIR` defaults to the ACT's data directory;
source comparisons skip if its `.metta` files are absent. The fixed matrix
counts describe the human v6 data build, so another snapshot can differ.

Checks cover the S01–S17 scenarios, exact gene sets from source files,
complete gene/transcript/protein joins, 100-value tables, explicit limits, response properties,
count agreement and helper cleanup. Shared graph grouping is a separate
layer and is not exercised by this native backend suite.

## For backend developers

- Validation and normalization: `app/lib/logic.py` (backend-independent,
  including which end of a NOT / OR predicate is kept).
- Cypher generation: `CypherQueryGenerator._apply_logic` and friends in
  `app/services/cypher_generator.py`.
- MORK compilation: `MorkJoinCompiler` in `app/services/mork_program.py` and
  `MorkPropertyCompiler` in `app/services/mork_logic.py`.
- A backend opts in with `supports_logic = True`.
- Tests: `tests/unit/test_logic.py`, `test_cypher_logic.py`,
  `test_query_canonical.py`, `test_query_cost.py`; live checks against Neo4j
  in `tests/integration/cypher/test_logic_live.py` (`LOGIC_LIVE_TESTS=1`).
- MORK unit checks: `test_mork_cli_values.py`, `test_mork_program.py`,
  `test_mork_logic.py`, `test_mork_output.py`, `test_mork_counts.py` and
  `test_mork_session.py`; native live checks in `tests/integration/mork_cli`.

# Code Explorer — LatticeDB Migration & Hybrid Impact Analysis Architecture

> Standalone design spec, preserved for later implementation. Not yet built.
> First concrete milestone: **Phase 0 — freeze the canonical `NodeRecord`/`EdgeRecord`
> model and define the backend interface.**

## 1. Purpose

This document defines the target architecture for migrating the `code-explorer`
storage and query layer from [Kùzu](https://kuzudb.com/) to
[LatticeDB](https://github.com/jeffhajewski/latticedb) — an embedded single-file
knowledge graph database with native graph traversal, BM25 full-text search, HNSW
vector search, fuzzy text search, and durable changefeeds in one engine.

The migration must preserve the existing core value of Code Explorer:

- structural code understanding
- dependency analysis
- call resolution
- incremental indexing
- impact analysis
- bounded-memory operation

The migration should additionally enable:

- BM25 lexical search
- fuzzy code search
- vector semantic search
- hybrid retrieval
- graph-aware semantic retrieval
- confidence-aware impact propagation
- optional runtime and configuration dependency integration

The goal is **not** to turn Code Explorer into a generic RAG system.

> Build a code intelligence engine where exact program relationships remain the
> source of truth, while lexical and semantic search help discover the correct
> graph entry points.

---

## 1a. Implementation Status

> Living status tracker for this spec — updated as work lands. Last updated after
> search/context assembly/vector search shipped, the search_text redesign, and the
> ingest-performance work (node_id_map) — see Section 1b below for performance data.

### Phase-by-phase status

| Phase | Status | Evidence |
|---|---|---|
| **0 — Canonical model + backend interface** | ✅ Done | `graph/records.py` (`NodeRecord`/`EdgeRecord`), `graph/backend.py` (`CodeGraphBackend` Protocol), `graph/backends/{kuzu,lattice}_backend.py` |
| **1 — Read-only Lattice prototype** | ✅ Done | `graph/queries.py` routes through `backend.query()`; `get_callers`/`get_callees`/`ImpactAnalyzer` verified identical on both backends |
| **2 — Initial ingestion** | ⚠️ Partial | `graph/ingest.py`'s `file_analyses_to_records()` covers only File/Function/Class nodes + CONTAINS_FUNCTION/CONTAINS_CLASS/CALLS edges. No Variable/Import/Decorator/Attribute/Exception/Module yet — deliberately deprioritized, see ranking below. |
| **3 — Incremental updates** | ✅ Done | `DependencyGraph.ingest_incremental()` in `src/code_explorer/graph/graph.py` — hashes every current file, skips unchanged ones, and for changed/new files calls `delete_file()` then re-ingests just that file; deleted-from-disk files are also removed via `delete_file()`. Wired into `code-explorer search` (`src/code_explorer/cli.py`): an existing index is updated incrementally by default, `--reindex` forces a full rebuild. Known limitation: an *unchanged* file's CALLS edges into a function that moved/renamed/was-deleted in a changed file are not re-examined until that caller file is itself reprocessed. Tests: `tests/test_incremental_ingestion.py`. Benchmark: `perfo/benchmark_incremental_ingest.py` (speed + accuracy vs. full rebuild — see Section 1b). |
| **4 — BM25** | ✅ Done | `code-explorer search "query" PATH` — BM25 (default) + `--fuzzy`, over a compact derived `search_text` (see `source-of-truth-and-search-representations.md`), plus an exact-match shortcut for `file.py:function` queries. Tutorial: `docs/tutorials/search-and-context.md`. |
| **Minimal LLM context assembly** | ✅ Done | `src/code_explorer/context.py`'s `ContextAssembler` — seed + one-hop callers/callees with source (read live from disk via `SourceProvider`, not stored), wired into `search`'s default output. |
| **5 — Vector search** | ✅ Done | `code-explorer search "query" PATH --semantic`, backed by local Ollama (`nomic-embed-text`) — see `src/code_explorer/embeddings.py`. Verified genuine semantic ranking (zero keyword overlap) on real code, not just synthetic vectors. `--semantic` also re-embeds incrementally (only changed nodes, via `build_vector_index(node_ids=...)`), and embedding calls are batched (`embed_texts`, `_EMBED_BATCH_SIZE = 50`) rather than one Ollama HTTP call per node — measured ~7x faster per item (37ms→~5.2ms), see `perfo/benchmark_embed_batching.py`. |
| **6 — Hybrid retrieval** | ✅ Done | `code-explorer search "query" PATH` (plain, no `--fuzzy`/`--semantic`) fuses BM25 + vector search via Reciprocal Rank Fusion (`src/code_explorer/hybrid_search.py`) whenever a vector index already exists on disk for that repo (i.e. `--semantic` has been run there at least once) — never builds the vector index itself, so a repo that's never used `--semantic` pays no embedding cost. `--fuzzy`/`--semantic` still mean "exactly this mode," no fusion. Plus the "try exact match, fall back to BM25" heuristic. No query classifier beyond that — not needed once fusion handles the ambiguous case directly. |
| **7 — Confidence-aware impact** | ❌ Not implemented | No `confidence`/`resolution_method`/`evidence` fields on any edge. `ImpactAnalyzer` treats every edge as certain. |

### Ranking of unimplemented phases, by impact on LLM-search-context quality

> Historical record of the prioritization decision, kept for the reasoning trail.
> Ranks 1-4 (BM25, context assembly, fuzzy, vector search) are now ✅ Done per the
> table above; only 5-7 remain open.

Ranked for a specific goal — "search in code for an LLM, to give a real nice context" —
not for completeness or Kuzu feature parity (full node/edge type coverage is explicitly
deprioritized for this ranking).

1. **BM25 lexical search (Phase 4) — highest impact, lowest effort.** This is the
   actual unlock for *search* existing at all. Today code-explorer can only answer
   "what calls X" if you already know X's exact file+name — there's no way to go from
   a natural-language-ish query ("token refresh", "plugin loader") to a seed node. BM25
   is the cheapest way to close that gap: the engine capability is already proven,
   `Function`/`Class` nodes already carry `source_code`, so this is "create an FTS
   index on ingest + one method that calls `fts_search`" — no new node types, no
   embedding model decision, no new dependency.

2. **Minimal LLM context assembly (Section 18) — highest impact, paired with #1.**
   BM25 alone returns a ranked list of hits, not "a real nice context." Section 18's
   shape (seed → direct impact → transitive → bounded budget → retrieve source only
   for selected nodes) is what turns a search hit into something an LLM can actually
   use well. Doesn't need the full budget/pruning machinery — a minimal version (seed
   from BM25 → one-hop `get_callers`/`get_callees` → cap at N nodes → attach
   `source_code`) is already a large jump over raw search hits or raw impact lists.
   Ranked essentially tied with #1: BM25 without this is half the value, this without
   BM25 has no way to find a seed from a natural-language query.

3. **Fuzzy search (Phase 4 / Section 11 "Strategy C") — high impact, near-zero
   marginal effort.** Once the BM25 FTS index exists, `fts_search_fuzzy` is the same
   index, same API, different call. Useful for slightly-off/misremembered identifiers.
   Ranked just below BM25 since it's a fallback on top of #1, not a capability on its
   own.

4. **Vector search (Phase 5) — high potential impact, meaningfully higher effort.**
   Handles genuinely conceptual queries ("where do we validate access before loading a
   plugin") with no keyword overlap — what BM25 structurally cannot cover. Real cost
   though: requires an embedding model decision, a new dependency, an
   embedding-generation step in ingest, and `vector_dimensions` is fixed at
   database-creation time, so it's a real design decision, not a small add-on. Ranked
   below BM25/fuzzy because keyword search alone already covers a large fraction of
   realistic "where is X" queries, which tend to share vocabulary with the code.

5. **Hybrid retrieval / query classifier (Phase 6, Section 12) — moderate impact,
   mostly formalization.** Merging exact+BM25+fuzzy+vector with scoring/reranking is
   real value once *multiple* modes exist, but with only BM25/fuzzy in place, a full
   classifier is over-engineering — "try exact match, fall back to BM25" is a
   two-line heuristic. Becomes much higher-value once vector search (rank 4) exists.

6. **Confidence-aware impact (Phase 7) — moderate impact, orthogonal to search.**
   Improves result *trustworthiness* once a seed is already found and impact already
   traversed — useful for an LLM to know "high confidence direct caller" vs "possible
   dynamic reference," but doesn't help *finding* things. No dependency on 1-5, so
   implementable independently whenever prioritized.

7. **Incremental updates (Phase 3) — lower impact on context quality, real
   operational cost.** Doesn't change what an LLM sees in a single query — it's about
   re-index cost over time. Important for adoption on a real, changing codebase, but
   last for this specific "search context quality" lens.

## 1b. Performance Findings: Kuzu vs LatticeDB

> Real measurements, not vendor benchmarks. Every number below was produced on this
> machine, on either this repo's own `src/code_explorer` (small: ~450-480 nodes) or
> [gemseo](https://gitlab.com/gemseo/dev/gemseo) (large, real, external:
> 2,107 files, 15,421 nodes, 338,128 resolved calls) — see `perfo/benchmark_backends.py`
> and `perfo/benchmark_ingest_speed.py` to reproduce. Where a claim from LatticeDB's own
> docs/marketing contradicted what we measured, we kept our own number and said so —
> see the note at the end of this section.

**The strategy in one sentence**: LatticeDB is the right choice for storage +
search (it's the only one of the two that has BM25/vector search at all), but its
Cypher query engine is meaningfully slower than Kuzu's per-query — so anything that
does many small queries in a loop (like `ImpactAnalyzer`'s BFS) pays for that
repeatedly, while anything that's naturally one bulk operation doesn't.

### Ingestion (writing data in)

| Workload | Kuzu | LatticeDB (before this session's fixes) | LatticeDB (after) |
|---|---|---|---|
| This repo (small) | fast (Parquet/COPY-FROM path, not measured head-to-head here) | 0.44s (generic path) | 0.32s |
| gemseo (338K edges) | not measured at this scale | 62.78s | **34.77s (1.81x)** |

LatticeDB's generic node/edge write path (the only one available — there is no
bulk-insert-with-properties primitive, confirmed from the library's own README,
only a vector-only `batch_insert_vectors(label, vectors)` that can't hold arbitrary
properties) starts out slow because every edge resolves its endpoints via a DB
lookup. The fix that actually mattered: build a `{canonical_id: internal_id}` map
once while writing nodes, and have edge creation use that map from memory instead
of a lookup per endpoint (`graph/backends/lattice_backend.py`'s `upsert_nodes`
return value / `upsert_edges`' `node_id_map` parameter). A separate optimization
(`assume_new`, skipping the *node* existence-check) gave only ~1.01x at this same
scale — it targeted the wrong side of the problem: edges outnumber nodes ~22:1 on
a real codebase, so node-side savings barely register against edge-side cost.

### Query latency (reading data back)

From `perfo/benchmark_backends.py`, on this repo's own small dataset:

| Metric | Kuzu | LatticeDB |
|---|---|---|
| Single-hop query (`get_callers`) | 0.52ms | 74ms (**~140x slower**) |
| Impact traversal, depth 8 | 17ms | 2,287ms (**~130x slower**) |
| Accuracy (same seed, same traversal) | — | matches Kuzu exactly |

This gap is *not* explained by a missing index — confirmed empirically that adding
a LatticeDB property index has zero effect on Cypher `MATCH` query latency (25.36ms
vs 25.42ms with/without); the index only helps the separate
`find_nodes_by_label_property` API, not Cypher `MATCH`.

**Update — this turned out to be fixable, and the fix landed**: at gemseo's real
scale (338,128 edges), a single Cypher `MATCH (caller:Function)-[c:CALLS]->
(callee:Function {id: $id})` measured **15.3 seconds** to find one node's 27
callers. Reading LatticeDB's own architecture docs (`book/src/architecture/
query-execution.md`, fetched via context7) explains why: `MATCH (a)-[:TYPE]->(b)`
compiles to `Expand ← LabelScan(label)` — the planner scans *every* node with the
given label before expanding edges, rather than seeking directly to the
`{id: $id}`-filtered target. Their storage docs separately confirm edges are also
kept in "a traversal tree and an edge-ID index... for efficient bidirectional
lookups" — a structure the Cypher planner isn't using for this query shape, but
that LatticeDB's own **imperative** `Transaction.get_incoming_edges`/
`get_outgoing_edges` API reads directly, bypassing the planner entirely. Measured
the same lookup that way: **0.12ms** for the edges, plus **2.02ms** to fetch all 27
callers' properties via `get_property` (also imperative, also bypasses Cypher) —
**~2ms total, vs 15.3s** — roughly **7,500x faster** for the identical result.

Run `perfo/benchmark_call_edges.py` yourself to see this directly (compares both
approaches side by side on real indexed data, not synthetic):

```
uv run --python 3.12 --extra dev python perfo/benchmark_call_edges.py [DIR]
```

`CodeGraphBackend.get_call_edges_with_lines()` (`graph/backend.py`) now
formalizes this: **each backend uses whatever primitive is fastest for it**, not
one shared Cypher string forced onto both. `LatticeBackend` implements it via the
imperative edge/property API (`graph/backends/lattice_backend.py`); `KuzuBackend`
keeps Cypher, since Kuzu has no equivalent slowdown (confirmed: 0.52ms for the same
query shape). `QueryOperations.get_callers`/`get_callees`/
`get_callers_and_callees_with_lines` (`graph/queries.py`) all route through it now.
End-to-end, verified on the actual `code-explorer search` command against gemseo:
**15.7s → 0.39s** (a full search-plus-context-assembly run) — roughly **40x**,
confirmed on the real CLI path, not just an isolated query.

One quirk found and worked around while building this: `Edge.properties` returned
by `get_incoming_edges`/`get_outgoing_edges` is unreliably empty (the same
lazy-load pattern already found on `Node.properties` earlier this session) —
`Transaction.get_edge_property(edge.id, key)` must be used instead to actually read
an edge property like `call_line`.

**Why this matters for architecture, not just numbers**: `ImpactAnalyzer` does one
Cypher query per graph node visited during its BFS (Section 13's traversal) via
`get_callers`/`get_callees` — which now use the fast imperative path automatically,
so `ImpactAnalyzer` inherits this fix for free, no changes needed there. The
earlier idea of collapsing the BFS into a single variable-length-path Cypher query
(`MATCH (a)-[:CALLS*1..5]->(b)`) is no longer the right next lever — a
Cypher-based fix would still hit the same `Expand`/`LabelScan` planner behavior
this section just worked around. If depth-N traversal ever needs to be faster than
"N calls to `get_call_edges_with_lines`," the next step would be extending the
imperative-API approach to multi-hop traversal directly, not a fancier Cypher
query.

### Search query latency: what BM25 is actually buying us

A single `search_text()` (BM25) call measures ~2ms on this repo's index. That number
only means something next to the right comparison, so here it is:

- **Not comparable to a live `grep`/`ripgrep` scan** — those re-scan raw files on
  every call; ours is a lookup against an index *already built* at indexing time
  (the cost of building it is separate, see Ingestion above). 2ms for an indexed
  lookup is genuinely fast, in the same range as Elasticsearch/Lucene-style BM25
  query latency — not a coincidence, LatticeDB's FTS is the same family of
  technique.
- **Not comparable to tree-sitter parse time either** — parsing is a one-time,
  amortized-over-every-future-query cost (~1ms/file during indexing); comparing it
  against a single query's 2ms is comparing the wrong two numbers.
- **The actual point, and it's the whole reason this feature exists**: BM25 ranks
  by relevance to the query's *meaning* (tokenized, scored), not just "does this
  substring appear." `grep "resolve call"` finds only literal occurrences of that
  exact phrase; BM25 over `search_text` finds and ranks `CallResolver`,
  `resolve_all_calls`, etc. — related vocabulary, not string matches. That's the
  actual value being built here, not "grep but slightly different."

**But this good number doesn't automatically extend past the search step itself.**
Measured directly (not estimated): `ContextAssembler.assemble_context()` for a
function with 10 callers + 8 callees issues **23 separate Cypher queries** and takes
38.7ms on this same small repo — ~20x slower than the search query it follows, purely
from doing 23 sequential round-trips (one per caller/callee resolved, plus the seed)
instead of one batched query. This is the *same* N+1-query pattern already named
above for `ImpactAnalyzer`, just at one-hop scale instead of depth-8 — and it would
compound the same way at gemseo's real fan-out. Not fixed yet; the fix is the same
kind (fewer, batched queries instead of one per node) as the `ImpactAnalyzer` lever
described above.

### A marketing-vs-measured discrepancy, noted for the record

LatticeDB's own documentation claims sub-microsecond node lookups and describes
itself as dramatically faster than Neo4j for graph operations. We didn't dispute
this outright, but we also didn't take it at face value: it's very likely comparing
against a much heavier baseline (a JVM server database with network-protocol
overhead) on operations chosen to showcase LatticeDB's strengths (bulk/vector
operations), not the small-sequential-query pattern our own `ImpactAnalyzer`
actually does. Our own measurement (same machine, same repo, both backends, same
queries) is the one that governs decisions in this project — not the vendor's.

### Incremental re-index (Phase 3): speed and accuracy vs. full rebuild

`DependencyGraph.ingest_incremental()` (`src/code_explorer/graph/graph.py`) hashes
every file on disk (SHA256, same `compute_hash` as full ingest), skips files whose
hash matches what's already indexed, and for changed/new files calls
`CodeGraphBackend.delete_file()` then re-ingests just that file; files removed from
disk are deleted the same way. `perfo/benchmark_incremental_ingest.py` measures
this on `src/code_explorer` itself (44 files, 387 functions):

| Scenario | Time | Detail |
|---|---|---|
| Full rebuild | 0.37s | 44 files |
| Incremental, no changes | 0.01s | unchanged=44, reprocessed=0 |
| Incremental, 1 file changed | 0.05s | unchanged=43, reprocessed=1 |

~8x faster than a full rebuild on this small repo for a single-file change, and the
gap widens with repo size since unchanged files are never re-parsed or re-upserted.
The benchmark also cross-checks accuracy: it diffs the `(file, name, start_line)`
Function set produced by the incremental path against a full rebuild's — they must
match exactly, or the run is flagged as a mismatch rather than silently trusted.

Run it yourself:

```
uv run --python 3.12 --extra dev python perfo/benchmark_incremental_ingest.py [DIR]
```

**Known limitation, not silently papered over**: a changed file's own outgoing CALLS
are correctly re-resolved against the full current function set. But if an
*unchanged* file calls into a function that just moved, was renamed, or was deleted
in a changed file, that unchanged file's CALLS edges are not re-examined by this
method and can go stale until that caller file is also reprocessed (e.g. via a full
`--reindex`).

---

## 2. Core Design Principles

### 2.1 The graph remains authoritative

The database search layer must never replace structural dependency analysis.

```text
LLM query: "what is responsible for refreshing authentication tokens?"
                │
                ▼
      BM25 / Vector / Fuzzy Search
                │
                ▼
         Candidate Symbols
                │
                ▼
       Exact Graph Resolution
                │
                ▼
          Impact Analysis
```

Search finds candidates. The graph determines: who calls the code; who depends on it;
what it imports; what inherits from it; what implements it; which tests exercise it;
which runtime components load it.

### 2.2 ASTs are temporary

Tree-sitter is an extraction mechanism. The AST is not the database model.

```text
Source File
    │
    ▼
Tree-sitter AST
    │
    ▼
Semantic Extraction
    │
    ├── symbols
    ├── imports
    ├── calls
    ├── inheritance
    ├── decorators
    └── runtime hints
    │
    ▼
Normalized Graph Records
    │
    ▼
Persist
    │
    ▼
Discard AST
```

At no point should an entire repository's ASTs accumulate in memory.

### 2.3 Search is a seed-selection system

There are two different types of queries.

**Structural query** — the seed is already known, no vector search is necessary:

```text
What is affected if I change:
src/auth/token.py::refresh_token
```

**Semantic query** — the seed is unknown, search must discover candidate nodes:

```text
Where is token refresh implemented?

BM25 + Vector + Fuzzy + Symbol-name lookup
           │
           ▼
     Candidate symbols
           │
           ▼
    Graph verification
           │
           ▼
    Impact / context graph
```

This distinction is fundamental.

---

## 3. Target Architecture

```text
                         ┌──────────────────┐
                         │    MONOREPO       │
                         └────────┬──────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ Change Detector   │
                         │ Git / FS / Hash   │
                         └────────┬──────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │                            │
                    ▼                            ▼
             Initial Index                Incremental Index
                    │                            │
                    └─────────────┬─────────────┘
                                  ▼
                        ┌──────────────────┐
                        │ Tree-sitter       │
                        │ Language Parser   │
                        └────────┬──────────┘
                                  │
                                  ▼
                        ┌──────────────────┐
                        │ Semantic          │
                        │ Extractors        │
                        └────────┬──────────┘
                                  │
                                  ▼
                        ┌──────────────────┐
                        │ Normalized        │
                        │ Graph Records     │
                        └────────┬──────────┘
                                  │
                                  ▼
                        ┌──────────────────┐
                        │ Resolution        │
                        │ Pipeline          │
                        └────────┬──────────┘
                                  │
                   ┌──────────────┼──────────────┐
                   ▼              ▼              ▼
                Static         Config          Runtime
                Graph          Graph           Graph
                   │              │              │
                   └──────────────┼──────────────┘
                                  ▼
                        ┌──────────────────┐
                        │   LatticeDB       │
                        │                   │
                        │ Graph             │
                        │ BM25              │
                        │ Vector            │
                        │ Fuzzy Search      │
                        └────────┬──────────┘
                                  │
                                  ▼
                        ┌──────────────────┐
                        │ Retrieval Layer   │
                        └────────┬──────────┘
                                  │
                                  ▼
                        ┌──────────────────┐
                        │ Impact Engine     │
                        └────────┬──────────┘
                                  │
                                  ▼
                        ┌──────────────────┐
                        │ Ranked Subgraph   │
                        └────────┬──────────┘
                                  │
                                  ▼
                             CLI / API / LLM
```

---

## 4. Backend Abstraction

The analyzer must not depend directly on LatticeDB. Define a stable storage
abstraction:

```python
class CodeGraphBackend(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def initialize_schema(self) -> None: ...

    def upsert_nodes(self, nodes: Iterable[NodeRecord]) -> None: ...
    def upsert_edges(self, edges: Iterable[EdgeRecord]) -> None: ...
    def delete_file(self, file_key: str) -> None: ...

    def resolve_symbol(self, query: SymbolQuery) -> list[SymbolMatch]: ...
    def search_text(self, query: str, limit: int) -> list[SearchResult]: ...
    def search_vector(self, vector: list[float], limit: int) -> list[SearchResult]: ...

    def impact(self, seed_ids: list[str], options: ImpactOptions) -> ImpactResult: ...
```

The important rule:

```text
Analyzer
    │
    ▼
Normalized Records
    │
    ▼
Backend Interface
    │
    ├── KuzuBackend
    └── LatticeBackend
```

The first migration should support both backends temporarily.

---

## 5. Canonical Graph Model

The graph schema must remain backend-neutral.

**Primary nodes**

```text
Repository Workspace Package Directory File Module

Class Interface Trait Struct Enum

Function Method Constructor

Variable Parameter Attribute Constant

Test Configuration Plugin Service Route
```

Do not require every language to produce every node type. Instead:

```text
Language
    │
    ▼
Language-specific AST
    │
    ▼
Canonical semantic model
```

For example:

```text
Python function
Java method
Rust function_item
Go function_declaration
TypeScript function_declaration
               ↓
         Function / Method
```

---

## 6. Canonical Edge Model

**Structural**: `CONTAINS`, `DEFINES`, `DECLARES`

**Dependencies**: `IMPORTS`, `IMPORTS_SYMBOL`, `REFERENCES`, `CALLS`, `READS`,
`WRITES`, `ACCESSES`

**Type relationships**: `INHERITS`, `IMPLEMENTS`, `EXTENDS`, `OVERRIDES`

**Testing**: `TESTS`, `TESTED_BY`, `MOCKS`

**Runtime**: `LOADS`, `RESOLVES_TO`, `REGISTERED_AS`, `PROVIDES`, `CONSUMES`

**Configuration**: `CONFIGURES`, `ENABLED_BY`, `SELECTS`

Every edge should eventually support: `confidence`, `evidence`, `language`,
`source_file`, `source_line`, `resolution_method`.

Example:

```json
{
  "type": "CALLS",
  "confidence": 1.0,
  "resolution_method": "static_exact",
  "source_file": "auth/service.py",
  "source_line": 124
}
```

---

## 7. LatticeDB Storage Strategy

LatticeDB is attractive because graph traversal, BM25, and vector similarity can
operate over the same local dataset and query layer. However, Code Explorer must
not automatically index everything into every search structure.

**Graph index** — all structural entities belong in the graph: File, Function,
Method, Class, Import, Test, Plugin.

**Full-text index** — index text that benefits from lexical search: symbol name,
qualified name, signature, docstring, comments, compact source summary. Example
searchable representation:

```text
refresh_token

auth.token.refresh_token

def refresh_token(
    refresh_token: str
) -> AccessToken

Refreshes an OAuth access token.
```

LatticeDB's BM25 search is appropriate for exact identifiers and textual relevance;
its fuzzy search can help with misspellings.

**Vector index** — do not embed every AST node, every import, every variable, every
token. Embed only semantic units such as: Function, Method, Class, Module, File
summary. Recommended vector representation: qualified name + signature + docstring +
compact implementation summary.

---

## 8. Injection Architecture

Initial indexing must be separated into explicit phases.

**Phase A — Discover**

```text
Filesystem
    │
    ▼
Repository Manifest
    │
    ├── path
    ├── hash
    ├── size
    ├── language
    └── modified time
```

Do not parse yet.

**Phase B — Parse**

```text
File
    │
    ▼
Language detection
    │
    ▼
Tree-sitter parser
    │
    ▼
AST
    │
    ▼
Extract semantic facts
    │
    ▼
FileRecord
    │
    ▼
Destroy AST
```

The worker output should contain only normalized data:

```python
@dataclass(slots=True)
class FileRecord:
    file: FileNode
    symbols: list[SymbolNode]
    imports: list[ImportFact]
    calls: list[CallFact]
    inheritance: list[InheritanceFact]
    references: list[ReferenceFact]
```

Do not send parser objects between processes.

---

## 9. Resolution Pipeline

Extraction and resolution must be separate.

**Extraction** — `foo()` becomes:

```json
{
  "kind": "call",
  "raw_name": "foo",
  "file": "service.py",
  "line": 42
}
```

**Resolution** — later:

```text
foo()
    │
    ▼
Local scope lookup
    │
    ├── found → exact symbol
    ▼
Import resolution
    │
    ├── found → imported symbol
    ▼
Class/type context
    │
    ├── found → method
    ▼
Dynamic inference
    │
    └── unresolved
```

Result: `CALLS confidence = 1.0 method = exact_static`, or
`CALLS confidence = 0.65 method = inferred`, or `UNRESOLVED_CALL raw_name = foo`.

This is important for impact accuracy.

---

## 10. Injection into LatticeDB

The initial migration should use bounded transactions:

```text
Records
    │
    ▼
Node batch
    │
    ▼
Lattice transaction
    │
    ▼
Commit
    │
    ▼
Release batch
```

LatticeDB supports write transactions and batch-oriented vector insertion; database
configuration such as vector dimensions is established when the database is created.

Recommended ingestion order:

```text
1. Repository
2. Packages
3. Files
4. Symbols
5. Structural edges
6. Dependency edges
7. Search indexes
8. Vectors
```

Do not generate embeddings during AST parsing. Instead:

```text
INDEX GRAPH
     │
     ▼
Graph complete
     │
     ▼
Select semantic entities
     │
     ▼
Embedding queue
     │
     ▼
Vector insertion
```

This allows graph indexing benchmark and vector indexing benchmark to be measured
independently.

---

## 11. Initial Search Strategy

Code Explorer should implement four retrieval modes.

**Strategy A — Exact.** Use when input looks like `path/to/file.py:function_name` or
`qualified.symbol.name`. Priority: exact path → exact qualified name → exact symbol
name. No semantic search required.

**Strategy B — BM25.** Use for `refresh token`, `plugin authentication`, `OAuth`,
`error handling`. Particularly useful for exact identifiers, error codes, API names,
class names, configuration keys.

**Strategy C — Fuzzy.** Use for `refesh_token`, `authentcation`, `plguin`, `loader`.
This should be fallback behavior rather than the default for all queries.

**Strategy D — Vector.** Use for conceptual queries such as
"Where do we validate access before loading extensions?" Vector search finds
semantically similar code even when the exact words differ.

---

## 12. Hybrid Seed Retrieval

The recommended search pipeline:

```text
User Query
    │
    ▼
Query Classifier
    │
    ├── exact symbol?
    ├── file path?
    ├── identifier?
    └── natural language?
    │
    ▼
Parallel Retrieval
    │
    ├── Exact
    ├── BM25
    ├── Fuzzy
    └── Vector
    │
    ▼
Candidate Merge
    │
    ▼
Score Normalization
    │
    ▼
Graph Validation
    │
    ▼
Seed Nodes
```

A candidate scoring model:

```text
seed_score =
    exact_score
  + lexical_score
  + vector_score
  + graph_context_score
```

Graph context score can reward: highly referenced symbol, symbol in requested
package, symbol matching language filter, symbol near known relevant node.

---

## 13. Impact Analysis Pipeline

This is the central pipeline.

```text
                    CHANGE
                       │
                       ▼
                 Seed Resolver
                       │
                       ▼
                   Seed Set
                       │
                       ▼
             Direct Dependency Scan
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
       CALLERS       IMPORTERS      TYPES
         │             │             │
         └─────────────┼─────────────┘
                       ▼
             Transitive Expansion
                       │
                       ▼
              Dynamic Expansion
                       │
            ┌──────────┼──────────┐
            ▼          ▼          ▼
         Runtime     Config      Plugin
                       │
                       ▼
                Impact Scoring
                       │
                       ▼
                 Rank + Prune
                       │
                       ▼
               Impact Subgraph
                       │
                       ▼
                 Tests / LLM
```

---

## 14. Impact Propagation

Not every edge has equal meaning. Initial policy:

```python
EDGE_WEIGHTS = {
    "CALLS": 1.00,
    "REFERENCES": 0.95,
    "IMPORTS_SYMBOL": 0.90,
    "IMPORTS": 0.75,
    "OVERRIDES": 0.90,
    "IMPLEMENTS": 0.85,
    "INHERITS": 0.75,
    "TESTS": 0.85,
    "LOADS": 0.90,
    "CONFIGURES": 0.70,
}
```

Propagation:

```text
impact_score =
    source_score
    × edge_weight
    × resolution_confidence
    × depth_decay
```

Example:

```text
Changed Symbol
     │
     │ CALLS confidence 1.0
     ▼
Direct Caller score 1.0
     │
     │ CALLS confidence 1.0
     ▼
Second-level Caller score 0.8
     │
     │ IMPORTS confidence 0.8
     ▼
Third-level Candidate score 0.48
```

This prevents every reachable node from being treated as equally impacted.

---

## 15. Impact Categories

Impact should not be returned as a single flat list. Use categories:

```text
DIRECT_BEHAVIORAL
TRANSITIVE_BEHAVIORAL
TYPE_IMPACT
API_IMPACT
IMPORT_IMPACT
TEST_IMPACT
CONFIG_IMPACT
RUNTIME_IMPACT
POSSIBLE_DYNAMIC_IMPACT
```

Example:

```json
{
  "direct_behavioral": [],
  "transitive_behavioral": [],
  "tests": [],
  "runtime": [],
  "possible": []
}
```

This is substantially more useful to humans and LLMs.

---

## 16. Dynamic and Runtime Dependencies

Static AST analysis cannot reliably detect: importlib, reflection, dependency
injection, plugin discovery, string-based loading, configuration-driven selection.

Therefore Code Explorer should support evidence sources: `STATIC`, `CONFIG`,
`RUNTIME`, `USER_DECLARED`.

Example:

```text
PluginLoader
    │
    │ STATIC confidence 0.65
    ▼
Unknown Plugin

PluginLoader
    │
    │ RUNTIME confidence 1.0
    ▼
StripePlugin
```

The impact engine must preserve both evidence and confidence.

---

## 17. Query Strategies

**Query: Exact impact** — `impact src/auth/token.py:refresh_token`

```text
Exact node lookup
    ↓
Seed
    ↓
Reverse dependency traversal
    ↓
Rank
    ↓
Return impact
```

No embeddings.

**Query: Natural-language impact** — "What breaks if token persistence changes?"

```text
BM25 + Vector + Fuzzy
    ↓
Candidate seeds
    ↓
Graph validation
    ↓
Impact traversal
    ↓
Ranked impact graph
```

**Query: Context retrieval** — "Explain how plugins are authenticated."

```text
Hybrid search
    ↓
Top semantic nodes
    ↓
Neighborhood expansion
    ↓
Context budget
    ↓
Relevant source retrieval
```

---

## 18. LLM Context Strategy

Never send the full graph. The LLM should receive a bounded representation:

```text
Seed:
    auth.token.refresh_token

Direct impact:
    AuthService.refresh
    TokenStore.save

Transitive:
    LoginController.refresh

Tests:
    tests/auth/test_refresh.py

Runtime:
    OAuthPlugin

Confidence:
    high / medium / possible
```

Then retrieve source only for selected nodes. Example budget:

```text
max seeds:        10
max impact nodes: 200
max graph depth:  4
max source bytes: configurable
```

The graph must be pruned before source retrieval.

---

## 19. Recommended LatticeDB Backend Layout

```text
src/code_explorer/
    graph/
        backend.py
        models.py
        kuzu_backend.py
        lattice_backend.py
        search.py
        impact.py
        schema.py
        migration.py

    indexing/
        discover.py
        parse.py
        extract.py
        resolve.py
        ingest.py
        embeddings.py
```

Important separation: `parse.py` → `extract.py` → `resolve.py` → `backend.py`.
No backend-specific code in parsers or extractors.

---

## 20. Migration Phases

**Phase 0 — Freeze the Canonical Model.** Before touching the backend: define
`NodeRecord`; define `EdgeRecord`; define stable IDs; define canonical edge names.
Success criteria: Kuzu and LatticeDB can consume identical records.

**Phase 1 — Read-only Lattice Prototype.** Implement open, query, exact lookup,
graph traversal. Use an exported subset of the existing Code Explorer graph.
Validate: same seed, same traversal, same impact result.

**Phase 2 — Initial Ingestion.** Implement nodes, edges, bounded transactions.
Benchmark: peak RSS, index time, disk size, nodes/sec, edges/sec.

**Phase 3 — Incremental Updates.** Implement: modified file → delete old file
subgraph → re-extract → insert new nodes → insert new edges. Validate graph
consistency.

**Phase 4 — BM25.** Index symbol names, qualified names, signatures, docstrings,
compact semantic descriptions. Do not index every raw source file by default.

**Phase 5 — Vector Search.** Add vectors only to Function, Method, Class, Module,
File summary. Start with one embedding field. Do not create multiple embedding
models initially. LatticeDB's vector dimension is configured when the database is
created, so embedding model selection should be decided explicitly before creating
a production database.

**Phase 6 — Hybrid Retrieval.** Implement Exact, BM25, Fuzzy, Vector → Merge →
Normalize → Graph-aware reranking.

**Phase 7 — Confidence-aware Impact.** Add edge confidence, resolution evidence,
depth decay, impact categories. This is likely more important to final result
quality than vector search.

---

## 21. Benchmark Plan

Every backend comparison must use the same repository, same extracted graph, same
machine, same data, same queries. Do not compare Kuzu on one graph vs LatticeDB on
another graph.

**Injection**: peak RSS, average RSS, wall-clock time, CPU, disk size, nodes/sec,
edges/sec.

**Incremental update**: 1 file, 10 files, 100 files, 1 package.

**Exact query**: symbol lookup, direct callers, transitive callers, imports, tests.

**Search**: exact identifiers, natural language, misspellings, mixed queries.

**Impact**: depth 1, depth 2, depth 4, depth 8.

---

## 22. Risk Register

**Risk: LatticeDB maturity.** LatticeDB is a newer engine than Kùzu, so migration
should remain reversible during the experimental phase. Its own comparison
documentation explicitly distinguishes its local relationship/search strengths from
workloads better suited to analytical graph engines or multi-client systems.
Mitigation: backend abstraction + canonical graph records + temporary dual-backend
support.

**Risk: Single-writer ingestion.** LatticeDB uses an embedded single-writer model.
Therefore: many parser workers → one ingestion coordinator → LatticeDB. Do not allow
parser workers to write directly to the database.

**Risk: Vector memory.** Vectors and HNSW indexing have memory and storage costs.
Mitigation: embed fewer entities, separate vector phase, benchmark dimensions,
measure peak RSS.

**Risk: Search degrades structural accuracy.** Mitigation: search discovers
candidates, graph validates dependencies, impact scoring exposes uncertainty.

---

## 23. Final Target Architecture

```text
                         USER QUERY
                             │
                ┌────────────┴────────────┐
                │                          │
                ▼                          ▼
          EXACT CHANGE              NATURAL LANGUAGE
                │                          │
                ▼                          ▼
            Graph Seed        Exact + BM25 + Vector
                │                          │
                └────────────┬────────────┘
                             ▼
                         Seed Set
                             │
                             ▼
                     Graph Validation
                             │
                             ▼
                     Impact Traversal
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
            Static         Config         Runtime
              │              │              │
              └──────────────┼──────────────┘
                             ▼
                      Score / Confidence
                             │
                             ▼
                       Rank / Prune
                             │
                             ▼
                      Impact Subgraph
                             │
                             ▼
                     Retrieve Source
                             │
                             ▼
                            LLM
```

---

## 24. Final Recommendation

The migration should not be treated as a straight replacement (Kuzu → LatticeDB).
The architecture should become:

```text
                    CODE EXPLORER
                          │
                    Canonical Graph
                          │
                    Backend Interface
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
        Kuzu/LadybugDB            LatticeDB
              │                       │
              │              ┌────────┼────────┐
              │              │        │         │
              │            Graph     BM25    Vector
              │              │        │         │
              └──────────────┴────────┴─────────┘
                          │
                    Impact Engine
                          │
                  CLI / API / LLM
```

The migration should succeed only when the following statement is true:

> Given the same repository, the same extracted dependency graph, and the same
> change, both backends produce equivalent structural impact results.

Only after that should LatticeDB-specific search capabilities be used to improve:
seed discovery, semantic queries, typo tolerance, hybrid retrieval, LLM context
selection.

The structural graph remains the foundation. Search makes the graph easier to
enter. Impact analysis makes the graph useful.

## Reference links

- [LatticeDB official documentation](https://docs.latticedb.org/)
- [LatticeDB Python quick start](https://docs.latticedb.org/getting-started/quickstart)
- [LatticeDB database configuration and vector dimensions](https://docs.latticedb.org/configuration/opening)
- [LatticeDB full-text search guide](https://docs.latticedb.org/guides/full-text-search)
- [LatticeDB GitHub repository](https://github.com/jeffhajewski/latticedb)
- [Embedded graph database comparison guide](https://docs.latticedb.org/comparisons/overview)

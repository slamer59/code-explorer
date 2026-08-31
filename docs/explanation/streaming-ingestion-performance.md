# Streaming Ingestion: Measured Performance

> Status: **evidence log**, not a design. Every number here was measured on this
> machine against `/home/pedot/Developpments/gemseo` with the streaming ingestion
> pipeline (`graph/lattice_streaming.py`) merged into main. Reproduce with the
> `perfo/` scripts named in each section.
>
> **What the corpus actually is:** that path is not the `gemseo` library alone —
> it is a parent directory holding three projects (`gemseo`, the MDO library;
> `gemseo-scenario-configurable`, a FastAPI/SQLAlchemy/Kubernetes service; and
> `gemseo_as_a_service`), 2,107 Python files in total. So it is a small
> multi-project monorepo, which makes it a more representative target than a
> single library — but it also means the call mix is skewed toward web-framework
> and test-mock calls, which matters when reading the call-resolution numbers
> below.

## Why this document exists

The streaming pipeline was built to fix three things at 100k-file monorepo scale:
peak RAM, wall-clock, and responsiveness. Two of the three turned out to be
mis-targeted once measured, and the profile pointed at costs nobody had ranked.
This records what is actually true, so the next round of work is aimed at the
critical path rather than at the parts that were easiest to reason about.

## The corpus

| Quantity | Value |
|---|---|
| Python files | 2,107 |
| Nodes written | 15,421 |
| Edges written | 21,551 |
| Call references produced | 53,557 |
| — resolved to a CALLS edge | **8,237** |
| — left unresolved | **45,320** |

For contrast, the previous `CallResolver` (plain cross-file name matching) produced
roughly **320,000** CALLS edges on the same repo. The import-aware resolver produces
8,237. The truth is somewhere between: the old one over-linked (every `run()` call
pointed at every `run()` definition), the new one refuses to guess. Which of those
two errors is worse for `impact`/`trace`/context bundles is not yet settled —
see "Open questions".

## Stage balance — where wall-clock goes

`perfo/benchmark_ingest_stage_balance.py`. It wraps the analysis iterator to time
how long the consumer blocks waiting for parsed files, times each batch commit via
`on_batch_committed`, and times the finalize drain separately (it runs after the
last batch and is invisible to the batch callback).

| Stage | Time | Share | On the critical path? |
|---|---|---|---|
| Committing batches | 18.5s | 60% | **yes** |
| Finalize (pending-call drain) | 10.7s | 35% | **yes — nothing overlaps it** |
| Consumer starved (waiting on parse) | 0.8s | 3% | no |
| **Wall clock** | **31.1s** | | |

**Ingestion is writer-bound, not parser-bound.** Worker processes finish all 2,107
files in ~20s while the writer needs ~29s. Parsing is fully hidden. This invalidates
the intuition the pipeline was designed around ("parsing is CPU intensive, so
parallelise it") — parsing is already fast enough to be free.

### The parser in-flight window: a real bug with no measurable cost

Observed symptom: CPU shows a flat → 100% → flat sawtooth during indexing.

The mechanism is real. `iter_analyze_directory` only calls `submit_next()` when the
consumer pulls an item, and the in-flight window was `worker_count * 2` — 32 files
at 16 workers — while the consumer swallows a whole batch (~66 files at the 2,000-op
batch size) before committing. So the pool drains during batch assembly and idles
through the entire commit.

Fixing it (`settings.analysis_queue_depth`, default 256) does **not** improve
wall-clock:

| Window | Wall | Starved | Commit | Finalize |
|---|---|---|---|---|
| 32 (`worker_count * 2`) | 30.9s | 1.5s (5%) | 17.7s (57%) | 10.5s (34%) |
| 256 | 31.1s | 0.8s (3%) | 18.5s (60%) | 10.7s (35%) |

Idle workers are free when the writer is the bottleneck. The setting was kept because
it costs ~16 MB (at ~63 KB per pending `FileAnalysis`) and becomes load-bearing if the
writer gets faster — which is the goal — or on machines with fewer cores. It earns no
performance claim today.

## CPU profile — where the time actually is

`py-spy record --rate 100 -f speedscope`, 3,186 samples over a full gemseo index.

### Self time (the CPU is literally here)

| Share | Frame |
|---|---|
| **53.6%** | `commit` (latticedb `transaction.py:97`) |
| **14.4%** | `get_property` (`transaction.py:390`) |
| 4.9% | `find_nodes_by_label_property` |
| ~9% | ctypes marshalling (`cast`, `_python_to_value`, `string_at`) |
| 1.7% | `set_property` |

### Cumulative (which of our functions owns that time)

| Share | Frame |
|---|---|
| 34.6% | `LatticeBackend.upsert_nodes` |
| 19.8% | `LatticeStreamingIngestor._resolve_references` |
| 17.8% | `LatticeBackend.apply_call_outcomes` |
| 17.4% | `LatticeStreamingIngestor._finalize_pending` |
| 15.2% | `find_functions_by_properties` / `_node_dict` |
| 9.1% | `publish_stream` |

### Why parsing is free and writing is not — both are native

It is tempting to explain the stage balance as "tree-sitter is native C, so parsing is
fast." That is true but not the distinction that matters, because **LatticeDB is
native too** — its Python package is a ctypes wrapper over a native library. Neither
stage is bottlenecked by interpreted Python doing the actual work.

What separates them is the *shape* of the calls across the boundary:

| | Crossings | Work per crossing |
|---|---|---|
| Parsing | one per file (2,107 total), in 16 separate processes — genuinely parallel, no GIL | large: parse a whole file |
| Property reads | ~7 per candidate, tens of thousands of candidates | tiny: return one field |

The profile shows the consequence directly: `get_property` is 14.4% of self-time and
another ~9% goes to pure ctypes marshalling (`cast`, `_python_to_value`, `string_at`).
That is not a slow database; it is a fast boundary crossed far too often with tiny
payloads. The fix is *fewer, fatter* crossings — drop unused fields, cache repeated
lookups, bulk-fetch — not a faster engine.

`commit` at 53.6% is the other half of the story and is a different animal: that is
native durability work happening *inside* LatticeDB. No Python-side tuning touches it.
The only lever is **committing fewer times**, which is exactly why the batch-size
tie-break below matters.

### Attributing the 53.6%: node commits, not edge commits

Assigning every `commit` sample to the call chain that reached it:

| Share of commit time | Caller |
|---|---|
| **64.6%** | `LatticeBackend.upsert_nodes` |
| 20.3% | `apply_call_outcomes` ← `_finalize_pending` |
| 12.8% | `apply_call_outcomes` ← batch phase |
| **2.2%** | `LatticeBackend.upsert_edges` |

Node commits cost roughly **30× more than edge commits**. Since both go through
the same transaction and WAL machinery, the difference has to be what each write
maintains:

| Write | Indexes maintained |
|---|---|
| `Function` node | `id`, `file`, `name`, `module`, `parent_class` property indexes (five) **plus** the BM25 FTS index on `search_text` |
| `CALLS` edge | one property index on `call_reference_id` |

LatticeDB's Property Indexes guide is explicit that an index "adds a little work
to every write that touches the indexed property", and its README notes a
"repeated-term FTS indexing workload that previously exposed quadratic append
behavior". Source code is precisely that workload: every `search_text` repeats
path components, `self`, and common identifiers.

Two of our declared indexes also look questionable against the vendor's own
guidance that "high-variety properties benefit most":

- **`Function.parent_class`** — the overwhelming majority of functions are
  module-level, so most values are the empty string.
- Indexes are declared for `Variable`, `Import`, `Decorator`, `Attribute`,
  `Exception`, and `Module`, node types the streaming path **never writes**.
  (Harmless if never written, but they are dead weight in the schema.)

**But the low-selectivity indexes cannot simply be dropped.** Removing the
`name`/`module`/`parent_class` indexes and re-running raises
`LatticeUnsupportedError: Unsupported operation or value type` the first time
`_resolve_references` calls `find_nodes_by_label_property`. This is deliberate
LatticeDB behaviour, documented in the Property Indexes guide: an indexless
lookup fails loudly rather than silently degrading to a scan, precisely so you
cannot "get scan performance while believing you had index performance". So
`parent_class` is a write-time cost that could only be removed by changing the
resolution strategy, not by deleting a line from `initialize_schema`. The FTS
index is the only genuinely optional one.

`perfo/benchmark_index_maintenance_cost.py` isolates this by building the same
corpus with FTS omitted, and with the low-selectivity property indexes omitted,
producing identical graph contents each time.

### Two levers ruled out by measurement

- **Buffer pool size.** The Performance Tuning guide recommends raising
  `cache_size_mb` for large databases, and our index file is 259 MB against a
  100 MB default cache. Raising it to 512 MB changed nothing: 30.7s versus 31.1s,
  within noise. Not the bottleneck.
- **Commit batching via a durability knob.** The durability guide describes the
  commit path as "The change is written to the log. The log is flushed to disk.
  Only then is the commit reported as successful" — an fsync per commit with no
  batching mechanism exposed. The only relevant switch, `enable_wal=False`,
  disables transactions entirely (`beginTransaction` returns
  `TransactionsNotEnabled`) and is documented only for "bulk-loading a database
  you are about to serialize or discard". Our write path is built on
  transactions, so this is not available.

Note also that the vendor's own example (`paper_graph_rag.py`) builds its entire
dataset — nodes, edges, vectors, and FTS indexing — inside **one** `db.write()`
with a single `txn.commit()`. Our pipeline commits every 1,000 items in
`upsert_nodes`, again in `upsert_edges`, and again in `apply_call_outcomes`.

## What the profile implies

### 1. Adaptive batch sizing is biased against the dominant cost

`AdaptiveBatchController` picks *the smallest* candidate size whose median throughput
is within 5% of peak. But `commit` is 53.6% of CPU, and commit cost is largely
per-transaction — so preferring smaller batches maximises the number of commits, which
is the most expensive thing in the profile. The tie-break optimises for memory at the
expense of the measured bottleneck.

It is also **not reproducible**: on identical input, on the same machine, it selected
2,000 ops/batch on one run (32 batches) and 1,000 on the next (54 batches). Two
causes, both plausible:

- **The metric is confounded.** `operations_per_second` counts
  `nodes + structural_edges + call_references` as interchangeable "operations", but a
  node write (which also updates the FTS index), an edge write, and a call-reference
  lookup cost very different amounts. Batch composition drifts between samples, so the
  throughput numbers being compared do not measure the same work.
- **The environment is non-stationary.** The database grows during ingestion, so later
  batches are slower regardless of size. Interleaving candidate sizes mitigates the
  bias but three samples per size is thin against that drift.

Calibration also costs 4 candidates × 3 samples = **12 batches** — on gemseo that is
12 of ~54, and the answer it buys does not reproduce.

### 2. Unresolvable calls are paid for six times

A call that can never resolve — `len(x)`, `np.array(...)`, anything defined outside
the repo — currently costs:

1. a candidate lookup during its batch
2. a `publish_stream` write into `PENDING_CALL_STREAM`
3. a `read_stream` read back during finalize
4. **a second full candidate lookup** (`find_functions_by_properties` + `_node_dict`)
5. a `publish_stream` write into `UNRESOLVED_CALL_STREAM`
6. a stream trim

Deferral itself is correct: a call may target a function in a file not yet ingested,
and the durable pending stream is what makes that recoverable (and what makes
incremental re-resolution work). But "not ingested *yet*" and "does not exist
*anywhere*" are currently treated identically. At finalize time ingestion is complete,
so the full function-name set is known and a set-membership test can route externals
straight to unresolved, skipping step 4 — the expensive one.

This is where the 9.1% `publish_stream` and 17.4% `_finalize_pending` come from, driven
by 45,320 deferred references on a repo 50× smaller than the target scale.

### 3. Candidate materialisation fetches fields nobody reads

`find_functions_by_properties` builds a dict per candidate via `_node_dict`:

```python
properties = ("id", "name", "file", "module", "parent_class", "start_line", "end_line")
return {key: txn.get_property(node_id, key) for key in properties}
```

Seven separate `get_property` ctypes calls per candidate, and `get_property` is 14.4%
of CPU self-time. But `_resolution()` reads only `id`, `name`, `file`, `module`, and
`parent_class` — **`start_line` and `end_line` are fetched for every candidate and
never used**, roughly 29% of this path, removable in one line.

Two further inefficiencies on the same path:

- Lookups use `limit=10_000` for `("file", caller_file)`, `("module", target_module)`
  and `("parent_class", base)`, materialising large candidate lists that are then
  filtered down to one match in Python.
- Results are deduplicated *within* a batch (the `requests` dict is keyed by
  `(property, value)`) but never reused *across* batches, even though in a full build a
  file's function set never changes once ingested.

## Memory

Measured by parsing a 150-file sample and watching peak RSS: **62.8 KB per retained
`FileAnalysis`** — each holds `_source_content` (the whole file's text), `_source_lines`,
and a `source_code` slice per function/class, so the file's text is retained several
times over.

| | gemseo (2,107 files) | Extrapolated to 100k files |
|---|---|---|
| All `FileAnalysis` held at once (the pre-streaming model) | ~132 MB | **~6.1 GB** |

RAM is a non-issue at gemseo scale; the 6 GB wall is what streaming exists to avoid,
and that goal is met by converting and dropping each `FileAnalysis` as it arrives.

## Incidental finding: a Cypher label scan that does not finish

`MATCH (f:Function) RETURN f.name AS name` against the 260 MB gemseo index ran for
~10 minutes without returning and had to be killed. The imperative equivalent
(`get_nodes_by_label("Function")` plus `get_property` per node) completes quickly.
This is consistent with the Cypher planner problems already documented in
`latticedb-migration.md`'s performance findings, and is why
`perfo/benchmark_call_resolution_quality.py` uses the imperative API.

## Index maintenance, measured

`perfo/benchmark_index_maintenance_cost.py`, identical graph contents in both rows:

| Configuration | Wall | Commit | DB size |
|---|---|---|---|
| All indexes (current) | 29.7s | 17.2s | 243 MB |
| No FTS index | **25.4s** | **13.3s** | **159 MB** |

The BM25 index costs **4.3s (14% of wall) and 84 MB (35% of the file)**. Real, and
worth moving to a post-load build eventually — `create_node_fts_index` scans
existing nodes once, so the same index can be had for one bulk scan instead of
maintenance across ~15k individual writes — but it is not the dominant cost.

## The dominant cost: unresolved call references

Sampling 4,000 records from `UNRESOLVED_CALL_STREAM`:

| | Share |
|---|---|
| Target name does **not** exist anywhere in the graph (stdlib, third-party, builtins) | **86.4%** |
| Target name **does** exist — a potential missed edge | 13.6% |
| `call.unresolved` / `call.ambiguous` | 90.7% / 9.3% |
| Call shape: `obj.method()` / bare `func()` / `self.method()` | 55% / 44% / 0.3% |

Classifying the absent names by what they actually are (8,000-record sample):

| Bucket | Share of absent | Examples |
|---|---|---|
| Attribute calls on external objects | 36.8% | `logger.info`, `mock.patch`, `list.append`, `session.commit`, `client.post` |
| External class constructors | 29.4% | `Mock`, `MagicMock`, `Column`, `HTTPException`, `Depends`, `Path` |
| **Python builtins** | **24.1%** | `print`, `len`, `str`, `isinstance`, `object`, `ValueError`, `hasattr` |
| **Stdlib** | **8.5%** | `json.dumps`, `uuid4`, `time.sleep`, `re.match`, `os.getenv` |
| Bare names not in graph | 1.2% | `cls`, `get_type_hints`, `defaultdict` |

About a third is core Python — and more than that in truth, since `Path`,
`ValueError` and `object` land in the constructor bucket by capitalization rather
than by origin. The rest is third-party framework and mock code, inflated here by
the web-service and test-heavy projects in this particular corpus.

This split matters for the fix: **builtins and stdlib can be filtered in-process
for free**, using `dir(builtins)` and `sys.stdlib_module_names`, before a
reference ever reaches the database. The framework calls need the graph's own
function-name set, which is only complete at finalize time.

So roughly **39,000 of the 45,320 references can never resolve**, no matter how
many files arrive. Each one is nonetheless published to the pending stream, read
back during finalize, put through a full candidate lookup, and republished to the
unresolved stream — six operations for a call to `len()`. Summing what that
costs: the finalize pass (10.7s, 35% of wall) plus the `apply_call_outcomes`
share of commit time (~33% of 17.2s ≈ 5.7s) is **over half the run**, more than
FTS, buffer-pool, batching, and parallelism put together.

It is also the *quality* story, and it is better than the raw ratio suggests:
only ~6,160 references (13.6% of 45,320) name a function that genuinely exists
and were not linked. Against 8,237 resolved, the import-aware resolver captures
roughly **57% of resolvable internal calls** — not 15%. The old name-matching
resolver's ~320,000 edges were largely spurious by comparison.

### `read_stream` is not quadratic

Paging `UNRESOLVED_CALL_STREAM` at `limit=500` costs 8ms for the first page and
7ms for the last — flat in offset. The earlier suspicion that `_finalize_pending`
scales quadratically in pending-call count is **disproved**; its cost is simply
proportional to how many references it re-examines, which is why cutting the
external 86% matters. (An earlier probe that appeared to hang for minutes was
doing a full label scan, not stream paging.)

## Open questions (measurements in flight)

- **Of the 45,320 unresolved references, how many name a function that actually exists
  in the graph?** Those are missed edges (a quality regression against the old
  resolver); the rest are external/stdlib and correctly unresolved. This decides
  whether call-resolution quality outranks the streaming work.
  (`perfo/benchmark_call_resolution_quality.py`)
- **Is `read_stream` paging linear or quadratic in offset?** `_finalize_pending` drains
  in 1,000-record windows using `after_sequence`. If per-page cost grows with offset,
  finalize is quadratic in pending-call count, which would scale badly toward 100k
  files. The same benchmark reports per-page timings for this reason. An early signal:
  paging 4,000 records out of a 45,320-record stream took over four minutes.
- **Does the commit cost scale with batch size or batch count?** This decides whether
  fixing the adaptive controller's tie-break is worth anything. Testable directly by
  pinning `CODE_EXPLORER_UPSERT_BATCH_SIZE` and comparing wall-clock.

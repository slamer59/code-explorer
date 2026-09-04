# Streaming Ingestion: Measured Performance

> Status: **evidence log**, not a design. Every number here was measured on this
> machine against `/home/pedot/Developpments/gemseo` with the streaming ingestion
> pipeline (`graph/lattice_streaming.py`) merged into main. Reproduce with the
> `perfo/` scripts named in each section.
>
> **What the corpus actually is:** that path is not the `gemseo` library alone —
> it is a parent directory holding three projects (`gemseo`, the MDO library;
> `gemseo-scenario-configurable`, a FastAPI/SQLAlchemy/Kubernetes service; and
> `gemseo_as_a_service`), 2,103 Python files after the hardened exclude
> patterns (2,107 before them — early tables below still carry the older
> count). So it is a small multi-project monorepo, which makes it a more
> representative target than a single library — but it also means the call mix
> is skewed toward web-framework and test-mock calls, which matters when
> reading the call-resolution numbers below.
>
> **Read the call-resolution counts as ranges, not constants.** Repeat runs do
> not produce identical graphs. Over one 22-run block, resolved calls ranged
> **14,874–14,988** and total edges **35,555–35,669** — and two repeats of the
> *same* configuration differed by as much as **39 resolved calls**, so the
> spread is not explained by the settings being varied. Node count was stable
> at 15,403 in all 22. That block predates the module-root fix, so its absolute
> band is not today's; what carries over is the **magnitude** of the noise,
> roughly ±60 resolved calls. Any single resolved-call figure quoted below is
> one sample of a noisy quantity — do not wire one into a regression gate.

## Why this document exists

The streaming pipeline was built to fix three things at 100k-file monorepo scale:
peak RAM, wall-clock, and responsiveness. Two of the three turned out to be
mis-targeted once measured, and the profile pointed at costs nobody had ranked.
This records what is actually true, so the next round of work is aimed at the
critical path rather than at the parts that were easiest to reason about.

## The corpus

The left column is the original baseline this document opens against; the
right column is where the pipeline stands after every change recorded below.
Both were measured the same way; see "Combined result" for the detail.

| Quantity | Baseline (first measurement) | Current |
|---|---|---|
| Python files | 2,107 | 2,103 |
| Nodes written | 15,421 | 15,403 |
| Edges written | 21,551 | ~36,116 |
| Call references produced | 53,557 | — (18,529 now skipped before any stream) |
| — resolved to a CALLS edge | **8,237** | **~15,435** (sample; see spread above) |
| — left unresolved | **45,320** | **~7,733** |

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
with a single `txn.commit()`. Our pipeline commits every `ingest_write_chunk_size`
(1,000) rows in `upsert_nodes`, again in `upsert_edges`, and again in
`apply_call_outcomes`. Widening that transaction turned out not to matter — see the
write-transaction-width note below.

## What the profile implies

### 1. Adaptive batch sizing was biased against the dominant cost — and has been deleted

**Outcome: `AdaptiveBatchController` was removed** (commit `1ccd459`). Batch size is
now the fixed setting `upsert_batch_size = 250`. What follows is why, kept because the
reasoning is the useful part.

`AdaptiveBatchController` picked *the smallest* candidate size whose median throughput
was within 5% of peak. But `commit` is 53.6% of CPU, and commit cost is largely
per-transaction — so preferring smaller batches maximises the number of commits, which
is the most expensive thing in the profile. The tie-break optimised for memory at the
expense of the measured bottleneck.

It was also **not reproducible**: on identical input, on the same machine, it selected
1,000, then 2,000, then 8,000 ops/batch on three consecutive runs. Two causes, both
plausible:

- **The metric is confounded.** `operations_per_second` counted
  `nodes + structural_edges + call_references` as interchangeable "operations", but a
  node write (which also updates the FTS index), an edge write, and a call-reference
  lookup cost very different amounts. Batch composition drifts between samples, so the
  throughput numbers being compared did not measure the same work.
- **The environment is non-stationary.** The database grows during ingestion, so later
  batches are slower regardless of size. Interleaving candidate sizes mitigates the
  bias but three samples per size is thin against that drift.

The measurement that settled it is the batch-size sweep
(`perfo/benchmark_batch_size_sweep.py`, 2 runs per point on the 2,103-file corpus,
agreeing to within 0.3s):

| Target ops/batch | 50 | 100 | 200 | 350 | 500 | 1,000 | 2,000 | 4,000 | 8,000 |
|---|---|---|---|---|---|---|---|---|---|
| Commit | 12.3s | 11.2s | **10.7s** | 11.1s | 11.2s | 12.2s | 12.7s | 13.7s | 13.3s |
| Wall | 25.6s | 24.4s | **23.9s** | 24.1s | 24.4s | 25.2s | 25.8s | 26.9s | 27.0s |

It is a shallow bowl with its floor at **200–350**. The controller's candidate set was
`upsert_batch_size` doubling up to `ingest_batch_max_size` — 1,000/2,000/4,000/8,000 —
so its *entire* search space sat on the wrong side of the knee: it could only ever pick
something worse than the default it started from. Across that stretch the wall range is
25.2–27.2s, so at a 5% tolerance it was choosing between points it cannot distinguish.
It was reading noise, and paying 4 candidates × 3 samples = **12 calibration batches**
to do it.

That is also why no metric fix or bandit was warranted: a fixed constant beats every
size the controller could reach. The prediction in the profile — that fewer, larger
commits would win because `commit` dominates — turned out to be wrong past ~350, which
is itself the interesting result. The likely reason: commit cost is dominated by
per-row index maintenance, which grouping cannot amortise, so batch size buys pipeline
overlap and nothing else. The write-transaction-width sweep in the same script is flat
across a 64× range, which is consistent with that.

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

The BM25 index costs **4.3s (14% of wall) and 84 MB (35% of the file)**. Real, but
not the dominant cost.

**Since done** (`LatticeBackend.ensure_fts_indexes`): the index is now built in one
pass *after* the bulk load rather than maintained across ~15k individual writes
(`create_node_fts_index` scans existing nodes when created).
`perfo/benchmark_ingest_stage_balance.py` on the same corpus, two runs each:

| | Wall | Commit | DB size |
|---|---|---|---|
| FTS maintained per write | 33.0s / 30.7s | 19.6s / 18.3s | 243 MB |
| FTS built after the load | 29.0s / 31.2s | **14.2s / 13.7s** | 242 MB |

Commit time drops ~26%. Wall drops much less and stays inside run-to-run noise —
the one-pass build still costs real time, it is just no longer attributed to
per-batch commits. The 84 MB is paid either way; only the maintenance is avoided.
The `no FTS index` row above remains the ceiling for anyone who genuinely does not
need lexical search.

## The dominant cost: unresolved call references

*All figures in this section are from the baseline run (8,237 resolved / 45,320
unresolved). They are what motivated the fixes recorded further down, and are kept
as the "before" picture; see "Combined result" for where the pipeline stands now.*

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
and were not linked. Against 8,237 resolved, the import-aware resolver captured
roughly **57% of resolvable internal calls** — not 15%. The old name-matching
resolver's ~320,000 edges were largely spurious by comparison. (Class-aware
lookup and the module-root fix have since taken resolved calls to ~15,435, so
this 57% is the *baseline* capture rate, not the current one.)

### `read_stream` is not quadratic

Paging `UNRESOLVED_CALL_STREAM` at `limit=500` costs 8ms for the first page and
7ms for the last — flat in offset. The earlier suspicion that `_finalize_pending`
scales quadratically in pending-call count is **disproved**; its cost is simply
proportional to how many references it re-examines, which is why cutting the
external 86% matters. (An earlier probe that appeared to hang for minutes was
doing a full label scan, not stream paging.)

## Resolution quality: classes were never searched

Call resolution looked up candidates via `find_functions_by_properties`, which
queries `Function` nodes only — but `file_analyses_to_records` also creates
`Class` nodes, so **every call to a project class constructor was unresolvable**.
Extending the lookup to both labels (`find_symbols_by_properties`) plus an
approximate re-export rule took resolved CALLS edges from **8,237 to 15,071
(+83%)** on this corpus, of which **5,379 target a Class node**.

Resolution-method split immediately after that change (before the module-root fix
below): `global_unique` 6,250, `package_reexport` 6,121, `same_class` 1,277,
`same_file` 1,187, `direct_base` 181 — and `explicit_import` **zero**, which is
what the next section is about.

Cost: wall clock rose 32.1s → 34.2s (finalize 11.7s → 13.7s) because each lookup
now materialises candidates for two labels instead of one.

### Fixed: module names were derived from the wrong root

**Resolved.** Node `module` properties are now derived from the *package* root
rather than the indexed root. This is the single highest-value correctness fix in
this document, so the broken mechanism is worth keeping on the record.

`explicit_import` — the highest-confidence rule — fired **zero times** on this
corpus. `_module_name()` derived a module from the file path relative to the
*indexed root* rather than the *package root*, so a src-layout project yielded:

```
file:    gemseo/src/gemseo/algos/design_space.py
derived: gemseo.src.gemseo.algos.design_space
import:  gemseo.algos.design_space          -> no match
```

Every import-based match therefore fell through to the workaround: accept a
candidate whose derived module contains the imported module as a whole dotted
segment run, in either direction, when that match is unique
(`package_reexport`, confidence `low`). It recovered 6,121 resolutions that should
have been high-confidence `explicit_import` matches — the right answers arrived by
the wrong route, and with the wrong confidence attached.

The fix is the standard one: walk up from each file while `__init__.py` exists,
take the first directory without one as the package root, and derive the module
relative to that. It handles src-layout, flat layout, and multi-project monorepos
— precisely the case this project targets. Package-root detection already existed
in `ProjectScope` for internal/external classification; wiring the node `module`
property to it was the whole change.

Effect on the reference corpus:

| Resolution method | Before | After |
|---|---|---|
| `explicit_import` (high confidence) | **0** | **6,525** |
| `package_reexport` (low confidence) | **6,062** | **25** |
| `global_unique` | 6,244 | 6,244 |
| `same_class` | 1,277 | 1,277 |
| `same_file` | 1,183 | 1,183 |
| `direct_base` | 181 | 181 |
| **Total resolved** | 14,947 | **15,435** |

So the low-confidence fallback all but disappears (6,062 → 25), the high-confidence
rule takes over the work it should always have done, and total resolved rises by
~488 on top of that. Read the totals as samples: at fixed settings this quantity
varies run to run (see the header), so the meaningful result is the *method shift*,
not the last three digits of the total.

## Combined result

All changes merged (Class-aware resolution, package-root module derivation, call
classification with external boundary nodes, deferred FTS + trimmed candidate
fields, fixed 250-op batches), measured on the same corpus:

| Metric | Baseline | Now | Change |
|---|---|---|---|
| Calls resolved | 8,237 | **~15,435** | **+87%** |
| Calls unresolved | 45,320 | **~7,733** | **-83%** |
| Nodes | 15,421 | 15,403 | stable across all 22 runs |
| Total edges | 21,551 | **~36,116** | **+68%** |
| External symbols (new) | -- | 742 | leaf boundary nodes |
| External call edges (new) | -- | 7,381 | "this function calls numpy/fastapi/..." |
| Skipped as unattributable | -- | 18,529 | never written to any stream |
| Wall clock (full build) | 31.1s | **27.6s** | -11% |
| Committing batches | 18.5s | **14.0s** | **-24%** |
| Finalize drain | 10.7s | **8.2s** | **-23%** |

**The `~` on the call counts is not decoration.** The "Now" column is a single
sample. The 22-run block described in the header — measured just before the
module-root fix, so at slightly lower absolute totals — saw resolved calls range
over a ~114-wide band and edges over a ~114-wide band, with repeats of one
configuration differing by up to 39. Nodes were stable at 15,403 every time.
Treat the call and edge figures as "about this much"; only the node count is safe
to assert exactly.

Read-back latency on the finished index, same corpus:

| Operation | Time |
|---|---|
| Reopen (after a clean `close()`) | 0.03s |
| BM25 query | 1-46ms |
| Context assembly | 4.5ms |
| Full in-process open + search + context | 75ms |

The graph gained ~68% more edges while the build got faster -- the pipeline is
doing substantially more useful work in less time. Read the wall-clock figure
conservatively: runs on this corpus have ranged 29.7-33.0s at baseline, so the
improvement is only a little outside run-to-run variance. The robust signals are
the commit and finalize reductions, and the structural drop in wasted references.
The file count also shifted 2,107 -> 2,103 because the hardened exclude patterns
now skip a few vendored directories, so the two runs are not perfectly
like-for-like.

### Still open

- **Resolved-call count is not deterministic.** A ~114-wide band over 22 runs,
  including repeats of one configuration that differed by 39. Nodes are
  stable, so the non-determinism lives in the *resolution* path, not in parsing or
  node writing -- most likely in which candidates a given batch can see when a
  reference is first examined, i.e. arrival order. Not yet root-caused, and it is
  the reason no resolved-call number in this document can be used as a regression
  gate.
- ~7,733 references remain unresolved and internal -- the genuine ambiguity
  backlog (same-named symbols the resolver declines to guess between).

## Correction: the "FTS makes open pathological" finding was wrong

An earlier revision of this document reported that building an index with a
BM25 FTS index made the database take >400s to reopen, that deferring FTS
creation left no index at all, and that search was therefore unusable at
scale. **All of that was an artifact of a missing `backend.close()` in
`perfo/benchmark_ingest_stage_balance.py`.**

Leaving the database open leaves an un-checkpointed WAL; the next process to
open it pays a recovery pass. Measured on the 2,103-file corpus:

| | Benchmark without `close()` | With `close()` |
|---|---|---|
| WAL left behind | 3.2 MB | 0.00 MB |
| Reopen | **>400s** | **0.03s** |
| FTS indexes present | no | yes (both labels) |
| BM25 query | `LatticeUnsupportedError` | 1 ms, 10 hits |

Nine separate reproductions were run against synthetic databases before the
cause was found -- node count, FTS itself, vocabulary size (60k distinct
words, 268MB), term repetition, property indexes, edges, an 8k-record
durable stream, real `search_text` content, and transaction count (1 vs 269)
all reopen in 0.01s. Every one of them was fast because every one of them
closed the database. The bisect that finally isolated it varied the real
pipeline instead, and the giveaway was the `wal=0.0MB` column.

No LatticeDB bug exists here, and no upstream issue was filed. Deferring FTS
index creation works correctly. `LatticeBackend` and `KuzuBackend` now
implement `__enter__`/`__exit__` so closing is automatic rather than
remembered, with a regression test in `tests/test_lattice_batching.py`.

## Open questions

All three questions this document opened with have since been answered. They are
kept, with their answers, because two of them were answered *against* the
hypothesis that motivated them.

- **Of the 45,320 unresolved references, how many name a function that actually
  exists in the graph?** *Answered:* 13.6% (~6,160). The rest are external, stdlib
  or builtin and correctly unresolved. Call-resolution quality did outrank the
  streaming work -- see "Resolution quality" and the module-root fix.
  (`perfo/benchmark_call_resolution_quality.py`)
- **Is `read_stream` paging linear or quadratic in offset?** *Answered: linear.*
  8ms for the first page, 7ms for the last, flat in offset. The early signal that
  suggested otherwise (paging 4,000 records "took over four minutes") was a full
  label scan, not stream paging. See "`read_stream` is not quadratic".
- **Does the commit cost scale with batch size or batch count?** *Answered:
  neither, past a point.* The sweep in `perfo/benchmark_batch_size_sweep.py` traces
  a shallow bowl with its floor at 200-350 ops/batch; larger batches get *worse*,
  not better, which is the opposite of what the "commit is 53.6% of CPU" reasoning
  predicted. That result is what removed `AdaptiveBatchController` rather than
  fixing its tie-break.

Genuinely still open: the non-determinism of the resolved-call count, recorded
under "Still open" above.

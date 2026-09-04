# Configuration

> Status: **implemented**. `src/code_explorer/settings.py` (`Settings`,
> `pydantic-settings`-backed) is the single source of truth for the values
> documented below. All existing callers (`embeddings.py`,
> `graph/backends/lattice_backend.py`, `graph/graph.py`) read from it.

## The gap, stated plainly

Before this module, the numbers that control embedding generation, LatticeDB
write batching, and incremental-reindex file exclusion were plain module-level
constants (`DEFAULT_MODEL`, `_UPSERT_BATCH_SIZE`, `_EMBED_BATCH_SIZE`, an
inline `default_exclude_patterns` list), scattered across three files, each
only changeable by editing source. That's fine for a value nobody needs to
tune. It stops being fine the moment someone's actual setup differs from the
one these defaults were measured against:

- The `_EMBED_BATCH_SIZE = 50` default (see
  [LatticeDB Migration](latticedb-migration.md)) was picked from a benchmark
  against one local Ollama install on one machine. A smaller/slower local
  model, or a remote/shared Ollama instance with its own request-size limits,
  may want a different number — without editing `lattice_backend.py`.
- `ollama_endpoint` defaults to `http://localhost:11434` because that's where
  `ollama serve` listens by default. Anyone running Ollama on another host,
  in a container, or behind a different port needs to override this, not
  patch the source.
- Python-file discovery uses Git's tracked/untracked file list when the target
  is inside a Git repository. This respects every applicable `.gitignore`,
  `.git/info/exclude`, and the user's global Git excludes. Non-Git targets use
  a pruned filesystem walk instead.
- `default_exclude_patterns` adds common exclusions (`.venv`, `.git`,
  `.worktrees`, `__pycache__`, ...) to both discovery paths, including
  `ingest_incremental` (see [LatticeDB Migration, Phase
  3](latticedb-migration.md)). It covers third-party trees as well as build
  artefacts — `site-packages`, `env`, `.tox`, `.eggs`, `node_modules` — because
  a single unexcluded dependency tree is indexed as if it were project code,
  which dominates both index build time and search noise.

## Settings

All fields live on the `Settings` class in `src/code_explorer/settings.py`,
exposed as a ready-to-use singleton: `from code_explorer.settings import
settings`. Every field is overridable via a `CODE_EXPLORER_`-prefixed
environment variable, or a `.env` file in the current working directory
(`pydantic-settings`'s built-in `env_file` support — no extra wiring).

| Setting | Env var | Default | Used by |
|---|---|---|---|
| `ollama_endpoint` | `CODE_EXPLORER_OLLAMA_ENDPOINT` | `http://localhost:11434` | `embeddings.py` — where `embed_text`/`embed_texts` send Ollama requests |
| `embedding_model` | `CODE_EXPLORER_EMBEDDING_MODEL` | `nomic-embed-text` | `embeddings.py` — the Ollama model requested for `--semantic` search |
| `embedding_dimensions` | `CODE_EXPLORER_EMBEDDING_DIMENSIONS` | `768` | `LatticeBackend(enable_vectors=True)` — vector index dimensionality, fixed at DB-creation time (see the migration doc) |
| `embedding_timeout` | `CODE_EXPLORER_EMBEDDING_TIMEOUT` | `30.0` | `embeddings.embed_text`'s HTTP timeout (seconds) |
| `embed_batch_size` | `CODE_EXPLORER_EMBED_BATCH_SIZE` | `50` | `LatticeBackend.build_vector_index` — texts per Ollama `/api/embed` call (see the migration doc's batching measurement) |
| `upsert_batch_size` | `CODE_EXPLORER_UPSERT_BATCH_SIZE` | `250` | Operations accumulated per streaming ingest batch before the writer commits (see the batch-size measurement below) |
| `ingest_write_chunk_size` | `CODE_EXPLORER_INGEST_WRITE_CHUNK_SIZE` | `1000` | Rows per `db.write()` transaction inside `upsert_nodes`/`upsert_edges`; `0` means "commit the whole batch in one transaction" |
| `ingest_batch_bytes` | `CODE_EXPLORER_INGEST_BATCH_BYTES` | `8388608` | Lattice search indexing — secondary byte ceiling for a parsed/write batch |
| `lattice_cache_size_mb` | `CODE_EXPLORER_LATTICE_CACHE_SIZE_MB` | `100` | LatticeDB page-cache ceiling |
| `analysis_workers` | `CODE_EXPLORER_ANALYSIS_WORKERS` | All logical CPUs | CPU-bound parser processes used by Lattice search indexing |
| `analysis_queue_depth` | `CODE_EXPLORER_ANALYSIS_QUEUE_DEPTH` | `256` | Minimum parsed files kept in flight ahead of the consumer; must exceed the files-per-batch the consumer swallows or the worker pool idles during commits |
| `default_exclude_patterns` | `CODE_EXPLORER_DEFAULT_EXCLUDE_PATTERNS` | `["__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov", "dist", "build", ".git", ".worktrees", ".venv", "venv", "env", ".tox", ".eggs", "site-packages", "node_modules"]` | Full and incremental discovery — paths excluded in addition to Git ignore rules |

To override a list-valued setting (`default_exclude_patterns`) via an env
var, pydantic-settings expects a JSON array, e.g.:

```bash
export CODE_EXPLORER_DEFAULT_EXCLUDE_PATTERNS='["__pycache__", ".git", "vendor", "node_modules"]'
```

Or via a `.env` file in the directory you run `code-explorer` from:

```
CODE_EXPLORER_OLLAMA_ENDPOINT=http://gpu-box.internal:11434
CODE_EXPLORER_EMBED_BATCH_SIZE=20
```

### Batch size is a measured constant, not an adaptive target

`upsert_batch_size` used to be the starting point for an `AdaptiveBatchController`
that interleaved doubled targets up to an `ingest_batch_max_size` of 8,000 and held
the smallest one within 5% of peak median throughput. **That controller has been
deleted** (commit `1ccd459`), along with the `adaptive_ingest_batching`,
`ingest_batch_max_size`, `ingest_calibration_batches` and
`ingest_throughput_tolerance` settings that configured it.

The reason is a measurement, not a preference. `perfo/benchmark_batch_size_sweep.py`
on the 2,103-file gemseo corpus (2 runs per point, agreeing to within 0.3s) traces a
shallow bowl whose floor is at **200-350 operations per batch**:

| Target ops/batch | 50 | 100 | 200 | 350 | 500 | 1,000 | 2,000 | 4,000 | 8,000 |
|---|---|---|---|---|---|---|---|---|---|
| Commit | 12.3s | 11.2s | **10.7s** | 11.1s | 11.2s | 12.2s | 12.7s | 13.7s | 13.3s |
| Wall | 25.6s | 24.4s | **23.9s** | 24.1s | 24.4s | 25.2s | 25.8s | 26.9s | 27.0s |

The controller's candidate sizes were `upsert_batch_size` doubling to
`ingest_batch_max_size` — 1,000/2,000/4,000/8,000 — so its entire search space sat
above the knee: it could only ever choose worse than its own default, while paying 12
calibration batches to do so. A fixed constant beats every size it could reach, so
`upsert_batch_size` is now simply `250`, in the middle of the flat floor. Below ~100
per-batch fixed overhead takes over; above ~1,000 the consumer starves more and the
per-batch resolve step works over longer reference lists.

`ingest_write_chunk_size` was split out of `upsert_batch_size` at the same time,
because the two were silently coupled: raising the ingest target also widened every
write transaction, so neither effect could be attributed. Varying it alone is flat
across a 64x range — write-transaction width does not matter here, batch size does.

The configured `ingest_batch_bytes` remains a hard ceiling except for one indivisible
source file whose own records exceed it.

See [Streaming Ingestion: Measured
Performance](streaming-ingestion-performance.md) for the full evidence log.

## Deliberately not built

Per the same "no speculative scope" discipline as the rest of this project:
no YAML/TOML config file format (env vars + `.env` cover the actual need), no
per-repo config-file discovery, no CLI flags to override these (the existing
`--exclude`/`--include` flags on `code-explorer analyze` are a separate,
already-working mechanism for the full-analysis path and are untouched by
this module -- see `analyzer/base_analyzer.py`). If a real need for one of
those shows up, it's a small follow-up on top of this, not a redesign.

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
  3](latticedb-migration.md)).

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
| `upsert_batch_size` | `CODE_EXPLORER_UPSERT_BATCH_SIZE` | `1000` | Initial adaptive operation target and `LatticeBackend` nodes/edges per write transaction |
| `ingest_batch_bytes` | `CODE_EXPLORER_INGEST_BATCH_BYTES` | `8388608` | Lattice search indexing — secondary byte ceiling for a parsed/write batch |
| `adaptive_ingest_batching` | `CODE_EXPLORER_ADAPTIVE_INGEST_BATCHING` | `true` | Interleave measured batch sizes during initial ingestion, then hold the smallest target within 5% of peak median throughput |
| `ingest_batch_max_size` | `CODE_EXPLORER_INGEST_BATCH_MAX_SIZE` | `8000` | Maximum operation target explored by adaptive ingestion; the byte ceiling still applies |
| `ingest_calibration_batches` | `CODE_EXPLORER_INGEST_CALIBRATION_BATCHES` | `3` | Measurements collected for each candidate batch size before selection |
| `ingest_throughput_tolerance` | `CODE_EXPLORER_INGEST_THROUGHPUT_TOLERANCE` | `0.05` | Select the smallest candidate whose median operations/second is within this fraction of the measured peak |
| `lattice_cache_size_mb` | `CODE_EXPLORER_LATTICE_CACHE_SIZE_MB` | `100` | LatticeDB page-cache ceiling |
| `analysis_workers` | `CODE_EXPLORER_ANALYSIS_WORKERS` | All logical CPUs | CPU-bound parser processes used by Lattice search indexing |
| `default_exclude_patterns` | `CODE_EXPLORER_DEFAULT_EXCLUDE_PATTERNS` | `["__pycache__", ".pytest_cache", "htmlcov", "dist", "build", ".git", ".worktrees", ".venv", "venv"]` | Full and incremental discovery — paths excluded in addition to Git ignore rules |

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

Adaptive ingestion does not perform a preliminary scan. It starts with the
configured `upsert_batch_size`, interleaves doubled targets up to
`ingest_batch_max_size`, and feeds each real LatticeDB commit duration back to
the next batch produced by the same iterator. The configured
`ingest_batch_bytes` remains a hard ceiling except for one indivisible source
file whose own records exceed it. Set
`CODE_EXPLORER_ADAPTIVE_INGEST_BATCHING=false` to retain a fixed logical batch
target.

## Deliberately not built

Per the same "no speculative scope" discipline as the rest of this project:
no YAML/TOML config file format (env vars + `.env` cover the actual need), no
per-repo config-file discovery, no CLI flags to override these (the existing
`--exclude`/`--include` flags on `code-explorer analyze` are a separate,
already-working mechanism for the full-analysis path and are untouched by
this module -- see `analyzer/base_analyzer.py`). If a real need for one of
those shows up, it's a small follow-up on top of this, not a redesign.

# Configuration

> Status: **implemented**. `src/code_explorer/settings.py` (`Settings`,
> `pydantic-settings`-backed) is the single source of truth for the values
> documented below. All existing callers (`embeddings.py`,
> `graph/backends/lattice_backend.py`, `graph/graph.py`) read from it; none
> of the defaults changed from what was previously hardcoded.

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
- `default_exclude_patterns` (used by `ingest_incremental`'s file walk, see
  [LatticeDB Migration, Phase 3](latticedb-migration.md)) covers common cases
  (`.venv`, `.git`, `__pycache__`, ...) but a given repo may have its own
  generated/vendored directory that should never be re-hashed on every
  incremental reindex.

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
| `upsert_batch_size` | `CODE_EXPLORER_UPSERT_BATCH_SIZE` | `1000` | `LatticeBackend` — nodes/edges per write transaction during ingestion |
| `default_exclude_patterns` | `CODE_EXPLORER_DEFAULT_EXCLUDE_PATTERNS` | `["__pycache__", ".pytest_cache", "htmlcov", "dist", "build", ".git", ".venv", "venv"]` | `DependencyGraph.ingest_incremental` — directories skipped during the incremental file walk |

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

## Deliberately not built

Per the same "no speculative scope" discipline as the rest of this project:
no YAML/TOML config file format (env vars + `.env` cover the actual need), no
per-repo config-file discovery, no CLI flags to override these (the existing
`--exclude`/`--include` flags on `code-explorer analyze` are a separate,
already-working mechanism for the full-analysis path and are untouched by
this module -- see `analyzer/base_analyzer.py`). If a real need for one of
those shows up, it's a small follow-up on top of this, not a redesign.

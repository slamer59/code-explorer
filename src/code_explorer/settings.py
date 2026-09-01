"""Centralized configuration via pydantic-settings.

Before this module, the values below were hardcoded module-level constants
scattered across embeddings.py, graph/backends/lattice_backend.py, and
graph/graph.py -- no single source of truth, no way to override any of them
without editing source. This module collects them into one Settings class,
overridable via CODE_EXPLORER_-prefixed env vars (or a .env file in the cwd)
without changing any default behavior.

See docs/explanation/configuration.md for what each setting is for and when
you'd actually want to change it.
"""

import os
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CODE_EXPLORER_", env_file=".env")

    # Ollama-backed embedding generation (see embeddings.py).
    ollama_endpoint: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = 768
    embedding_timeout: float = 30.0
    embed_batch_size: int = 50

    # LatticeDB write-transaction chunking (see graph/backends/lattice_backend.py).
    # Operations accumulated per streaming ingest batch before the writer
    # commits. Measured, not guessed: perfo/benchmark_batch_size_sweep.py on
    # the 2,103-file gemseo corpus (2 runs per point, agreeing to within 0.3s)
    # traces a shallow bowl with its floor at 200-350 --
    #   target    50    100    200    350    500  1,000  2,000  4,000  8,000
    #   commit  12.3s  11.2s  10.7s  11.1s  11.2s  12.2s  12.7s  13.7s  13.3s
    #   wall    25.6s  24.4s  23.9s  24.1s  24.4s  25.2s  25.8s  26.9s  27.0s
    # Below ~100 per-batch fixed overhead takes over (999 batches); above
    # ~1,000 the consumer starves more (0.44s at 500 vs 1.4s at 16,000) and
    # the per-batch resolve step works over longer reference lists. 250 sits
    # in the middle of the flat floor. Hypothesis for why the curve is this
    # shape at all: commit cost is dominated by per-row index maintenance,
    # which grouping cannot amortise, so the only thing batch size buys or
    # costs is pipeline overlap -- confirmed by the write-transaction-width
    # sweep in the same script being flat across a 64x range.
    upsert_batch_size: int = 250
    # Rows per db.write() transaction inside upsert_nodes/upsert_edges. This
    # used to be upsert_batch_size itself, which silently coupled two
    # independent knobs: raising the streaming ingest target from 1,000 to
    # 8,000 also widened every write transaction, so neither effect could be
    # attributed. Split out so perfo/benchmark_batch_size_sweep.py can vary one
    # axis at a time. 0 means "no chunking" -- commit the whole batch in one
    # transaction.
    ingest_write_chunk_size: int = 1000
    ingest_batch_bytes: int = 8 * 1024 * 1024
    # AdaptiveBatchController (graph/lattice_streaming.py) is off by default,
    # and should be deleted -- the measurement says it cannot help and does
    # harm. Its candidate sizes are upsert_batch_size doubling up to
    # ingest_batch_max_size, so with the measured optimum at 200-350 its
    # ENTIRE candidate set now sits on the wrong side of the knee: it can only
    # pick a size worse than the default it started from. Even before the
    # default moved, the 1,000-8,000 stretch it explored spans a wall range of
    # 25.2-27.2s, so at a 5% tolerance it was choosing between points it
    # cannot distinguish -- which is why it selected 1,000, then 2,000, then
    # 8,000 on three consecutive runs of the identical corpus. It was reading
    # noise, and paying 12 calibration batches (4 candidates x 3 samples) to
    # do it, on a run that at this batch size is ~338 batches but at the old
    # 8,000 was only 8 -- so calibration never even completed and finish()
    # chose from partial data. A fixed constant beats every size it can pick.
    # Left in place (not deleted) only because lattice_streaming.py is owned
    # by another change in flight; the flag makes it inert meanwhile.
    lattice_cache_size_mb: int = 100

    # Search indexing uses CPU-bound parser processes. Saturate all logical CPUs
    # by default; the environment setting remains available when headroom is
    # preferred.
    analysis_workers: int = os.cpu_count() or 1

    # Minimum number of parsed files kept in flight ahead of the consumer.
    # Must exceed the files-per-batch the consumer swallows, or the worker pool
    # drains during batch assembly and idles through the whole commit (a
    # flat/100%/flat CPU sawtooth). Measured on gemseo: ~66 files per batch at
    # the 2,000-op batch size the adaptive controller picked, against an
    # in-flight window of only 32 (2 x 16 workers). At ~63 KB per pending
    # FileAnalysis this is cheap -- 256 in flight is ~16 MB.
    analysis_queue_depth: int = 256

    # Directories skipped by ingest_incremental's file walk (see graph/graph.py).
    # Third-party trees matter more than build artefacts here: a single
    # unexcluded site-packages or conda env pulls an entire dependency tree
    # into the graph, which is both the dominant ingestion cost and noise in
    # every search result. ".venv"/"venv" alone don't cover the common
    # alternatives -- "env" (conda/virtualenv default), a "site-packages"
    # living outside any recognised env dir, or ".tox"/".eggs" -- so those are
    # listed explicitly rather than assumed to be caught by Git ignore rules.
    default_exclude_patterns: List[str] = [
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        "dist",
        "build",
        ".git",
        ".worktrees",
        ".venv",
        "venv",
        "env",
        ".tox",
        ".eggs",
        "site-packages",
        "node_modules",
    ]


settings = Settings()

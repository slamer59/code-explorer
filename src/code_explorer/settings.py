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
    upsert_batch_size: int = 1000
    # Rows per db.write() transaction inside upsert_nodes/upsert_edges. This
    # used to be upsert_batch_size itself, which silently coupled two
    # independent knobs: raising the streaming ingest target from 1,000 to
    # 8,000 also widened every write transaction, so neither effect could be
    # attributed. Split out so perfo/benchmark_batch_size_sweep.py can vary one
    # axis at a time. 0 means "no chunking" -- commit the whole batch in one
    # transaction.
    ingest_write_chunk_size: int = 1000
    ingest_batch_bytes: int = 8 * 1024 * 1024
    adaptive_ingest_batching: bool = True
    ingest_batch_max_size: int = 8000
    ingest_calibration_batches: int = 3
    ingest_throughput_tolerance: float = 0.05
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

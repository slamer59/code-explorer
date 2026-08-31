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
    ingest_batch_bytes: int = 8 * 1024 * 1024
    adaptive_ingest_batching: bool = True
    ingest_batch_max_size: int = 8000
    ingest_calibration_batches: int = 3
    ingest_throughput_tolerance: float = 0.05
    lattice_cache_size_mb: int = 100

    # Search indexing uses CPU-bound parser processes. Saturate all logical CPUs
    # by default; the environment setting remains available when headroom is
    # preferred. The pending queue is still bounded to twice this worker count.
    analysis_workers: int = os.cpu_count() or 1

    # Directories skipped by ingest_incremental's file walk (see graph/graph.py).
    default_exclude_patterns: List[str] = [
        "__pycache__",
        ".pytest_cache",
        "htmlcov",
        "dist",
        "build",
        ".git",
        ".worktrees",
        ".venv",
        "venv",
    ]


settings = Settings()

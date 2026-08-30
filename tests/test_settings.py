"""Tests for code_explorer.settings (centralized pydantic-settings config).

Kept small (2 tests): defaults match the values previously hardcoded across
embeddings.py/lattice_backend.py/graph.py, and an env var actually overrides
a value -- not just that Settings() instantiates.
"""

from code_explorer.settings import Settings


def test_settings_defaults_match_previous_hardcoded_values():
    s = Settings()
    assert s.ollama_endpoint == "http://localhost:11434"
    assert s.embedding_model == "nomic-embed-text"
    assert s.embedding_dimensions == 768
    assert s.embed_batch_size == 50
    assert s.upsert_batch_size == 1000
    assert "__pycache__" in s.default_exclude_patterns
    assert ".git" in s.default_exclude_patterns


def test_settings_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("CODE_EXPLORER_EMBED_BATCH_SIZE", "5")
    monkeypatch.setenv("CODE_EXPLORER_OLLAMA_ENDPOINT", "http://example.internal:9999")

    s = Settings()

    assert s.embed_batch_size == 5
    assert s.ollama_endpoint == "http://example.internal:9999"

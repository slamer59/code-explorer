"""Embedding provider selection.

The provider is not a tuning knob, it is a choice between two kinds of
computation: a transformer forward pass per text, or a static token->vector
lookup with no forward pass and no context. Measured on 500 real body-mode
search_text rows, that is 76 texts/s against 24,211 -- the difference between
an 8-minute vector build on django and a few seconds of one. See
settings.embedding_provider and docs/explanation/gap-analysis-vs-zvec.md.
"""

import numpy as np
import pytest
from click.testing import CliRunner

from code_explorer import embeddings
from code_explorer.cli import cli
from code_explorer.settings import settings


@pytest.fixture
def restore_settings():
    saved = (settings.embedding_provider, settings.embedding_model,
             settings.model2vec_model)
    yield
    (settings.embedding_provider, settings.embedding_model,
     settings.model2vec_model) = saved


def test_dimensions_follow_the_provider(restore_settings):
    """A vector index is dimensioned when built, so this must not be cached.

    DEFAULT_DIMENSIONS is evaluated at import time and was used as a default
    argument, so switching providers built a 768-wide index for a 512-wide
    model instead of refusing.
    """
    settings.embedding_provider = "ollama"
    assert embeddings.active_dimensions() == settings.embedding_dimensions

    settings.embedding_provider = "model2vec"
    assert embeddings.active_dimensions() == settings.model2vec_dimensions


def test_backend_resolves_dimensions_at_construction(restore_settings, temp_dir):
    from code_explorer.graph.backends.sqlite_backend import SqliteBackend

    settings.embedding_provider = "model2vec"
    assert SqliteBackend(temp_dir / "g.sqlite").vector_dimensions == 512

    settings.embedding_provider = "ollama"
    assert SqliteBackend(temp_dir / "g.sqlite").vector_dimensions == 768


def test_static_provider_is_dispatched_without_touching_ollama(
    restore_settings, monkeypatch
):
    """The four backend call sites must not know which provider is configured."""
    settings.embedding_provider = "model2vec"

    def explode(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("the Ollama path was taken for a static provider")

    monkeypatch.setattr(embeddings, "_call_embed_api", explode)
    monkeypatch.setattr(
        embeddings, "_embed_static",
        lambda texts, model_id: [np.zeros(512, dtype=np.float32) for _ in texts],
    )

    vectors = embeddings.embed_texts(["def f(): pass", "def g(): pass"])

    assert len(vectors) == 2
    assert vectors[0].shape == (512,)


def test_empty_input_never_calls_a_provider(restore_settings, monkeypatch):
    settings.embedding_provider = "model2vec"
    monkeypatch.setattr(embeddings, "_embed_static", lambda *a: 1 / 0)

    assert embeddings.embed_texts([]) == []


@pytest.mark.parametrize("spec", ["nomic-embed-text", "torch/foo", "ollama/", ""])
def test_cli_rejects_a_malformed_embedding_spec(spec):
    result = CliRunner().invoke(cli, ["search", "q", ".", "--embedding", spec])

    assert result.exit_code != 0
    assert "PROVIDER/MODEL" in result.output


def test_cli_sets_the_provider(restore_settings, tmp_path, monkeypatch):
    """model2vec ids contain a slash themselves, so only the first splits."""
    # Via sys.modules: code_explorer/__init__.py does `from .cli import cli`,
    # which shadows the submodule attribute with the Click Group, so neither
    # the string form nor `import code_explorer.cli as m` reaches the module.
    import sys

    cli_module = sys.modules["code_explorer.cli"]

    monkeypatch.setattr(
        cli_module, "_search_index_paths",
        lambda *a, **k: (_ for _ in ()).throw(SystemExit(0)),
    )
    CliRunner().invoke(
        cli, ["search", "q", str(tmp_path),
              "--embedding", "model2vec/minishlab/potion-retrieval-32m"]
    )

    assert settings.embedding_provider == "model2vec"
    assert settings.model2vec_model == "minishlab/potion-retrieval-32m"

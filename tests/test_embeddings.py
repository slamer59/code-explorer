"""Tests for embed_texts (batched Ollama embedding calls).

Requires a local Ollama server with nomic-embed-text pulled -- not mocked,
matching this session's established pattern for embedding-backed tests.
"""

from code_explorer.embeddings import embed_texts


def test_embed_texts_returns_one_vector_per_input_in_order():
    vectors = embed_texts(["refresh an oauth token", "add two numbers"])

    assert len(vectors) == 2
    assert vectors[0].shape == (768,)
    assert vectors[1].shape == (768,)
    # Order must be preserved -- callers zip these back onto node ids by
    # position (see LatticeBackend.build_vector_index).
    assert not (vectors[0] == vectors[1]).all()


def test_embed_texts_empty_list_returns_empty_list():
    assert embed_texts([]) == []

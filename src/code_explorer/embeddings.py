"""Local embedding generation via Ollama.

Deliberately does NOT use latticedb.embedding.EmbeddingClient: that client
(a ctypes wrapper around LatticeDB's native HTTP embedding code) was found to
raise an opaque "LatticeError: Generic error" on every call in testing, even
though the exact same Ollama endpoint responds correctly to a plain HTTP
request. latticedb.hash_embed is also unsuitable -- it's deterministic
hashing, not a semantic embedding, so it can't support conceptual search.
This module calls Ollama's HTTP API directly instead (stdlib urllib, no new
dependency), which was confirmed working.
"""

import json
import urllib.error
import urllib.request
from typing import List, Optional

import numpy as np

from code_explorer.settings import settings

# Kept as module-level names (not just settings.X) since other modules
# import these directly -- see graph/backends/lattice_backend.py.
DEFAULT_MODEL = settings.embedding_model
#: Kept for backwards compatibility. Prefer active_dimensions(): this is
#: evaluated at import time, so it cannot follow a provider switch.
DEFAULT_DIMENSIONS = settings.embedding_dimensions


def active_dimensions() -> int:
    """Vector width of the currently configured provider.

    A vector index is dimensioned when it is built, so this has to be read at
    build time rather than baked into a default argument at import time --
    switching providers otherwise silently keeps the previous width and the
    index is built wrong rather than refused.
    """
    if settings.embedding_provider == "model2vec":
        return settings.model2vec_dimensions
    return settings.embedding_dimensions
DEFAULT_ENDPOINT = settings.ollama_endpoint


def _call_embed_api(
    inputs: List[str], model: str, endpoint: str, timeout: float
) -> List[np.ndarray]:
    body = json.dumps({"model": model, "input": inputs}).encode("utf-8")
    req = urllib.request.Request(
        f"{endpoint}/api/embed",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Ollama not reachable at {endpoint} -- is it running? (ollama serve)"
        ) from e

    if "error" in data:
        raise RuntimeError(
            f"Ollama embedding request failed: {data['error']} -- "
            f"if the model is missing, run: ollama pull {model}"
        )

    embeddings = data.get("embeddings")
    if not embeddings:
        raise RuntimeError(f"Ollama returned no embedding for model {model!r}: {data}")

    return [np.array(e, dtype=np.float32) for e in embeddings]


# --------------------------------------------------------------------------
# Model2Vec: static embeddings.
#
# A different kind of computation from a transformer, not a smaller one --
# each token is looked up in a table and the results are mean-pooled, so
# there is no forward pass and no context. That is why it is ~300x faster
# per text and why it can be wrong in ways a contextual model is not. Loaded
# lazily and cached process-wide: the load is ~12s and dwarfs the encoding.
# --------------------------------------------------------------------------

_static_model = None
_static_model_id: Optional[str] = None


def _load_static_model(model_id: str):
    global _static_model, _static_model_id
    if _static_model is not None and _static_model_id == model_id:
        return _static_model
    try:
        from model2vec import StaticModel
    except ImportError as exc:  # pragma: no cover - depends on the extra
        raise RuntimeError(
            "embedding_provider is 'model2vec' but the model2vec package is "
            "not installed. Install it with: pip install 'code-explorer[model2vec]'"
        ) from exc
    _static_model = StaticModel.from_pretrained(model_id)
    _static_model_id = model_id
    return _static_model


def _embed_static(texts: List[str], model_id: str) -> List[np.ndarray]:
    vectors = _load_static_model(model_id).encode(texts)
    return [np.asarray(v, dtype=np.float32) for v in vectors]


def embed_text(
    text: str,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = settings.embedding_timeout,
) -> np.ndarray:
    """Generate a semantic embedding for `text` via the configured provider.

    Returns:
        A 1-D float32 numpy array (768 dimensions for the default model).

    Raises:
        RuntimeError: Ollama isn't reachable, or the model isn't pulled.
    """
    return embed_texts([text], model=model, endpoint=endpoint, timeout=timeout)[0]


def embed_texts(
    texts: List[str],
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = 60.0,
) -> List[np.ndarray]:
    """Generate embeddings for multiple texts through the configured provider.

    With embedding_provider="model2vec" this is an in-process static lookup
    and `model`/`endpoint`/`timeout` are ignored; the notes below describe
    the Ollama path.

    Ollama's /api/embed accepts a list `input` and returns embeddings in
    the same order -- measured ~7x faster per item than one embed_text()
    call per text (37ms/item at batch=1 down to ~5.2ms/item at batch=50+,
    see perfo/benchmark_embed_batching.py), since each call pays a fixed
    HTTP/model-load overhead regardless of batch size. Callers (see
    LatticeBackend.build_vector_index) chunk larger inputs into batches of
    a few dozen rather than passing everything at once, mainly to keep
    progress reporting granular and bound a single request's payload/
    timeout risk, not because larger batches stop helping.

    Returns:
        Empty list for an empty input list (no network call made).
    """
    if not texts:
        return []
    # Dispatch here rather than at every call site: the four callers in the
    # two backends should not know which kind of model is configured.
    if settings.embedding_provider == "model2vec":
        return _embed_static(texts, settings.model2vec_model)
    return _call_embed_api(texts, model, endpoint, timeout)

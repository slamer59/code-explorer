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
from typing import List

import numpy as np

from code_explorer.settings import settings

# Kept as module-level names (not just settings.X) since other modules
# import these directly -- see graph/backends/lattice_backend.py.
DEFAULT_MODEL = settings.embedding_model
DEFAULT_DIMENSIONS = settings.embedding_dimensions
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


def embed_text(
    text: str,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = settings.embedding_timeout,
) -> np.ndarray:
    """Generate a semantic embedding for `text` via a local Ollama server.

    Returns:
        A 1-D float32 numpy array (768 dimensions for the default model).

    Raises:
        RuntimeError: Ollama isn't reachable, or the model isn't pulled.
    """
    return _call_embed_api([text], model, endpoint, timeout)[0]


def embed_texts(
    texts: List[str],
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = 60.0,
) -> List[np.ndarray]:
    """Generate embeddings for multiple texts in one Ollama HTTP call.

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
    return _call_embed_api(texts, model, endpoint, timeout)

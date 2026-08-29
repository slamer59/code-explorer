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

import numpy as np

DEFAULT_MODEL = "nomic-embed-text"
DEFAULT_DIMENSIONS = 768
DEFAULT_ENDPOINT = "http://localhost:11434"


def embed_text(
    text: str,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = 30.0,
) -> np.ndarray:
    """Generate a semantic embedding for `text` via a local Ollama server.

    Returns:
        A 1-D float32 numpy array (768 dimensions for the default model).

    Raises:
        RuntimeError: Ollama isn't reachable, or the model isn't pulled.
    """
    body = json.dumps({"model": model, "input": text}).encode("utf-8")
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

    return np.array(embeddings[0], dtype=np.float32)

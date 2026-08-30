#!/usr/bin/env python3
"""Compare per-node vs. batched Ollama embedding calls.

Run locally (requires a local Ollama server with nomic-embed-text pulled):

    uv run --python 3.12 --extra dev python perfo/benchmark_embed_batching.py

Backs the batch-size choice in LatticeBackend._EMBED_BATCH_SIZE (50): cost
per item flattens around batch=50, so going bigger buys little while
increasing single-request payload/timeout risk.
"""

import time

from rich.console import Console
from rich.table import Table

from code_explorer.embeddings import embed_text, embed_texts

console = Console()


def main() -> None:
    texts = [f"function number {i} does something with data and returns a result" for i in range(200)]

    table = Table(title="Embedding batch size vs. per-item cost")
    table.add_column("Batch size", justify="right")
    table.add_column("Total time (s)", justify="right")
    table.add_column("Per-item (ms)", justify="right")

    console.print("[cyan]Single-call baseline (batch=1, via embed_text)[/cyan]")
    t0 = time.time()
    for text in texts[:20]:
        embed_text(text)
    elapsed = time.time() - t0
    table.add_row("1 (embed_text x20)", f"{elapsed:.3f}", f"{elapsed / 20 * 1000:.2f}")

    for batch_size in (10, 50, 100, 200):
        batch = texts[:batch_size]
        t0 = time.time()
        embed_texts(batch)
        elapsed = time.time() - t0
        table.add_row(str(batch_size), f"{elapsed:.3f}", f"{elapsed / batch_size * 1000:.2f}")

    console.print(table)


if __name__ == "__main__":
    main()

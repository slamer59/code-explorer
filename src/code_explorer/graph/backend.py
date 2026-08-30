"""Backend-neutral graph storage interface.

Phase 0 of the LatticeDB migration (see docs/explanation/latticedb-migration.md).
search_text (Phase 4, BM25) is now part of the interface, but it is a
LatticeDB-only capability for now -- Kuzu has no full-text search engine, so
KuzuBackend.search_text() raises NotImplementedError rather than silently
returning nothing. This is a deliberate asymmetry, not an oversight: see
docs/explanation/latticedb-migration.md's "Implementation Status" section,
which explicitly deprioritizes Kuzu feature parity in favor of shipping
LatticeDB's search capabilities first. search_vector (Phase 5) is now part
of the interface too: also LatticeDB-only, backed by local Ollama
embeddings (see embeddings.py) rather than LatticeDB's own native embedding
client (found broken -- opaque "Generic error" -- in testing).
"""

from typing import Any, Dict, Iterable, List, Optional, Protocol

from code_explorer.graph.records import EdgeRecord, NodeRecord, SearchResult


class CodeGraphBackend(Protocol):
    """A pluggable storage/query backend for the dependency graph."""

    def open(self) -> None:
        """Open the underlying database connection."""
        ...

    def close(self) -> None:
        """Close the underlying database connection."""
        ...

    def initialize_schema(self) -> None:
        """Create node/edge tables if they don't already exist."""
        ...

    def upsert_nodes(self, nodes: Iterable[NodeRecord]) -> None:
        """Insert or update nodes, matched by their canonical primary key."""
        ...

    def upsert_edges(self, edges: Iterable[EdgeRecord]) -> None:
        """Insert or update edges between existing nodes."""
        ...

    def delete_file(self, file_key: str) -> None:
        """Delete all nodes/edges owned by a file, for incremental re-indexing."""
        ...

    def clear_all(self) -> None:
        """Delete every node and edge, for a full re-index from scratch."""
        ...

    def query(
        self, statement: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Escape hatch for existing raw-Cypher call sites during the transition."""
        ...

    def search_text(
        self,
        query: str,
        node_types: Optional[List[str]] = None,
        limit: int = 10,
        fuzzy: bool = False,
    ) -> List[SearchResult]:
        """BM25 (or, with fuzzy=True, typo-tolerant) lexical search over
        indexed node text (currently Function/Class search_text).

        LatticeDB-only: KuzuBackend has no full-text search engine and raises
        NotImplementedError rather than silently returning [].
        """
        ...

    def search_vector(
        self,
        query_text: str,
        node_types: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[SearchResult]:
        """Semantic (vector similarity) search: embeds query_text locally
        (see embeddings.py) and finds the nearest indexed node vectors.

        `score` on the returned SearchResult is a distance (lower = more
        similar), unlike search_text's BM25 relevance score (higher = more
        relevant) -- the two are not comparable.

        LatticeDB-only, and only works on a backend opened with
        enable_vectors=True whose vector index has actually been populated
        (see LatticeBackend.build_vector_index). KuzuBackend has no vector
        search and raises NotImplementedError.
        """
        ...

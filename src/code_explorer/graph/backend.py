"""Backend-neutral graph storage interface.

Phase 0 of the LatticeDB migration (see docs/explanation/latticedb-migration.md).
search_text (Phase 4, BM25) is now part of the interface, but it is a
LatticeDB-only capability for now -- Kuzu has no full-text search engine, so
KuzuBackend.search_text() raises NotImplementedError rather than silently
returning nothing. This is a deliberate asymmetry, not an oversight: see
docs/explanation/latticedb-migration.md's "Implementation Status" section,
which explicitly deprioritizes Kuzu feature parity in favor of shipping
LatticeDB's search capabilities first. search_vector is still not part of
this interface -- no implementation exists yet.
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
        indexed node text (currently Function/Class source_code).

        LatticeDB-only: KuzuBackend has no full-text search engine and raises
        NotImplementedError rather than silently returning [].
        """
        ...

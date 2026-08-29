"""Backend-neutral graph storage interface.

Phase 0 of the LatticeDB migration (see docs/explanation/latticedb-migration.md).
Scoped to what DependencyGraph needs today; search_text/search_vector are
deliberately not included yet -- no implementation of either exists in the
codebase, and the migration spec places search in a later phase (Phase 4+).
"""

from typing import Any, Dict, Iterable, List, Optional, Protocol

from code_explorer.graph.records import EdgeRecord, NodeRecord


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

    def query(
        self, statement: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Escape hatch for existing raw-Cypher call sites during the transition."""
        ...

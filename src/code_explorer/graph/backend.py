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

from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Tuple

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

    def upsert_nodes(
        self,
        nodes: Iterable[NodeRecord],
        on_progress: Optional[Callable[[], None]] = None,
        assume_new: bool = False,
    ) -> Dict[Tuple[str, str], int]:
        """Insert or update nodes, matched by their canonical primary key.

        on_progress, if given, is called once per node processed -- there's
        no batching within a single write (writes are chunked into ~1000-item
        transactions, but there's no cross-node bulk-insert primitive), so on
        a large codebase this is the only way to know it's still making
        progress rather than hung. See cli.py's `search` command for the
        intended caller pattern (rich.progress.Progress.advance).

        assume_new: skip the existing-node lookup and always create, when the
        caller knows this backend has no pre-existing data for these nodes
        (e.g. a fresh index build). A modest win in practice for the node
        phase alone (see perfo/benchmark_ingest_speed.py) -- never wrong when
        the assumption holds, but don't expect a dramatic speedup from this
        alone; the bigger lever is upsert_edges' node_id_map. Passing True
        against a backend that already has some of these nodes produces
        duplicates, not updates; only set it when you're sure.

        Returns a {(node_type, canonical_id): internal_id} map for every
        node processed -- pass it to upsert_edges as node_id_map to resolve
        edge endpoints from memory instead of a per-endpoint DB lookup.
        KuzuBackend returns {} (its MERGE-based upsert has no equivalent
        internal-id concept to expose, and doesn't need this optimization).
        """
        ...

    def upsert_edges(
        self,
        edges: Iterable[EdgeRecord],
        on_progress: Optional[Callable[[], None]] = None,
        node_id_map: Optional[Dict[Tuple[str, str], int]] = None,
    ) -> None:
        """Insert or update edges between existing nodes. on_progress: see
        upsert_nodes.

        node_id_map: from a prior upsert_nodes() call in the same ingest,
        used to resolve (node_type, canonical_id) -> internal_id from memory
        instead of a DB lookup per endpoint -- the real win on a large
        codebase, where edges typically outnumber nodes by an order of
        magnitude. Falls back to a DB lookup for any endpoint not covered by
        the map (e.g. an edge referencing a node from an earlier ingest, not
        this one). Ignored by KuzuBackend (no internal-id concept there).
        """
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

    def get_call_edges_with_lines(
        self, function_canonical_id: str
    ) -> Tuple[
        List[Tuple[str, str, int, int, int]], List[Tuple[str, str, int, int, int]]
    ]:
        """Return (callers, callees) for the Function with this canonical id,
        each a list of (file, name, call_line, start_line, end_line) tuples.

        Deliberately NOT implemented as one shared Cypher query for both
        backends -- each backend uses whatever primitive is fastest for it.
        Confirmed via direct measurement on a real 338K-edge graph (see
        docs/explanation/latticedb-migration.md's Performance Findings):
        LatticeDB's Cypher `MATCH (a)-[:CALLS]->(b)` compiles to a
        LabelScan-then-Expand plan (confirmed from LatticeDB's own
        architecture docs) that measured ~15.3s for one node's 27 callers,
        while its imperative get_incoming_edges/get_outgoing_edges +
        get_property API (which uses the storage layer's own edge-ID index
        directly, bypassing the Cypher planner) measured ~2ms for the same
        data -- roughly 7,500x faster for this exact pattern. Kuzu's Cypher
        has no equivalent slowdown (confirmed: 0.52ms for the same shape of
        query on the small test repo), so KuzuBackend just uses Cypher.
        """
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

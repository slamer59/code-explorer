"""LatticeDB implementation of CodeGraphBackend.

Phase 1 of the LatticeDB migration (see docs/explanation/latticedb-migration.md):
the first real, non-Kuzu CodeGraphBackend, verified against latticedb==0.15.0's
actual Python API (confirmed interactively before writing this file -- see
scratchpad smoke scripts referenced in the implementation session).

Key differences from KuzuBackend that shape this implementation:

- LatticeDB nodes/edges are schema-less: a node is (internal int id, labels,
  properties dict). There is no CREATE TABLE / typed-column DDL, so
  initialize_schema() only creates property indexes (for upsert-by-canonical-id
  lookups) instead of tables.
- Our canonical NodeRecord.id (e.g. 'fn_a1b2c3d4e5f6', or a File's relative
  path) is not the same as LatticeDB's internal node id. upsert_nodes looks up
  existing nodes by the same primary-key property Kuzu uses (see
  NODE_PRIMARY_KEY in kuzu_backend.py) via find_nodes_by_label_property, and
  creates a new node only if none is found.
- delete_node does NOT cascade-delete attached edges (confirmed empirically:
  a dangling Edge remains referencing a deleted node id). delete_file must
  therefore delete a node's incoming/outgoing edges explicitly before deleting
  the node itself -- there is no DETACH DELETE equivalent.
"""

from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import latticedb

from code_explorer.embeddings import DEFAULT_DIMENSIONS, DEFAULT_MODEL, embed_text
from code_explorer.graph.backends.kuzu_backend import (
    EDGE_ENDPOINT_TYPES,
    FILE_SCOPED_NODE_TYPES,
    NODE_PRIMARY_KEY,
)
from code_explorer.graph.records import EdgeRecord, NodeRecord, SearchResult

# Node types + text property indexed for BM25/fuzzy search, and embedded for
# vector search (same field, same scope -- one text representation, not two).
# search_text is a compact, indexing-time derived field (qualified-ish name +
# signature + docstring first line) -- not full source_code, which is only
# stored when ingest_results(include_source=True) is used. See
# docs/explanation/source-of-truth-and-search-representations.md.
SEARCHABLE_TEXT_FIELDS: Dict[str, str] = {
    "Function": "search_text",
    "Class": "search_text",
}

# One db.write() transaction per this many items, not one giant transaction
# for the whole batch. Matches LatticeDB's own documented guidance (its
# performance-tuning guide explicitly calls out "one giant transaction for
# millions of items" as the pattern to avoid, recommending ~1000-item
# chunks) -- confirmed via context7 before picking this number, not guessed.
_UPSERT_BATCH_SIZE = 1000


def _chunked(items: List[Any], size: int) -> Iterable[List[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class LatticeBackend:
    """CodeGraphBackend implementation backed by LatticeDB."""

    def __init__(
        self,
        db_path: Path,
        read_only: bool = False,
        enable_vectors: bool = False,
        vector_dimensions: int = DEFAULT_DIMENSIONS,
    ):
        """
        Args:
            enable_vectors: Opt-in -- vectors have real memory/storage cost
                (see the migration spec's risk register), so plain
                structural/BM25 usage doesn't pay for them. Fixed at
                database-creation time; can't be turned on for an existing
                database that was created without it.
            vector_dimensions: Must match the embedding model used with this
                database (768 for the default nomic-embed-text). Also fixed
                at database-creation time.
        """
        self.db_path = db_path
        self.read_only = read_only
        self.enable_vectors = enable_vectors
        self.vector_dimensions = vector_dimensions
        self.db: Optional[latticedb.Database] = None

    def open(self) -> None:
        if not self.read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = latticedb.Database(
            self.db_path,
            create=not self.read_only,
            read_only=self.read_only,
            enable_vectors=self.enable_vectors,
            vector_dimensions=self.vector_dimensions,
        )
        self.db.open()

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
        self.db = None

    def _ensure_node_property_index(self, label: str, prop: str) -> None:
        try:
            self.db.create_node_property_index(label, prop)
        except latticedb.LatticeAlreadyExistsError:
            pass

    def initialize_schema(self) -> None:
        if self.read_only:
            return
        # find_nodes_by_label_property requires a property index to exist for
        # the (label, property) pair -- confirmed empirically, it raises
        # LatticeUnsupportedError otherwise rather than falling back to a scan.
        for label, pk in NODE_PRIMARY_KEY.items():
            self._ensure_node_property_index(label, pk)
        # delete_file looks nodes up by their owning file's path via the
        # 'file' property, which also needs an index.
        for label in FILE_SCOPED_NODE_TYPES:
            self._ensure_node_property_index(label, "file")
        for label, prop in SEARCHABLE_TEXT_FIELDS.items():
            if not self.db.has_node_fts_index(label, prop):
                self.db.create_node_fts_index(label, prop)

    def detect_schema_version(self) -> str:
        """No versioned schema in LatticeDB (schema-less); always current."""
        return "v2"

    def _find_node_id(
        self, txn: "latticedb.Transaction", node_type: str, pk_value: Any
    ) -> Optional[int]:
        pk = NODE_PRIMARY_KEY[node_type]
        matches = txn.find_nodes_by_label_property(node_type, pk, pk_value, limit=1)
        return matches[0] if matches else None

    def upsert_nodes(
        self,
        nodes: Iterable[NodeRecord],
        on_progress: Optional[Callable[[], None]] = None,
        assume_new: bool = False,
    ) -> Dict[Tuple[str, str], int]:
        """
        assume_new: skip the existing-node lookup and always create --
        correct (only a modest win in practice -- see
        perfo/benchmark_ingest_speed.py -- but never wrong) only when the
        caller knows this backend has no pre-existing data for these nodes,
        e.g. a fresh index build. Wrong data results if this is set True
        against a backend that already has some of these nodes: they'd be
        duplicated instead of updated.

        Returns a {(node_type, canonical_id): internal_id} map for every
        node processed in this call -- pass it to upsert_edges as
        node_id_map to resolve edge endpoints from memory instead of a DB
        lookup per endpoint. This is the real win: on a large codebase,
        edges typically outnumber nodes by an order of magnitude (e.g.
        gemseo: 15K nodes, 338K resolved calls), so avoiding a lookup per
        edge endpoint matters far more than avoiding one per node.
        """
        node_list = list(nodes)
        id_map: Dict[Tuple[str, str], int] = {}
        for batch in _chunked(node_list, _UPSERT_BATCH_SIZE):
            with self.db.write() as txn:
                for node in batch:
                    pk = NODE_PRIMARY_KEY.get(node.type)
                    if pk is None:
                        raise ValueError(f"Unknown node type for upsert: {node.type}")
                    pk_value = node.properties.get(pk, node.id)
                    if assume_new:
                        created = txn.create_node(
                            labels=[node.type], properties=dict(node.properties)
                        )
                        internal_id = created.id
                    else:
                        existing_id = self._find_node_id(txn, node.type, pk_value)
                        if existing_id is not None:
                            for key, value in node.properties.items():
                                txn.set_property(existing_id, key, value)
                            internal_id = existing_id
                        else:
                            created = txn.create_node(
                                labels=[node.type], properties=dict(node.properties)
                            )
                            internal_id = created.id
                    id_map[(node.type, pk_value)] = internal_id
                    if on_progress is not None:
                        on_progress()
                txn.commit()
        return id_map

    def upsert_edges(
        self,
        edges: Iterable[EdgeRecord],
        on_progress: Optional[Callable[[], None]] = None,
        node_id_map: Optional[Dict[Tuple[str, str], int]] = None,
    ) -> None:
        # No assume_new fast path here: an edge's endpoints must always be
        # resolved from canonical id -> internal id. node_id_map (from a
        # prior upsert_nodes call) resolves that from memory when it covers
        # the edge; falls back to a DB lookup only for endpoints outside the
        # current batch (e.g. incremental ingestion referencing older data).
        edge_list = list(edges)
        node_id_map = node_id_map or {}
        for batch in _chunked(edge_list, _UPSERT_BATCH_SIZE):
            with self.db.write() as txn:
                for edge in batch:
                    endpoints = EDGE_ENDPOINT_TYPES.get(edge.type)
                    if endpoints is None:
                        raise ValueError(f"Unknown edge type for upsert: {edge.type}")
                    src_type, dst_type = endpoints
                    src_id = node_id_map.get((src_type, edge.src_id))
                    if src_id is None:
                        src_id = self._find_node_id(txn, src_type, edge.src_id)
                    dst_id = node_id_map.get((dst_type, edge.dst_id))
                    if dst_id is None:
                        dst_id = self._find_node_id(txn, dst_type, edge.dst_id)
                    if src_id is None or dst_id is None:
                        raise ValueError(
                            f"Cannot create {edge.type} edge: endpoint node not found "
                            f"(src={edge.src_id!r} found={src_id is not None}, "
                            f"dst={edge.dst_id!r} found={dst_id is not None})"
                        )
                    txn.create_edge(
                        src_id, dst_id, edge.type, properties=dict(edge.properties)
                    )
                    if on_progress is not None:
                        on_progress()
                txn.commit()

    def delete_file(self, file_key: str) -> None:
        with self.db.write() as txn:
            node_ids: List[int] = []
            for node_type in FILE_SCOPED_NODE_TYPES:
                node_ids.extend(
                    txn.find_nodes_by_label_property(
                        node_type, "file", file_key, limit=100_000
                    )
                )
            file_id = self._find_node_id(txn, "File", file_key)
            if file_id is not None:
                node_ids.append(file_id)

            for node_id in node_ids:
                for edge in txn.get_outgoing_edges(node_id):
                    txn.delete_edge(edge.source_id, edge.target_id, edge.edge_type)
                for edge in txn.get_incoming_edges(node_id):
                    txn.delete_edge(edge.source_id, edge.target_id, edge.edge_type)
            for node_id in node_ids:
                txn.delete_node(node_id)
            txn.commit()

    def clear_all(self) -> None:
        for node_type in NODE_PRIMARY_KEY:
            self.query(f"MATCH (n:{node_type}) DETACH DELETE n")

    def query(
        self, statement: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        return self.db.query(statement, params or {}).fetchall()

    def get_call_edges_with_lines(
        self, function_canonical_id: str
    ) -> Tuple[
        List[Tuple[str, str, int, int, int]], List[Tuple[str, str, int, int, int]]
    ]:
        """Imperative-API implementation -- see CodeGraphBackend's docstring
        for why this exists instead of a Cypher MATCH (measured ~7,500x
        faster on a real 338K-edge graph). get_incoming_edges/
        get_outgoing_edges use LatticeDB's storage-layer edge-ID index
        directly; get_property likewise looks up by internal id directly --
        neither goes through the Cypher query planner.
        """
        with self.db.read() as txn:
            internal_id = self._find_node_id(txn, "Function", function_canonical_id)
            if internal_id is None:
                return [], []

            def _resolve(edges, other_id_attr):
                out = []
                for edge in edges:
                    if edge.edge_type != "CALLS":
                        continue
                    other_id = getattr(edge, other_id_attr)
                    file = txn.get_property(other_id, "file")
                    name = txn.get_property(other_id, "name")
                    start_line = txn.get_property(other_id, "start_line")
                    end_line = txn.get_property(other_id, "end_line")
                    # edge.properties is unreliably empty here (same
                    # lazy-load quirk already found on Node.properties) --
                    # get_edge_property looks it up directly and works.
                    call_line = txn.get_edge_property(edge.id, "call_line")
                    out.append((file, name, call_line, start_line, end_line))
                return out

            callers = _resolve(txn.get_incoming_edges(internal_id), "source_id")
            callees = _resolve(txn.get_outgoing_edges(internal_id), "target_id")
            return callers, callees

    def search_text(
        self,
        query: str,
        node_types: Optional[List[str]] = None,
        limit: int = 10,
        fuzzy: bool = False,
    ) -> List[SearchResult]:
        types = node_types if node_types is not None else list(SEARCHABLE_TEXT_FIELDS)
        raw_hits: List[tuple] = []  # (node_type, node_id, score)
        for node_type in types:
            prop = SEARCHABLE_TEXT_FIELDS.get(node_type)
            if prop is None:
                continue
            search_fn = self.db.fts_search_fuzzy if fuzzy else self.db.fts_search
            kwargs = {"limit": limit, "max_distance": 2} if fuzzy else {"limit": limit}
            for hit in search_fn(node_type, prop, query, **kwargs):
                raw_hits.append((node_type, hit.node_id, hit.score))

        # Confirmed empirically: fts_search_fuzzy reports score=0.0 (not a
        # real relevance score), unlike fts_search's BM25 score. Sorting by
        # score is a no-op in fuzzy mode (all 0.0, order preserved) and
        # meaningful in exact mode -- harmless either way, but don't assume
        # fuzzy results are ranked by relevance.
        raw_hits.sort(key=lambda h: h[2], reverse=True)
        raw_hits = raw_hits[:limit]

        results: List[SearchResult] = []
        with self.db.read() as txn:
            for node_type, node_id, score in raw_hits:
                pk = NODE_PRIMARY_KEY[node_type]
                results.append(
                    SearchResult(
                        node_id=txn.get_property(node_id, pk),
                        node_type=node_type,
                        name=txn.get_property(node_id, "name") or "",
                        file=txn.get_property(node_id, "file") or "",
                        score=score,
                    )
                )
        return results

    def build_vector_index(
        self,
        node_types: Optional[List[str]] = None,
        model: str = DEFAULT_MODEL,
        on_progress: Optional[Callable[[], None]] = None,
    ) -> int:
        """Embed and store a vector for each existing node of the given
        types, using their SEARCHABLE_TEXT_FIELDS text property.

        A separate step from ingestion on purpose (see the migration spec,
        Section 10: "Do not generate embeddings during AST parsing" -- select
        entities from the already-built graph, then embed). One Ollama HTTP
        call per node -- slow, not batched/parallelized; fine for now.

        Returns:
            Number of nodes embedded.

        Raises:
            RuntimeError: This backend wasn't opened with enable_vectors=True.
        """
        if not self.enable_vectors:
            raise RuntimeError(
                "build_vector_index requires a LatticeBackend opened with "
                "enable_vectors=True (vector_dimensions is fixed at "
                "database-creation time and can't be enabled afterward)."
            )
        types = node_types if node_types is not None else list(SEARCHABLE_TEXT_FIELDS)
        count = 0
        for node_type in types:
            prop = SEARCHABLE_TEXT_FIELDS.get(node_type)
            if prop is None:
                continue
            node_ids = self.db.get_nodes_by_label(node_type)
            # Chunked rather than one transaction for the whole type: each
            # iteration makes a slow external Ollama HTTP call (embed_text)
            # while holding the transaction open -- chunking bounds how long
            # a single write transaction sits open waiting on the network.
            for batch in _chunked(node_ids, _UPSERT_BATCH_SIZE):
                with self.db.write() as txn:
                    for node_id in batch:
                        text = txn.get_property(node_id, prop)
                        if text:
                            vector = embed_text(text, model=model)
                            txn.set_vector(node_id, "embedding", vector)
                            count += 1
                        if on_progress is not None:
                            on_progress()
                    txn.commit()
        return count

    def search_vector(
        self,
        query_text: str,
        node_types: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[SearchResult]:
        if not self.enable_vectors:
            raise RuntimeError(
                "search_vector requires a LatticeBackend opened with "
                "enable_vectors=True."
            )
        query_vector = embed_text(query_text)
        hits = self.db.vector_search(query_vector, k=limit)

        types = set(node_types) if node_types is not None else None
        results: List[SearchResult] = []
        with self.db.read() as txn:
            for hit in hits:
                labels = txn.get_node(hit.node_id).labels
                node_type = next((t for t in labels if t in NODE_PRIMARY_KEY), None)
                if node_type is None or (types is not None and node_type not in types):
                    continue
                pk = NODE_PRIMARY_KEY[node_type]
                results.append(
                    SearchResult(
                        node_id=txn.get_property(hit.node_id, pk),
                        node_type=node_type,
                        name=txn.get_property(hit.node_id, "name") or "",
                        file=txn.get_property(hit.node_id, "file") or "",
                        score=hit.distance,
                    )
                )
        return results

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

import heapq
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

import latticedb

from code_explorer.embeddings import (
    DEFAULT_DIMENSIONS,
    DEFAULT_MODEL,
    embed_text,
    embed_texts,
)
from code_explorer.graph.backends.kuzu_backend import (
    EDGE_ENDPOINT_TYPES,
    FILE_SCOPED_NODE_TYPES,
    NODE_PRIMARY_KEY,
)
from code_explorer.graph.records import EdgeRecord, NodeRecord, SearchResult
from code_explorer.settings import settings

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
# Sourced from Settings (see settings.py) -- module-level for tests that
# monkeypatch it directly (see tests/test_lattice_batching.py).
_UPSERT_BATCH_SIZE = settings.upsert_batch_size

# One Ollama /api/embed HTTP call per this many texts, not one call per node.
# Measured (perfo/benchmark_embed_batching.py, local nomic-embed-text): cost
# per item drops from ~37ms at batch=1 to ~5.2ms flat from batch=50 onward --
# the fixed per-request overhead (not the embedding work itself) dominates
# at small batch sizes, and going bigger than 50 buys almost nothing more.
# Kept well under _UPSERT_BATCH_SIZE so on_progress/write-transaction
# chunking stays granular. Sourced from Settings, module-level for the same
# monkeypatch-friendliness as _UPSERT_BATCH_SIZE above.
_EMBED_BATCH_SIZE = settings.embed_batch_size

# Node labels a call site can resolve to. Classes are here because `Foo()` on
# a project class is a call whose definition is a Class node, not a Function
# node; restricting candidate lookup to "Function" made every project-class
# construction permanently unresolvable.
CALL_TARGET_LABELS: Tuple[str, ...] = ("Function", "Class")

PENDING_CALL_STREAM = "__code_explorer_pending_calls"
UNRESOLVED_CALL_STREAM = "code_explorer_unresolved_calls"


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
            cache_size_mb=settings.lattice_cache_size_mb,
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

    def _ensure_edge_property_index(self, edge_type: str, prop: str) -> None:
        try:
            self.db.create_edge_property_index(edge_type, prop)
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
        # Call resolution looks candidates up by these properties on *both*
        # Function and Class labels (a call to a project class constructor
        # targets a Class node -- see find_symbols_by_properties). Every
        # property looked up must be indexed, including "parent_class" on
        # Class, which no Class node actually carries: the lookup itself is
        # still issued for that label, and an indexless lookup raises
        # LatticeUnsupportedError rather than degrading to a scan.
        for label in CALL_TARGET_LABELS:
            for prop in ("name", "module", "parent_class"):
                self._ensure_node_property_index(label, prop)
        self._ensure_edge_property_index("CALLS", "call_reference_id")
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
            # A target-file update deletes incoming CALLS edges. Their compact
            # extraction facts ride on the edge and are republished atomically
            # so a replacement definition can resolve them later.
            for node_id in node_ids:
                for edge in (
                    *txn.get_outgoing_edges(node_id),
                    *txn.get_incoming_edges(node_id),
                ):
                    if edge.edge_type != "CALLS":
                        continue
                    reference = txn.get_edge_property(edge.id, "call_reference")
                    if not reference or reference.get("caller_file") == file_key:
                        continue
                    txn.publish_stream(
                        PENDING_CALL_STREAM, reference, kind="call.pending"
                    )

            for node_id in node_ids:
                for edge in txn.get_outgoing_edges(node_id):
                    txn.delete_edge(edge.source_id, edge.target_id, edge.edge_type)
                for edge in txn.get_incoming_edges(node_id):
                    txn.delete_edge(edge.source_id, edge.target_id, edge.edge_type)
            for node_id in node_ids:
                txn.delete_node(node_id)
            txn.commit()

    def get_search_node_ids_for_files(self, files: Iterable[str]) -> List[int]:
        """Return Function/Class internal IDs for incremental embedding."""
        ids: List[int] = []
        with self.db.read() as txn:
            for file_key in files:
                for node_type in ("Function", "Class"):
                    ids.extend(
                        txn.find_nodes_by_label_property(
                            node_type, "file", file_key, limit=100_000
                        )
                    )
        return ids

    def get_file_content_hashes(
        self, file_keys: Iterable[str]
    ) -> Dict[str, Optional[str]]:
        """Read bounded caller generations in one read transaction."""
        hashes: Dict[str, Optional[str]] = {}
        with self.db.read() as txn:
            for file_key in set(file_keys):
                node_id = self._find_node_id(txn, "File", file_key)
                hashes[file_key] = (
                    txn.get_property(node_id, "content_hash")
                    if node_id is not None
                    else None
                )
        return hashes

    def clear_all(self) -> None:
        for node_type in NODE_PRIMARY_KEY:
            self.query(f"MATCH (n:{node_type}) DETACH DELETE n")

    def _node_dict(
        self,
        txn: "latticedb.Transaction",
        node_id: int,
        properties: Iterable[str],
    ) -> Dict[str, Any]:
        return {key: txn.get_property(node_id, key) for key in properties}

    def find_functions_by_property(
        self, property_key: str, value: Any, *, limit: int = 10_000
    ) -> List[Dict[str, Any]]:
        """Return functions through a declared Lattice equality index."""
        return self.find_functions_by_properties({(property_key, value): limit})[
            (property_key, value)
        ]

    def find_functions_by_properties(
        self, requests: Mapping[Tuple[str, Any], int]
    ) -> Dict[Tuple[str, Any], List[Dict[str, Any]]]:
        """Resolve a bounded group of index lookups in one read transaction."""
        return self.find_symbols_by_properties(requests, labels=("Function",))

    def find_symbols_by_properties(
        self,
        requests: Mapping[Tuple[str, Any], int],
        labels: Tuple[str, ...] = CALL_TARGET_LABELS,
    ) -> Dict[Tuple[str, Any], List[Dict[str, Any]]]:
        """Resolve a bounded group of index lookups in one read transaction.

        Each candidate carries a "node_type" so the caller can tell a Class
        definition from a Function one -- resolution rules differ (a Class
        has no parent_class) and apply_call_outcomes needs the label to look
        the target's internal id back up by primary key.

        `limit` is applied per label, so a request asking for at most N
        candidates can return up to N*len(labels). That only matters for the
        finalize-time "is this name globally unique?" probe, which asks for 2
        purely to distinguish one from many -- more is still "many".
        """
        properties = (
            "id",
            "name",
            "file",
            "module",
            "parent_class",
            "start_line",
            "end_line",
        )
        results: Dict[Tuple[str, Any], List[Dict[str, Any]]] = {}
        with self.db.read() as txn:
            for (property_key, value), limit in requests.items():
                candidates: List[Dict[str, Any]] = []
                for label in labels:
                    for node_id in txn.find_nodes_by_label_property(
                        label, property_key, value, limit=limit
                    ):
                        candidate = self._node_dict(txn, node_id, properties)
                        candidate["node_type"] = label
                        candidates.append(candidate)
                results[(property_key, value)] = candidates
        return results

    def apply_call_outcomes(
        self,
        resolutions: Iterable[Mapping[str, Any]],
        deferred: Iterable[Mapping[str, Any]],
        *,
        deferred_stream: str = PENDING_CALL_STREAM,
        trim_stream: Optional[str] = None,
        trim_through: Optional[int] = None,
    ) -> int:
        """Write resolved edges and deferred facts in bounded transactions."""
        outcomes = [
            *(("resolved", resolution) for resolution in resolutions),
            *(("deferred", reference) for reference in deferred),
        ]
        count = 0
        batches = list(_chunked(outcomes, _UPSERT_BATCH_SIZE)) or [[]]
        for batch_index, batch in enumerate(batches):
            with self.db.write() as txn:
                for outcome, item in batch:
                    if outcome == "resolved":
                        resolution = item
                        reference = resolution["reference"]
                        caller_id = self._find_node_id(
                            txn, "Function", reference["caller_id"]
                        )
                        # A CALLS edge can point at a Class (constructor
                        # call), so the target's label comes from the
                        # resolution rather than being assumed Function.
                        target_id = self._find_node_id(
                            txn,
                            resolution.get("target_type", "Function"),
                            resolution["target_id"],
                        )
                        if caller_id is None or target_id is None:
                            continue
                        if txn.find_edges_by_type_property(
                            "CALLS",
                            "call_reference_id",
                            reference["id"],
                            limit=1,
                        ):
                            continue
                        txn.create_edge(
                            caller_id,
                            target_id,
                            "CALLS",
                            properties={
                                "call_line": reference["call_line"],
                                "call_reference_id": reference["id"],
                                "call_reference": reference,
                                "resolution_method": resolution["resolution_method"],
                                "confidence": resolution["confidence"],
                            },
                        )
                        count += 1
                    else:
                        reference = item
                        txn.publish_stream(
                            deferred_stream,
                            reference,
                            kind=reference.get("status", "call.pending"),
                        )
                is_last_chunk = batch_index == len(batches) - 1
                if is_last_chunk and trim_stream and trim_through is not None:
                    txn.trim_stream(trim_stream, trim_through)
                txn.commit()
        return count

    def requeue_unresolved_calls(self, limit: int = 1000) -> int:
        """Move durable unresolved facts back to the pending stream."""
        after = 0
        moved = 0
        while records := self.db.read_stream(
            UNRESOLVED_CALL_STREAM, after_sequence=after, limit=limit
        ):
            through = records[-1].sequence
            with self.db.write() as txn:
                for record in records:
                    reference = dict(record.payload)
                    reference.pop("status", None)
                    txn.publish_stream(
                        PENDING_CALL_STREAM, reference, kind="call.pending"
                    )
                    moved += 1
                txn.trim_stream(UNRESOLVED_CALL_STREAM, through)
                txn.commit()
            after = through
        return moved

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

    def get_most_called_functions(self, limit: int = 20) -> List[Tuple[str, str, int]]:
        """Imperative-API implementation -- see CodeGraphBackend's docstring
        for why (measured ~19x faster than the equivalent Cypher aggregation
        on gemseo's real 338K-edge graph: 1.25s vs 23.9s). Iterates every
        Function node (get_nodes_by_label, imperative) and counts its
        incoming CALLS edges (get_incoming_edges, also imperative) --
        neither goes through the Cypher planner.

        Aggregates by (name, file), summing counts across nodes that share
        that key -- matching the old Cypher query's GROUP BY semantics
        exactly (Cypher groups by the *returned* callee.name/callee.file
        columns, not node identity). Two distinct Function nodes can share
        (name, file) -- e.g. same-named methods on different classes in one
        file, the same ambiguity class handled elsewhere this session (see
        QueryOperations._resolve_function_id) -- and a first version of this
        method that kept per-node counts instead of grouping silently
        dropped such a function from the top-N entirely (found via a
        mismatch against the old query's output on this repo's own
        tree_sitter_adapter.py::walk, which has exactly two such nodes).
        """
        with self.db.read() as txn:
            function_ids = txn.get_nodes_by_label("Function")
            counts: Dict[Tuple[str, str], int] = {}
            for fid in function_ids:
                count = sum(
                    1 for e in txn.get_incoming_edges(fid) if e.edge_type == "CALLS"
                )
                if count == 0:
                    continue
                key = (txn.get_property(fid, "name"), txn.get_property(fid, "file"))
                counts[key] = counts.get(key, 0) + count

            top = heapq.nlargest(limit, counts.items(), key=lambda kv: kv[1])
        return [(name, file, count) for (name, file), count in top]

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
        node_ids: Optional[Iterable[int]] = None,
    ) -> int:
        """Embed and store a vector for existing nodes, using their
        SEARCHABLE_TEXT_FIELDS text property.

        A separate step from ingestion on purpose (see the migration spec,
        Section 10: "Do not generate embeddings during AST parsing" -- select
        entities from the already-built graph, then embed). Texts are
        embedded in batches of _EMBED_BATCH_SIZE via one Ollama HTTP call
        per batch, not one call per node -- see _EMBED_BATCH_SIZE for the
        measurement behind that number.

        node_ids: embed only these specific internal node ids (any mix of
        Function/Class ids), skipping the get_nodes_by_label(node_type) scan
        over the whole graph -- used for incremental re-indexing, where only
        a handful of nodes actually changed. All searchable node types share
        the same "search_text" property name (see SEARCHABLE_TEXT_FIELDS),
        so no per-type lookup is needed here; node_types is ignored when
        node_ids is given. Passing an id that has no search_text property
        (e.g. a File node) is harmless -- get_property returns falsy and
        it's silently skipped, same as the full-scan path.

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
        count = 0
        if node_ids is not None:
            # Chunked rather than one transaction for everything: each
            # inner batch makes a slow external Ollama HTTP call while
            # holding the transaction open -- chunking bounds how long a
            # single write transaction sits open waiting on the network.
            for batch in _chunked(list(node_ids), _UPSERT_BATCH_SIZE):
                with self.db.write() as txn:
                    count += self._embed_batch(
                        txn, batch, "search_text", model, on_progress
                    )
                    txn.commit()
            return count

        types = node_types if node_types is not None else list(SEARCHABLE_TEXT_FIELDS)
        for node_type in types:
            prop = SEARCHABLE_TEXT_FIELDS.get(node_type)
            if prop is None:
                continue
            type_node_ids = self.db.get_nodes_by_label(node_type)
            for batch in _chunked(type_node_ids, _UPSERT_BATCH_SIZE):
                with self.db.write() as txn:
                    count += self._embed_batch(txn, batch, prop, model, on_progress)
                    txn.commit()
        return count

    def _embed_batch(
        self,
        txn: Any,
        node_ids: List[int],
        prop: str,
        model: str,
        on_progress: Optional[Callable[[], None]],
    ) -> int:
        """Embed and store vectors for `node_ids` within an open write
        transaction, batching Ollama calls at _EMBED_BATCH_SIZE. Nodes with
        no (or empty) `prop` text are skipped, same as before batching.
        """
        count = 0
        for sub_batch in _chunked(node_ids, _EMBED_BATCH_SIZE):
            texts: List[str] = []
            ids_with_text: List[int] = []
            for node_id in sub_batch:
                text = txn.get_property(node_id, prop)
                if text:
                    texts.append(text)
                    ids_with_text.append(node_id)
            if texts:
                vectors = embed_texts(texts, model=model)
                for node_id, vector in zip(ids_with_text, vectors):
                    txn.set_vector(node_id, "embedding", vector)
                    count += 1
            if on_progress is not None:
                for _ in sub_batch:
                    on_progress()
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

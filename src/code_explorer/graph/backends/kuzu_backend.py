"""Kuzu implementation of CodeGraphBackend.

Wraps the kuzu.Database/kuzu.Connection construction and SchemaManager that used
to live directly in DependencyGraph.__init__ (see graph/graph.py). This is
Phase 0's proof that the CodeGraphBackend interface fits the existing behavior
before a LatticeBackend is attempted.

upsert_nodes/upsert_edges are a generic implementation of the canonical
NodeRecord/EdgeRecord shape, driven by the same primary keys and FROM/TO
endpoint types declared in graph/schema.py's DDL. DependencyGraph does not use
them yet -- it still calls the specialized NodeOperations/EdgeOperations/
QueryOperations classes directly via `backend.conn`, which remains unchanged in
Phase 0 (see docs/explanation/latticedb-migration.md, Phase 0 scope).
"""

from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import kuzu

from code_explorer.graph.records import EdgeRecord, NodeRecord, SearchResult
from code_explorer.graph.schema import SchemaManager

# Primary key property per node type, mirroring the CREATE NODE TABLE ...
# PRIMARY KEY(...) clauses in schema.py.
NODE_PRIMARY_KEY: Dict[str, str] = {
    "File": "path",
    "Function": "id",
    "Variable": "id",
    "Class": "id",
    "Import": "id",
    "Decorator": "id",
    "Attribute": "id",
    "Exception": "id",
    "Module": "id",
    # A symbol we know is called but deliberately never index: numpy.array,
    # fastapi.HTTPException, pytest.raises... The user's boundary rule is
    # "keep 'my function calls a fastapi function', don't go deeper than
    # that", and since library sources are never parsed, an ExternalSymbol
    # is always a leaf -- the boundary enforces itself.
    "ExternalSymbol": "id",
}

# (src_type, dst_type) per edge type, mirroring the CREATE REL TABLE ... FROM
# ... TO ... clauses in schema.py.
EDGE_ENDPOINT_TYPES: Dict[str, Tuple[str, str]] = {
    "CALLS": ("Function", "Function"),
    "REFERENCES": ("Function", "Variable"),
    "CONTAINS_FUNCTION": ("File", "Function"),
    "CONTAINS_CLASS": ("File", "Class"),
    "CONTAINS_VARIABLE": ("File", "Variable"),
    "IMPORTS": ("File", "File"),
    "INHERITS": ("Class", "Class"),
    # The one edge type whose endpoints are NOT fixed. DEPENDS_ON is a
    # single relation carrying a `kind` -- "inherits" (Class -> Class),
    # "decorates" (Function|Class -> Function|Class), "imports" (File ->
    # File) -- and any of them may land on an ExternalSymbol when the
    # target is outside the corpus. The pair below is the default used
    # when an EdgeRecord does not name its own endpoint labels; edges
    # built by graph/ingest.py always do (EdgeRecord.src_type/dst_type).
    #
    # NOTE for Kuzu specifically: its REL TABLE DDL in schema.py declares
    # DEPENDS_ON as Class -> Class only, so a cross-label DEPENDS_ON
    # would fail there. Not fixed because nothing writes one: Kuzu
    # ingests through the Parquet bulk loader, not through
    # file_analyses_to_records.
    "DEPENDS_ON": ("Class", "Class"),
    "METHOD_OF": ("Function", "Class"),
    "HAS_IMPORT": ("File", "Import"),
    "IMPORTS_FROM": ("Import", "Function"),
    "DECORATED_BY": ("Function", "Decorator"),
    "HAS_ATTRIBUTE": ("Class", "Attribute"),
    "ACCESSES": ("Function", "Attribute"),
    "HANDLES_EXCEPTION": ("Function", "Exception"),
    "CONTAINS_MODULE": ("Module", "Module"),
    "MODULE_OF": ("File", "Module"),
    # Deduped per (caller, symbol) rather than per call site -- unlike CALLS,
    # which keeps one edge per call site because "who calls this at which
    # line" is a question users ask. Nobody asks for the 2,247nd call site of
    # numpy.array; on the measured 2,107-file corpus this collapses 13,844
    # external call sites into 9,095 edges. The lost per-site detail is kept
    # in aggregate as the edge's `count` property.
    "CALLS_EXTERNAL": ("Function", "ExternalSymbol"),
}

# Node types deleted (with their owned edges) when a file is removed/re-indexed,
# matching DependencyGraph.node_ops.delete_file_data.
FILE_SCOPED_NODE_TYPES = (
    "Function",
    "Class",
    "Variable",
    "Import",
    "Decorator",
    "Attribute",
    "Exception",
)


class KuzuBackend:
    """CodeGraphBackend implementation backed by KuzuDB."""

    def __init__(self, db_path: Path, read_only: bool = False):
        self.db_path = db_path
        self.read_only = read_only
        self.db: Optional[kuzu.Database] = None
        self.conn: Optional[kuzu.Connection] = None
        self.schema_manager: Optional[SchemaManager] = None
        # Declared columns per node table, filled lazily from table_info.
        # See _table_columns.
        self._table_columns: Dict[str, frozenset] = {}

    def open(self) -> None:
        # Idempotent, for the same reason as LatticeBackend.open(): callers
        # that use `with backend:` and then hand the backend to
        # DependencyGraph would otherwise open it twice. Kuzu tolerates this
        # less loudly than LatticeDB (it does not raise here, but a second
        # kuzu.Database on the same directory is still a second lock holder
        # and leaks the first Connection), so both backends behave the same
        # way rather than only the one where the bug was observed.
        if self.db is not None:
            return
        if not self.read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = kuzu.Database(str(self.db_path), read_only=self.read_only)
        self.conn = kuzu.Connection(self.db)
        self.schema_manager = SchemaManager(self.conn)

    def close(self) -> None:
        self.conn = None
        self.db = None
        self.schema_manager = None
        self._table_columns = {}

    def __enter__(self):
        """Context-manager support so callers cannot forget close().

        Not cosmetic: leaving a database open leaves an un-checkpointed WAL,
        and the next process to open it pays a recovery pass -- measured at
        >400s on the 2,103-file corpus (256MB, 3.2MB WAL) versus 0.03s after
        a clean close. It also left the FTS indexes unreadable, so search
        raised LatticeUnsupportedError. A missing close() in one benchmark
        script produced all of that, so the fix is to make closing automatic
        rather than remembered.
        """
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
        return None

    def initialize_schema(self, *, create_fts_indexes: bool = True) -> None:
        # create_fts_indexes is accepted for backend-protocol parity and
        # ignored: Kuzu search here is Cypher/regex over stored columns, so
        # there is no separate full-text index to defer past a bulk load.
        if self.read_only:
            return
        self.schema_manager.create_schema()

    def detect_schema_version(self) -> str:
        """Preserved from SchemaManager for DependencyGraph's existing use."""
        return self.schema_manager.detect_schema_version()

    def _table_columns_for(self, label: str) -> frozenset:
        """Columns the node table actually declares, from Kuzu itself.

        Kuzu rejects a MERGE that sets a property the table does not have
        ("Binder exception: Cannot find property module for n"), and the
        canonical NodeRecord carries properties this DDL never had --
        Function.module/parent_class and Class.module, which the other two
        backends do declare. Adding them to schema.py is not an option: the
        Parquet bulk loader (graph/bulk_loader.py) issues bare
        `COPY Function FROM <file>`, which matches columns by position, so
        two extra columns would break every bulk load.

        So the extra properties are dropped for this backend only. Read from
        table_info rather than a fourth hand-maintained copy of the DDL, and
        cached: this is one query per label per open, not per node.
        """
        columns = self._table_columns.get(label)
        if columns is None:
            result = self.conn.execute(f"CALL table_info('{label}') RETURN *")
            names = set()
            while result.has_next():
                names.add(result.get_next()[1])
            columns = frozenset(names)
            self._table_columns[label] = columns
        return columns

    def upsert_nodes(
        self,
        nodes: Iterable[NodeRecord],
        on_progress: Optional[Callable[[], None]] = None,
        assume_new: bool = False,
    ) -> Dict[Tuple[str, str], int]:
        # assume_new is a LatticeBackend-only optimization (skips a separate
        # existence-lookup Lattice needs but Kuzu's MERGE doesn't) -- accepted
        # here for interface compatibility, has no effect: MERGE already does
        # a single create-or-update in one query regardless. Kuzu has no
        # internal-id concept to hand back either (Cypher addresses nodes by
        # their own properties, not a separate id), so this always returns
        # {} -- upsert_edges falls back to its own MATCH-by-property lookup
        # unconditionally, which is already a single query, not a separate
        # existence check + create like Lattice's.
        for node in nodes:
            pk = NODE_PRIMARY_KEY.get(node.type)
            if pk is None:
                raise ValueError(f"Unknown node type for upsert: {node.type}")
            pk_value = node.properties.get(pk, node.id)
            declared = self._table_columns_for(node.type)
            set_props = {
                k: v
                for k, v in node.properties.items()
                if k != pk and k in declared
            }
            set_clause = ", ".join(f"n.{k} = ${k}" for k in set_props)
            params = {pk: pk_value, **set_props}
            query = f"MERGE (n:{node.type} {{{pk}: ${pk}}})"
            if set_clause:
                query += f" ON CREATE SET {set_clause} ON MATCH SET {set_clause}"
            self.conn.execute(query, params)
            if on_progress is not None:
                on_progress()
        return {}

    def upsert_edges(
        self,
        edges: Iterable[EdgeRecord],
        on_progress: Optional[Callable[[], None]] = None,
        node_id_map: Optional[Dict[Tuple[str, str], int]] = None,
    ) -> None:
        # node_id_map is a LatticeBackend-only optimization -- ignored here,
        # see upsert_nodes.
        for edge in edges:
            endpoints = EDGE_ENDPOINT_TYPES.get(edge.type)
            if endpoints is None:
                raise ValueError(f"Unknown edge type for upsert: {edge.type}")
            src_type = edge.src_type or endpoints[0]
            dst_type = edge.dst_type or endpoints[1]
            src_pk = NODE_PRIMARY_KEY[src_type]
            dst_pk = NODE_PRIMARY_KEY[dst_type]
            params = {
                "src": edge.src_id,
                "dst": edge.dst_id,
                **edge.properties,
            }
            # Match on the edge's own properties too, not just (src, dst, type):
            # some edge types (e.g. CALLS) legitimately have multiple parallel
            # edges between the same node pair (distinct call sites). Matching
            # on (src, dst, type) alone would MERGE them into a single edge,
            # silently discarding all but the last-written one.
            rel_props = ", ".join(f"{k}: ${k}" for k in edge.properties)
            rel_pattern = f"r:{edge.type} {{{rel_props}}}" if rel_props else f"r:{edge.type}"
            query = (
                f"MATCH (a:{src_type} {{{src_pk}: $src}}), "
                f"(b:{dst_type} {{{dst_pk}: $dst}}) "
                f"MERGE (a)-[{rel_pattern}]->(b)"
            )
            self.conn.execute(query, params)
            if on_progress is not None:
                on_progress()

    def delete_file(self, file_key: str) -> None:
        for node_type in FILE_SCOPED_NODE_TYPES:
            self.conn.execute(
                f"MATCH (n:{node_type} {{file: $path}}) DETACH DELETE n",
                {"path": file_key},
            )
        self.conn.execute(
            "MATCH (f:File {path: $path}) DETACH DELETE f",
            {"path": file_key},
        )

    def clear_all(self) -> None:
        for node_type in NODE_PRIMARY_KEY:
            self.conn.execute(f"MATCH (n:{node_type}) DETACH DELETE n")

    def query(
        self, statement: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        result = self.conn.execute(statement, params or {})
        columns = result.get_column_names()
        rows: List[Dict[str, Any]] = []
        while result.has_next():
            rows.append(dict(zip(columns, result.get_next())))
        return rows

    def get_call_edges_with_lines(
        self, function_canonical_id: str
    ) -> Tuple[
        List[Tuple[str, str, int, int, int]], List[Tuple[str, str, int, int, int]]
    ]:
        # Kuzu's Cypher has no equivalent to LatticeDB's Expand-plan
        # slowdown (confirmed: 0.52ms for this shape of query on the small
        # test repo) -- Cypher is already the fastest option here, no need
        # for an imperative-API path like LatticeBackend's.
        caller_rows = self.query(
            """
            MATCH (caller:Function)-[c:CALLS]->(callee:Function {id: $id})
            RETURN caller.file AS file, caller.name AS name, c.call_line AS call_line,
                   caller.start_line AS start_line, caller.end_line AS end_line
            """,
            {"id": function_canonical_id},
        )
        callee_rows = self.query(
            """
            MATCH (caller:Function {id: $id})-[c:CALLS]->(callee:Function)
            RETURN callee.file AS file, callee.name AS name, c.call_line AS call_line,
                   callee.start_line AS start_line, callee.end_line AS end_line
            """,
            {"id": function_canonical_id},
        )

        def _to_tuples(rows):
            return [
                (r["file"], r["name"], r["call_line"], r["start_line"], r["end_line"])
                for r in rows
            ]

        return _to_tuples(caller_rows), _to_tuples(callee_rows)

    def get_most_called_functions(
        self, limit: int = 20
    ) -> List[Tuple[str, str, int]]:
        # Kuzu has no equivalent slowdown for this shape of query -- just
        # use Cypher, no optimization effort needed here.
        rows = self.query(
            """
            MATCH (caller:Function)-[:CALLS]->(callee:Function)
            RETURN callee.name AS name, callee.file AS file, COUNT(caller) AS call_count
            ORDER BY call_count DESC
            LIMIT $limit
            """,
            {"limit": limit},
        )
        return [(r["name"], r["file"], r["call_count"]) for r in rows]

    def search_text(
        self,
        query: str,
        node_types: Optional[List[str]] = None,
        limit: int = 10,
        fuzzy: bool = False,
    ) -> List[SearchResult]:
        raise NotImplementedError(
            "KuzuBackend does not support text search -- BM25/fuzzy search is "
            "a LatticeDB-only capability for now (Kuzu has no full-text search "
            "engine). Use LatticeBackend, or fall back to exact lookups via "
            "query()/get_function()."
        )

    def search_vector(
        self,
        query_text: str,
        node_types: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[SearchResult]:
        raise NotImplementedError(
            "KuzuBackend does not support vector search -- semantic search is "
            "a LatticeDB-only capability for now (Kuzu has no vector index). "
            "Use LatticeBackend, or fall back to exact lookups via "
            "query()/get_function()."
        )

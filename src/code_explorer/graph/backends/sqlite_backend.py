"""SQLite implementation of CodeGraphBackend -- FEASIBILITY SPIKE.

Why this exists: Kuzu was archived (Oct 2025) and LatticeDB has a blocking
reopen bug on a real index built with a BM25 FTS index (>400s inside
db.open(); 0.17s for the same database without FTS). This module answers
"could stdlib sqlite3 carry the full CodeGraphBackend contract?" with
running code and measurements (see perfo/benchmark_sqlite_backend.py), not
with an opinion.

Storage model -- relational, one table per label, NOT a property graph:

- One table per node label, with the exact columns Kuzu's DDL declares
  (graph/schema.py) plus `search_text` on Function/Class. The canonical id
  (NODE_PRIMARY_KEY) is the SQL PRIMARY KEY.
- One table per edge type, holding the endpoints' *canonical ids* as TEXT
  (`src`/`dst`) plus the edge's declared property columns. Endpoints are
  therefore never resolved to an internal integer id -- upsert_edges needs
  no lookup at all, and `node_id_map` is accepted and ignored (same as
  KuzuBackend). upsert_nodes returns {} for the same reason.
- Any property not declared as a column is JSON-encoded into an `extra_json`
  column. HYPOTHESIS/LIMITATION: such properties are storable and readable
  via SQL json_extract(), but the Cypher subset in query() will NOT see
  them -- a `MATCH (n:X {undeclared_prop: $v})` silently matches nothing
  rather than erroring. Nothing in this repo does that today (every
  property used in a Cypher pattern is a declared column), but a future
  extractor adding a field to a NodeRecord without adding it here would hit
  exactly that silent gap.

query() is a *restricted Cypher subset translator*, not a Cypher engine --
see _CypherToSQL below for exactly what it accepts and what it does not.
It exists so this spike can be measured against the SAME call sites and the
same backend-agnostic tests as Kuzu/LatticeDB, not because a translator is
the right long-term answer (the report argues for typed methods instead).
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

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

# Column layout per node label, mirroring graph/schema.py's CREATE NODE TABLE
# DDL exactly (same names, same order), with SQLite storage classes. BOOLEAN
# has no native SQLite type: stored as INTEGER 0/1 and converted back to bool
# on read (see _BOOL_COLUMNS).
NODE_COLUMNS: Dict[str, Dict[str, str]] = {
    "File": {"path": "TEXT", "language": "TEXT", "content_hash": "TEXT"},
    "Function": {
        "id": "TEXT",
        "name": "TEXT",
        "file": "TEXT",
        "start_line": "INTEGER",
        "end_line": "INTEGER",
        "is_public": "INTEGER",
        "source_code": "TEXT",
        "search_text": "TEXT",
    },
    "Variable": {
        "id": "TEXT",
        "name": "TEXT",
        "file": "TEXT",
        "definition_line": "INTEGER",
        "scope": "TEXT",
    },
    "Class": {
        "id": "TEXT",
        "name": "TEXT",
        "file": "TEXT",
        "start_line": "INTEGER",
        "end_line": "INTEGER",
        "bases": "TEXT",
        "is_public": "INTEGER",
        "source_code": "TEXT",
        "search_text": "TEXT",
    },
    "Import": {
        "id": "TEXT",
        "imported_name": "TEXT",
        "import_type": "TEXT",
        "alias": "TEXT",
        "line_number": "INTEGER",
        "is_relative": "INTEGER",
        "file": "TEXT",
    },
    "Decorator": {
        "id": "TEXT",
        "name": "TEXT",
        "file": "TEXT",
        "line_number": "INTEGER",
        "arguments": "TEXT",
    },
    "Attribute": {
        "id": "TEXT",
        "name": "TEXT",
        "class_name": "TEXT",
        "file": "TEXT",
        "definition_line": "INTEGER",
        "type_hint": "TEXT",
        "is_class_attribute": "INTEGER",
    },
    "Exception": {"id": "TEXT", "name": "TEXT", "file": "TEXT", "line_number": "INTEGER"},
    "Module": {
        "id": "TEXT",
        "name": "TEXT",
        "path": "TEXT",
        "is_package": "INTEGER",
        "docstring": "TEXT",
    },
}

# Property columns per edge type, mirroring graph/schema.py's CREATE REL TABLE
# DDL. Endpoints are always (src TEXT, dst TEXT) holding canonical ids.
EDGE_COLUMNS: Dict[str, Dict[str, str]] = {
    "CALLS": {"call_line": "INTEGER"},
    "REFERENCES": {"line_number": "INTEGER", "context": "TEXT"},
    "CONTAINS_FUNCTION": {},
    "CONTAINS_CLASS": {},
    "CONTAINS_VARIABLE": {},
    "IMPORTS": {"line_number": "INTEGER", "is_direct": "INTEGER"},
    "INHERITS": {},
    "DEPENDS_ON": {"dependency_type": "TEXT", "line_number": "INTEGER"},
    "METHOD_OF": {},
    "HAS_IMPORT": {},
    "IMPORTS_FROM": {},
    "DECORATED_BY": {"position": "INTEGER"},
    "HAS_ATTRIBUTE": {},
    "ACCESSES": {"line_number": "INTEGER", "access_type": "TEXT"},
    "HANDLES_EXCEPTION": {"line_number": "INTEGER", "context": "TEXT"},
    "CONTAINS_MODULE": {},
    "MODULE_OF": {},
}

# Columns declared BOOLEAN in the Kuzu DDL: stored 0/1 in SQLite, converted
# back to bool when read out through query()/typed methods, so callers that
# do `if row["is_public"]` or compare `is True` behave identically.
_BOOL_COLUMNS: Dict[Tuple[str, str], bool] = {
    ("Function", "is_public"): True,
    ("Class", "is_public"): True,
    ("Import", "is_relative"): True,
    ("Attribute", "is_class_attribute"): True,
    ("Module", "is_package"): True,
    ("IMPORTS", "is_direct"): True,
}

# Extra secondary indexes beyond each table's PRIMARY KEY. `file` is the hot
# one (delete_file, get_functions_in_file, and most (file, name) lookups);
# `name` backs the search/resolve paths.
_NODE_INDEXES: Dict[str, Tuple[str, ...]] = {
    "Function": ("file", "name"),
    "Class": ("file", "name"),
    "Variable": ("file", "name"),
    "Import": ("file", "imported_name"),
    "Decorator": ("file", "name"),
    "Attribute": ("file", "name", "class_name"),
    "Exception": ("file", "name"),
    "Module": ("name",),
}

# Node types + text column indexed for BM25/fuzzy search, matching
# LatticeBackend.SEARCHABLE_TEXT_FIELDS so both backends index the same text.
SEARCHABLE_TEXT_FIELDS: Dict[str, str] = {"Function": "search_text", "Class": "search_text"}

# One executemany() / transaction per this many rows. Mirrors
# LatticeBackend's _UPSERT_BATCH_SIZE so ingest comparisons are like for
# like; SQLite itself would be happy with far larger batches.
_UPSERT_BATCH_SIZE = 1000

_EMBED_BATCH_SIZE = 50


def _chunked(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


# --------------------------------------------------------------------------
# Cypher subset -> SQL
# --------------------------------------------------------------------------

_MATCH_RE = re.compile(r"^\s*MATCH\s+(?P<pattern>.+?)\s*(?=(?:\bWHERE\b|\bWITH\b|\bRETURN\b|\bDETACH\b))", re.I | re.S)
_NODE_RE = re.compile(r"\(\s*(?P<var>\w*)\s*(?::\s*(?P<label>\w+))?\s*(?P<props>\{.*?\})?\s*\)", re.S)
_REL_RE = re.compile(r"-\[\s*(?P<var>\w*)\s*(?::\s*(?P<type>\w+))?\s*(?P<props>\{.*?\})?\s*\]->", re.S)
_PROP_RE = re.compile(r"(\w+)\s*:\s*(\$\w+|'[^']*'|\"[^\"]*\"|-?\d+)")
_RETURN_RE = re.compile(r"\bRETURN\s+(?P<distinct>DISTINCT\s+)?(?P<items>.+?)(?:\s+ORDER\s+BY\s+(?P<order>.+?))?(?:\s+LIMIT\s+(?P<limit>\S+))?\s*$", re.I | re.S)
_ITEM_RE = re.compile(r"^(?P<expr>.+?)(?:\s+AS\s+(?P<alias>\w+))?$", re.I | re.S)
_AGG_RE = re.compile(r"^(?P<fn>COUNT|COLLECT)\s*\(\s*(?P<arg>[\w.]+|\*)\s*\)$", re.I)


class CypherSubsetError(ValueError):
    """The statement uses Cypher this translator does not implement.

    Raised loudly on purpose: the alternative (best-effort translation) would
    return silently wrong rows, which is worse than a crash in a spike whose
    whole point is measuring what does and does not work.
    """


class _CypherToSQL:
    """Translate the small, highly stereotyped Cypher dialect this repo
    actually uses into SQL against the relational layout above.

    SUPPORTED (this is the complete list -- every shape found by grepping
    every backend.query() call site in src/, tests/ and perfo/):

        MATCH (v:Label {prop: $p, ...})
              [ -[r:TYPE]-> (w:Label2 {...}) ]
        [WHERE <simple boolean expr over v.prop / r.prop>]
        RETURN [DISTINCT] v.prop AS a, COUNT(w) AS n, ...
        [ORDER BY <alias|expr> [ASC|DESC]] [LIMIT n]

        MATCH ()-[r:TYPE]->()  RETURN COUNT(r) AS count
        MATCH (n:Label) DETACH DELETE n

    plus ONE hand-special-cased pipeline (the multi-decorator report in
    graph/queries.py), because it is the only statement in the repo using
    WITH/COLLECT and generalising WITH was not worth it for a spike.

    NOT SUPPORTED, and raises CypherSubsetError rather than guessing:
    variable-length paths (-[:CALLS*1..3]->), OPTIONAL MATCH, UNION,
    multi-hop patterns (3+ nodes), undirected patterns, CREATE/MERGE/SET,
    subqueries, general WITH pipelines, and any function beyond
    COUNT/COLLECT.

    HYPOTHESIS about equivalence: SQL joins are *inner* joins, and Cypher's
    MATCH on a relationship pattern is likewise an inner join, so
    single-hop patterns translate faithfully. Aggregation groups by the
    non-aggregate RETURN items, which matches Cypher's implicit
    group-by-returned-columns semantics (the same semantics that
    get_most_called_functions depends on -- see its docstring about two
    Function nodes sharing (name, file)). Where this can get it wrong: NULL
    handling differs (SQL drops NULL rows from a join the same way Cypher
    does, but `WHERE x <> 'y'` excludes NULLs in both, so no divergence was
    found in practice) and Cypher's `DISTINCT` applies to the whole returned
    row in both -- verified against the backend-agnostic tests, not proven
    in general.
    """

    def __init__(self, statement: str, params: Dict[str, Any]):
        self.statement = " ".join(statement.split())
        self.params = params
        self.sql_params: Dict[str, Any] = dict(params)
        self._counter = 0
        # (alias, label) for each node var; used to type-convert results.
        self.var_label: Dict[str, str] = {}
        self.var_kind: Dict[str, str] = {}  # 'node' | 'edge'

    def _bind(self, value: Any) -> str:
        self._counter += 1
        key = f"_lit{self._counter}"
        self.sql_params[key] = value
        return f":{key}"

    # -- pattern -----------------------------------------------------------

    def _parse_props(self, raw: Optional[str]) -> List[Tuple[str, str]]:
        if not raw:
            return []
        out = []
        for prop, value in _PROP_RE.findall(raw):
            if value.startswith("$"):
                out.append((prop, ":" + value[1:]))
            elif value[0] in "'\"":
                out.append((prop, self._bind(value[1:-1])))
            else:
                out.append((prop, self._bind(int(value))))
        return out

    def translate(self) -> Tuple[str, Dict[str, Any], Dict[str, Tuple[str, str]]]:
        """Return (sql, params, column_origin) where column_origin maps an
        output column name to the (label, property) it came from, so the
        caller can restore BOOLEAN columns to Python bools."""
        m = _MATCH_RE.search(self.statement)
        if not m:
            raise CypherSubsetError(f"Not a supported MATCH statement: {self.statement!r}")
        pattern = m.group("pattern")

        nodes = list(_NODE_RE.finditer(pattern))
        rels = list(_REL_RE.finditer(pattern))
        if len(nodes) > 2 or len(rels) > 1:
            raise CypherSubsetError(
                f"Only single-hop patterns are supported, got {len(nodes)} nodes / "
                f"{len(rels)} relationships: {self.statement!r}"
            )

        froms: List[str] = []
        wheres: List[str] = []

        def add_node(idx: int) -> Optional[str]:
            nm = nodes[idx]
            label, var = nm.group("label"), nm.group("var")
            if not label:
                return None  # anonymous endpoint, e.g. MATCH ()-[r:T]->()
            if label not in NODE_COLUMNS:
                raise CypherSubsetError(f"Unknown node label {label!r}")
            var = var or f"_n{idx}"
            self.var_label[var] = label
            self.var_kind[var] = "node"
            froms.append(f'"{label}" AS {var}')
            for prop, placeholder in self._parse_props(nm.group("props")):
                wheres.append(f"{var}.{prop} = {placeholder}")
            return var

        src_var = add_node(0)
        rel_var = None
        dst_var = None
        if rels:
            rm = rels[0]
            etype = rm.group("type")
            if not etype:
                raise CypherSubsetError("Untyped relationship patterns are not supported")
            if etype not in EDGE_COLUMNS:
                raise CypherSubsetError(f"Unknown edge type {etype!r}")
            rel_var = rm.group("var") or "_r"
            self.var_label[rel_var] = etype
            self.var_kind[rel_var] = "edge"
            froms.append(f'"{etype}" AS {rel_var}')
            for prop, placeholder in self._parse_props(rm.group("props")):
                wheres.append(f"{rel_var}.{prop} = {placeholder}")
            dst_var = add_node(1)
            src_type, dst_type = EDGE_ENDPOINT_TYPES[etype]
            if src_var:
                wheres.append(f"{rel_var}.src = {src_var}.{NODE_PRIMARY_KEY[src_type]}")
            if dst_var:
                wheres.append(f"{rel_var}.dst = {dst_var}.{NODE_PRIMARY_KEY[dst_type]}")

        # -- WHERE ---------------------------------------------------------
        wm = re.search(r"\bWHERE\b(?P<expr>.+?)(?=\bRETURN\b|\bWITH\b|$)", self.statement, re.I | re.S)
        if wm:
            wheres.append("(" + self._translate_expr(wm.group("expr")) + ")")

        # -- RETURN --------------------------------------------------------
        rm2 = _RETURN_RE.search(self.statement)
        if not rm2:
            raise CypherSubsetError(f"No RETURN clause: {self.statement!r}")

        select_parts: List[str] = []
        group_parts: List[str] = []
        origins: Dict[str, Tuple[str, str]] = {}
        has_agg = False
        for item in _split_items(rm2.group("items")):
            im = _ITEM_RE.match(item.strip())
            expr, alias = im.group("expr").strip(), im.group("alias")
            agg = _AGG_RE.match(expr)
            if agg:
                has_agg = True
                fn = agg.group("fn").upper()
                arg = agg.group("arg")
                if fn == "COUNT":
                    # COUNT(v) in Cypher counts non-null rows for that
                    # variable; with an inner join every joined row is
                    # non-null, so COUNT(*) is equivalent here.
                    sql_expr = "COUNT(*)"
                else:
                    sql_expr = f"group_concat({self._qualify(arg)})"
                out = alias or expr
                select_parts.append(f'{sql_expr} AS "{out}"')
                continue
            sql_expr = self._qualify(expr)
            out = alias or expr
            select_parts.append(f'{sql_expr} AS "{out}"')
            group_parts.append(sql_expr)
            if "." in expr:
                var, prop = expr.split(".", 1)
                if var in self.var_label:
                    origins[out] = (self.var_label[var], prop)

        sql = "SELECT "
        if rm2.group("distinct"):
            sql += "DISTINCT "
        sql += ", ".join(select_parts)
        sql += " FROM " + ", ".join(froms) if froms else ""
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        if has_agg and group_parts:
            sql += " GROUP BY " + ", ".join(group_parts)
        if rm2.group("order"):
            sql += " ORDER BY " + self._translate_order(rm2.group("order"))
        if rm2.group("limit"):
            lim = rm2.group("limit").strip()
            sql += " LIMIT " + (":" + lim[1:] if lim.startswith("$") else lim)
        return sql, self.sql_params, origins

    def _qualify(self, expr: str) -> str:
        return expr.strip()

    def _translate_order(self, order: str) -> str:
        # ORDER BY items reference either an output alias or var.prop; both
        # are legal in SQLite's ORDER BY, so only list syntax needs fixing.
        return order.strip()

    def _translate_expr(self, expr: str) -> str:
        """Cypher boolean expression -> SQL. Only the forms this repo uses:
        `x.p = 'lit'`, `x.p IN ['a','b']`, `n > 1`, joined by AND/OR.
        `$param` becomes `:param`; Cypher list literals become SQL tuples.
        """
        out = expr.strip()
        out = re.sub(r"\$(\w+)", r":\1", out)
        out = out.replace("[", "(").replace("]", ")")
        out = re.sub(r"\bIS\s+NULL\b", "IS NULL", out, flags=re.I)
        out = out.replace("<>", "!=")
        if re.search(r"\b(CREATE|MERGE|DELETE|SET|CALL)\b", out, re.I):
            raise CypherSubsetError(f"Unsupported WHERE expression: {expr!r}")
        return out


def _split_items(items: str) -> List[str]:
    """Split a RETURN list on top-level commas (not commas inside COUNT()/[])."""
    out, depth, cur = [], 0, ""
    for ch in items:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


# The one statement in the repo that uses WITH/COLLECT (QueryOperations.
# find_multi_decorated_functions). Hand-translated rather than generalising
# WITH -- see _CypherToSQL's docstring.
_MULTI_DECORATOR_SQL = """
SELECT func.name AS function_name, func.file AS file_path,
       COUNT(dec.id) AS decorator_count,
       group_concat(dec.name) AS decorators
FROM "Function" AS func, "DECORATED_BY" AS r, "Decorator" AS dec
WHERE r.src = func.id AND r.dst = dec.id
GROUP BY func.name, func.file
HAVING COUNT(dec.id) > 1
ORDER BY decorator_count DESC
"""


class SqliteBackend:
    """CodeGraphBackend implementation backed by stdlib sqlite3 + FTS5."""

    def __init__(
        self,
        db_path: Path,
        read_only: bool = False,
        enable_vectors: bool = False,
        vector_dimensions: int = DEFAULT_DIMENSIONS,
        enable_fts: bool = True,
        enable_fuzzy: bool = True,
    ):
        """
        enable_vectors: unlike LatticeDB this is NOT fixed at creation time
            (the vector table is created lazily), but it is kept in the
            signature so the two backends are constructor-compatible for
            benchmarks and tests.
        enable_fts / enable_fuzzy: present so the spike can measure the
            reopen and ingest cost *of the search indexes themselves* --
            which is the exact axis LatticeDB fails on.
        """
        self.db_path = db_path
        self.read_only = read_only
        self.enable_vectors = enable_vectors
        self.vector_dimensions = vector_dimensions
        self.enable_fts = enable_fts
        self.enable_fuzzy = enable_fuzzy
        self.conn: Optional[sqlite3.Connection] = None
        self._vector_cache: Optional[Tuple[List[Tuple[str, str]], np.ndarray]] = None

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        if not self.read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.read_only:
            uri = f"file:{self.db_path}?mode=ro"
            self.conn = sqlite3.connect(uri, uri=True)
        else:
            self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        if not self.read_only:
            # WAL + NORMAL sync: the standard write-throughput settings. They
            # are durable against process crash, not against OS crash -- an
            # acceptable trade for a rebuildable derived index.
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=OFF")

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
        self.conn = None
        self._vector_cache = None

    def initialize_schema(self) -> None:
        if self.read_only:
            return
        cur = self.conn.cursor()
        for label, cols in NODE_COLUMNS.items():
            pk = NODE_PRIMARY_KEY[label]
            defs = [
                f'"{c}" {t}' + (" PRIMARY KEY" if c == pk else "") for c, t in cols.items()
            ]
            defs.append('"extra_json" TEXT')
            cur.execute(f'CREATE TABLE IF NOT EXISTS "{label}" ({", ".join(defs)})')
            for col in _NODE_INDEXES.get(label, ()):
                cur.execute(
                    f'CREATE INDEX IF NOT EXISTS "ix_{label}_{col}" ON "{label}" ("{col}")'
                )
        for etype, cols in EDGE_COLUMNS.items():
            defs = ['"src" TEXT NOT NULL', '"dst" TEXT NOT NULL']
            defs += [f'"{c}" {t}' for c, t in cols.items()]
            defs.append('"extra_json" TEXT')
            cur.execute(f'CREATE TABLE IF NOT EXISTS "{etype}" ({", ".join(defs)})')
            # MERGE semantics: an edge is identified by (src, dst) *and* its
            # own properties -- CALLS legitimately has parallel edges between
            # the same pair (distinct call sites), which a unique index on
            # (src, dst) alone would collapse. Same reasoning as
            # KuzuBackend.upsert_edges' rel_pattern comment.
            uniq = ", ".join(f'"{c}"' for c in ("src", "dst", *cols))
            cur.execute(
                f'CREATE UNIQUE INDEX IF NOT EXISTS "ux_{etype}" ON "{etype}" ({uniq})'
            )
            cur.execute(f'CREATE INDEX IF NOT EXISTS "ix_{etype}_dst" ON "{etype}" ("dst")')
        if self.enable_fts:
            # A plain (not external-content) FTS5 table: it stores a second
            # copy of search_text. External-content would avoid that but
            # needs triggers per source table and breaks on our upsert path;
            # the duplicate text is a few MB, measured in the benchmark.
            cur.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
                "node_type UNINDEXED, node_id UNINDEXED, name UNINDEXED, "
                "file UNINDEXED, search_text)"
            )
        if self.enable_fuzzy:
            # Typo tolerance, in two stages: FTS5's trigram tokenizer
            # indexes every 3-character substring, which is used purely as a
            # CANDIDATE FILTER (a misspelled token still shares most of its
            # trigrams with the right one), and the candidates are then
            # re-ranked in Python by bounded Levenshtein distance -- see
            # search_text(fuzzy=True).
            #
            # Measured dead end, recorded so nobody repeats it: a plain
            # `search_trgm MATCH '"parze"'` finds NOTHING for "parse". FTS5
            # tokenizes the query into trigrams too and requires them as a
            # contiguous phrase, so the trigram tokenizer on its own is a
            # SUBSTRING index, not a fuzzy one. The per-trigram OR below is
            # what makes it a fuzzy candidate filter.
            #
            # Chosen over spellfix1 (a loadable extension, not stdlib) and
            # rapidfuzz (a new hard dependency).
            # HYPOTHESIS/LIMITATION: a token shorter than 3 characters
            # produces no trigram at all and is dropped from the query, so
            # typos in 1-2 character tokens are invisible to this.
            cur.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS search_trgm USING fts5("
                "node_type UNINDEXED, node_id UNINDEXED, name UNINDEXED, "
                "file UNINDEXED, search_text, tokenize='trigram')"
            )
        if self.enable_vectors:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS node_vectors ("
                "node_type TEXT, node_id TEXT, vec BLOB, "
                "PRIMARY KEY (node_type, node_id))"
            )
        self.conn.commit()

    def detect_schema_version(self) -> str:
        """Always v2: this backend only ever creates the full node/edge set."""
        return "v2"

    # -- ingestion ---------------------------------------------------------

    def upsert_nodes(
        self,
        nodes: Iterable[NodeRecord],
        on_progress: Optional[Callable[[], None]] = None,
        assume_new: bool = False,
    ) -> Dict[Tuple[str, str], int]:
        """Returns {} -- deliberately, like KuzuBackend. Edge endpoints here
        are canonical id strings, so upsert_edges needs no internal-id map;
        building one would cost a lookup per node for no benefit.

        assume_new switches INSERT..ON CONFLICT DO UPDATE for a plain
        INSERT OR REPLACE. Both are one statement; the win is small (SQLite's
        upsert is already a single index probe), unlike LatticeDB where it
        saves a separate find_nodes_by_label_property round trip.
        """
        by_type: Dict[str, List[NodeRecord]] = {}
        for node in nodes:
            if node.type not in NODE_COLUMNS:
                raise ValueError(f"Unknown node type for upsert: {node.type}")
            by_type.setdefault(node.type, []).append(node)

        cur = self.conn.cursor()
        fts_rows: List[Tuple[str, str, str, str, str]] = []
        for label, group in by_type.items():
            cols = list(NODE_COLUMNS[label])
            pk = NODE_PRIMARY_KEY[label]
            placeholders = ", ".join("?" for _ in range(len(cols) + 1))
            collist = ", ".join(f'"{c}"' for c in (*cols, "extra_json"))
            if assume_new:
                stmt = f'INSERT OR REPLACE INTO "{label}" ({collist}) VALUES ({placeholders})'
            else:
                updates = ", ".join(
                    f'"{c}"=excluded."{c}"' for c in (*cols, "extra_json") if c != pk
                )
                stmt = (
                    f'INSERT INTO "{label}" ({collist}) VALUES ({placeholders}) '
                    f'ON CONFLICT("{pk}") DO UPDATE SET {updates}'
                )
            text_col = SEARCHABLE_TEXT_FIELDS.get(label)
            for batch in _chunked(group, _UPSERT_BATCH_SIZE):
                rows = []
                for node in batch:
                    props = node.properties
                    values = [_to_sql(props.get(c)) for c in cols]
                    if values[cols.index(pk)] is None:
                        values[cols.index(pk)] = node.id
                    extra = {k: v for k, v in props.items() if k not in NODE_COLUMNS[label]}
                    values.append(json.dumps(extra) if extra else None)
                    rows.append(values)
                    if text_col and props.get(text_col):
                        fts_rows.append(
                            (
                                label,
                                props.get(pk, node.id),
                                props.get("name") or "",
                                props.get("file") or "",
                                props[text_col],
                            )
                        )
                    if on_progress is not None:
                        on_progress()
                cur.executemany(stmt, rows)
                self.conn.commit()

        if fts_rows:
            self._index_text(cur, fts_rows, replace=not assume_new)
            self.conn.commit()
        return {}

    def _index_text(self, cur, rows, replace: bool) -> None:
        if replace:
            # FTS5 has no upsert: delete-then-insert per node id. Cheap here
            # because re-ingest volume is small; a full rebuild uses
            # assume_new=True and skips this entirely.
            ids = [(r[0], r[1]) for r in rows]
            for tbl in self._text_tables():
                for batch in _chunked(ids, _UPSERT_BATCH_SIZE):
                    cur.executemany(
                        f"DELETE FROM {tbl} WHERE node_type = ? AND node_id = ?", batch
                    )
        for tbl in self._text_tables():
            for batch in _chunked(rows, _UPSERT_BATCH_SIZE):
                cur.executemany(
                    f"INSERT INTO {tbl} (node_type, node_id, name, file, search_text) "
                    "VALUES (?, ?, ?, ?, ?)",
                    batch,
                )

    def _text_tables(self) -> List[str]:
        tables = []
        if self.enable_fts:
            tables.append("search_fts")
        if self.enable_fuzzy:
            tables.append("search_trgm")
        return tables

    def upsert_edges(
        self,
        edges: Iterable[EdgeRecord],
        on_progress: Optional[Callable[[], None]] = None,
        node_id_map: Optional[Dict[Tuple[str, str], int]] = None,
    ) -> None:
        """node_id_map is accepted and ignored (same as KuzuBackend): edge
        rows store the canonical ids directly, so there is no endpoint
        resolution to skip.

        HYPOTHESIS/LIMITATION: unlike Kuzu/LatticeDB this does NOT verify
        that both endpoints exist -- there are no foreign keys, so a dangling
        edge is silently storable. Every read path joins through the node
        table, so a dangling edge is invisible to queries rather than
        corrupting them; the visible difference is that
        LatticeBackend.upsert_edges raises "endpoint node not found" where
        this one quietly stores the row.
        """
        by_type: Dict[str, List[EdgeRecord]] = {}
        for edge in edges:
            if edge.type not in EDGE_COLUMNS:
                raise ValueError(f"Unknown edge type for upsert: {edge.type}")
            by_type.setdefault(edge.type, []).append(edge)

        cur = self.conn.cursor()
        for etype, group in by_type.items():
            cols = list(EDGE_COLUMNS[etype])
            collist = ", ".join(f'"{c}"' for c in ("src", "dst", *cols, "extra_json"))
            placeholders = ", ".join("?" for _ in range(len(cols) + 3))
            stmt = f'INSERT OR IGNORE INTO "{etype}" ({collist}) VALUES ({placeholders})'
            for batch in _chunked(group, _UPSERT_BATCH_SIZE):
                rows = []
                for edge in batch:
                    values = [edge.src_id, edge.dst_id]
                    values += [_to_sql(edge.properties.get(c)) for c in cols]
                    extra = {
                        k: v for k, v in edge.properties.items() if k not in EDGE_COLUMNS[etype]
                    }
                    values.append(json.dumps(extra) if extra else None)
                    rows.append(values)
                    if on_progress is not None:
                        on_progress()
                cur.executemany(stmt, rows)
                self.conn.commit()

    def delete_file(self, file_key: str) -> None:
        cur = self.conn.cursor()
        # Collect the canonical ids owned by this file first, then delete
        # every edge touching them, then the nodes -- SQLite has no
        # DETACH DELETE, and dropping the nodes first would leave edges
        # whose endpoints can no longer be identified.
        owned: Dict[str, List[str]] = {}
        for label in FILE_SCOPED_NODE_TYPES:
            pk = NODE_PRIMARY_KEY[label]
            owned[label] = [
                r[0]
                for r in cur.execute(
                    f'SELECT "{pk}" FROM "{label}" WHERE "file" = ?', (file_key,)
                )
            ]
        owned["File"] = [file_key]

        for etype, (src_type, dst_type) in EDGE_ENDPOINT_TYPES.items():
            for endpoint, label in (("src", src_type), ("dst", dst_type)):
                ids = owned.get(label)
                if not ids:
                    continue
                for batch in _chunked(ids, 500):
                    marks = ", ".join("?" for _ in batch)
                    cur.execute(
                        f'DELETE FROM "{etype}" WHERE "{endpoint}" IN ({marks})',
                        list(batch),
                    )
        for label, ids in owned.items():
            if not ids:
                continue
            pk = NODE_PRIMARY_KEY[label]
            for batch in _chunked(ids, 500):
                marks = ", ".join("?" for _ in batch)
                cur.execute(f'DELETE FROM "{label}" WHERE "{pk}" IN ({marks})', list(batch))
            for tbl in self._text_tables():
                for batch in _chunked(ids, 500):
                    marks = ", ".join("?" for _ in batch)
                    cur.execute(
                        f"DELETE FROM {tbl} WHERE node_type = ? AND node_id IN ({marks})",
                        [label, *batch],
                    )
            if self.enable_vectors:
                for batch in _chunked(ids, 500):
                    marks = ", ".join("?" for _ in batch)
                    cur.execute(
                        f"DELETE FROM node_vectors WHERE node_type = ? AND node_id IN ({marks})",
                        [label, *batch],
                    )
        self.conn.commit()
        self._vector_cache = None

    def clear_all(self) -> None:
        cur = self.conn.cursor()
        for label in NODE_COLUMNS:
            cur.execute(f'DELETE FROM "{label}"')
        for etype in EDGE_COLUMNS:
            cur.execute(f'DELETE FROM "{etype}"')
        for tbl in self._text_tables():
            cur.execute(f"DELETE FROM {tbl}")
        if self.enable_vectors:
            cur.execute("DELETE FROM node_vectors")
        self.conn.commit()
        self._vector_cache = None

    # -- raw query escape hatch -------------------------------------------

    def query(
        self, statement: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Run a statement from the restricted Cypher subset (see
        _CypherToSQL). Raises CypherSubsetError for anything outside it --
        never a best-effort partial translation.
        """
        params = params or {}
        flat = " ".join(statement.split())

        if re.search(r"\bDETACH\s+DELETE\b", flat, re.I):
            m = _NODE_RE.search(flat)
            label = m.group("label") if m else None
            if label not in NODE_COLUMNS:
                raise CypherSubsetError(f"Unsupported DETACH DELETE: {statement!r}")
            pk = NODE_PRIMARY_KEY[label]
            cur = self.conn.cursor()
            props = _CypherToSQL(flat, params)._parse_props(m.group("props"))
            if props:
                where = " AND ".join(f"{p} = {v}" for p, v in props)
                ids = [
                    r[0]
                    for r in cur.execute(f'SELECT "{pk}" FROM "{label}" WHERE {where}', params)
                ]
            else:
                ids = [r[0] for r in cur.execute(f'SELECT "{pk}" FROM "{label}"')]
            for etype, (src_type, dst_type) in EDGE_ENDPOINT_TYPES.items():
                for endpoint, elabel in (("src", src_type), ("dst", dst_type)):
                    if elabel != label:
                        continue
                    for batch in _chunked(ids, 500):
                        marks = ", ".join("?" for _ in batch)
                        cur.execute(
                            f'DELETE FROM "{etype}" WHERE "{endpoint}" IN ({marks})',
                            list(batch),
                        )
            for batch in _chunked(ids, 500):
                marks = ", ".join("?" for _ in batch)
                cur.execute(f'DELETE FROM "{label}" WHERE "{pk}" IN ({marks})', list(batch))
                for tbl in self._text_tables():
                    cur.execute(
                        f"DELETE FROM {tbl} WHERE node_type = ? AND node_id IN ({marks})",
                        [label, *batch],
                    )
            self.conn.commit()
            return []

        if "COLLECT(" in flat.upper() and "DECORATED_BY" in flat.upper():
            sql, sql_params, origins = _MULTI_DECORATOR_SQL, {}, {}
            rows = self.conn.execute(sql, sql_params).fetchall()
            out = []
            for row in rows:
                d = dict(row)
                # COLLECT() returns a list in Cypher; group_concat returns a
                # comma-joined string. Split it back so callers see a list.
                d["decorators"] = d["decorators"].split(",") if d["decorators"] else []
                out.append(d)
            return out

        translator = _CypherToSQL(flat, params)
        sql, sql_params, origins = translator.translate()
        rows = self.conn.execute(sql, sql_params).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            for col, origin in origins.items():
                if _BOOL_COLUMNS.get(origin) and d.get(col) is not None:
                    d[col] = bool(d[col])
            out.append(d)
        return out

    # -- typed graph reads -------------------------------------------------

    def get_call_edges_with_lines(
        self, function_canonical_id: str
    ) -> Tuple[
        List[Tuple[str, str, int, int, int]], List[Tuple[str, str, int, int, int]]
    ]:
        """Two index-backed joins. Unlike LatticeDB there is no
        planner-vs-imperative gap to work around: `CALLS.dst`/`CALLS.src` are
        indexed, so this is a b-tree probe plus a PK lookup per hit.
        """
        cur = self.conn.cursor()
        callers = [
            (r["file"], r["name"], r["call_line"], r["start_line"], r["end_line"])
            for r in cur.execute(
                'SELECT f.file AS file, f.name AS name, c.call_line AS call_line, '
                'f.start_line AS start_line, f.end_line AS end_line '
                'FROM "CALLS" c JOIN "Function" f ON f.id = c.src WHERE c.dst = ?',
                (function_canonical_id,),
            )
        ]
        callees = [
            (r["file"], r["name"], r["call_line"], r["start_line"], r["end_line"])
            for r in cur.execute(
                'SELECT f.file AS file, f.name AS name, c.call_line AS call_line, '
                'f.start_line AS start_line, f.end_line AS end_line '
                'FROM "CALLS" c JOIN "Function" f ON f.id = c.dst WHERE c.src = ?',
                (function_canonical_id,),
            )
        ]
        return callers, callees

    def get_most_called_functions(self, limit: int = 20) -> List[Tuple[str, str, int]]:
        """Groups by (name, file), matching Cypher's group-by-returned-columns
        semantics -- see CodeGraphBackend's docstring for why per-node counts
        would silently drop same-named functions.
        """
        rows = self.conn.execute(
            'SELECT f.name AS name, f.file AS file, COUNT(*) AS n '
            'FROM "CALLS" c JOIN "Function" f ON f.id = c.dst '
            'GROUP BY f.name, f.file ORDER BY n DESC, f.name ASC LIMIT ?',
            (limit,),
        ).fetchall()
        return [(r["name"], r["file"], r["n"]) for r in rows]

    # -- search ------------------------------------------------------------

    def search_text(
        self,
        query: str,
        node_types: Optional[List[str]] = None,
        limit: int = 10,
        fuzzy: bool = False,
    ) -> List[SearchResult]:
        """BM25 via FTS5's built-in bm25() ranking function.

        fuzzy=True switches to the trigram index used as a candidate filter
        plus a bounded-Levenshtein re-rank in Python (see _search_fuzzy).
        Scores from the two modes are NOT comparable: exact mode returns a
        flipped bm25() relevance, fuzzy mode returns a similarity derived
        from edit distance.
        """
        if fuzzy:
            if not self.enable_fuzzy:
                raise NotImplementedError(
                    "fuzzy search requires this backend to be opened with "
                    "enable_fuzzy=True (it needs the trigram FTS5 index)"
                )
            return self._search_fuzzy(query, node_types, limit)
        if not self.enable_fts:
            raise NotImplementedError(
                "search_text requires this backend to be opened with enable_fts=True"
            )
        table = "search_fts"
        types = node_types if node_types is not None else list(SEARCHABLE_TEXT_FIELDS)
        types = [t for t in types if t in SEARCHABLE_TEXT_FIELDS]
        if not types:
            return []

        match = _fts_match_expression(query)
        if not match:
            return []
        marks = ", ".join("?" for _ in types)
        sql = (
            f"SELECT node_type, node_id, name, file, bm25({table}) AS score "
            f"FROM {table} WHERE {table} MATCH ? AND node_type IN ({marks}) "
            f"ORDER BY score LIMIT ?"
        )
        try:
            rows = self.conn.execute(sql, [match, *types, limit]).fetchall()
        except sqlite3.OperationalError as exc:
            # An unparseable FTS5 MATCH expression (stray quote, bare NEAR,
            # etc.) -- report no hits rather than crashing the CLI, same
            # user-visible behaviour as a query that matches nothing.
            if "fts5" not in str(exc).lower() and "syntax" not in str(exc).lower():
                raise
            return []
        # bm25() returns a NEGATIVE number (more negative = better). The
        # SearchResult contract says higher = more relevant, so flip the sign
        # to match LatticeBackend's convention.
        return [
            SearchResult(
                node_id=r["node_id"],
                node_type=r["node_type"],
                name=r["name"],
                file=r["file"],
                score=-r["score"],
            )
            for r in rows
        ]

    # Candidates pulled from the trigram index before the Levenshtein
    # re-rank. Big enough that the right answer is almost always in the
    # shortlist, small enough that the Python rescoring stays sub-10ms.
    FUZZY_CANDIDATE_POOL = 300
    FUZZY_MAX_DISTANCE = 2

    def _search_fuzzy(
        self, query: str, node_types: Optional[List[str]], limit: int
    ) -> List[SearchResult]:
        """Typo-tolerant search: trigram shortlist, then bounded Levenshtein.

        Stage 1 ORs every trigram of every query token against the trigram
        index, so a misspelled token still retrieves documents containing the
        correctly spelled one. Stage 2 rescores each candidate by the best
        edit distance between any query token and any token of the
        candidate's name/search_text, keeping only distances <=
        FUZZY_MAX_DISTANCE (matching LatticeBackend's fts_search_fuzzy
        max_distance=2).

        HYPOTHESIS/LIMITATION: recall is bounded by FUZZY_CANDIDATE_POOL. A
        typo whose trigrams are common across the corpus can push the true
        match out of the shortlist, in which case this returns fewer/worse
        hits rather than being wrong -- a recall failure, not a correctness
        one. Tokens under 3 characters produce no trigrams and are dropped.
        """
        types = node_types if node_types is not None else list(SEARCHABLE_TEXT_FIELDS)
        types = [t for t in types if t in SEARCHABLE_TEXT_FIELDS]
        if not types:
            return []
        tokens = [t.lower() for t in _FTS_SPECIAL.split(query) if len(t) >= 3]
        if not tokens:
            return []
        grams = sorted({t[i : i + 3] for t in tokens for i in range(len(t) - 2)})
        match = " OR ".join(f'"{g}"' for g in grams)
        marks = ", ".join("?" for _ in types)
        rows = self.conn.execute(
            "SELECT node_type, node_id, name, file, search_text, "
            "bm25(search_trgm) AS score FROM search_trgm "
            f"WHERE search_trgm MATCH ? AND node_type IN ({marks}) "
            "ORDER BY score LIMIT ?",
            [match, *types, self.FUZZY_CANDIDATE_POOL],
        ).fetchall()

        scored: List[Tuple[float, sqlite3.Row]] = []
        for row in rows:
            cand_tokens = {
                t.lower()
                for t in _FTS_SPECIAL.split(f"{row['name']} {row['search_text']}")
                if t
            }
            total = 0.0
            matched = 0
            for qt in tokens:
                best = min(
                    (_bounded_levenshtein(qt, ct, self.FUZZY_MAX_DISTANCE) for ct in cand_tokens),
                    default=self.FUZZY_MAX_DISTANCE + 1,
                )
                if best <= self.FUZZY_MAX_DISTANCE:
                    matched += 1
                    total += best
            if matched == 0:
                continue
            # Similarity: reward matching more query tokens, penalise the
            # accumulated edit distance. Higher = better, like BM25.
            scored.append((matched - total / (len(tokens) * (self.FUZZY_MAX_DISTANCE + 1)), row))
        scored.sort(key=lambda s: s[0], reverse=True)
        return [
            SearchResult(
                node_id=row["node_id"],
                node_type=row["node_type"],
                name=row["name"],
                file=row["file"],
                score=float(score),
            )
            for score, row in scored[:limit]
        ]

    def build_vector_index(
        self,
        node_types: Optional[List[str]] = None,
        model: str = DEFAULT_MODEL,
        on_progress: Optional[Callable[[], None]] = None,
        node_ids: Optional[Iterable[str]] = None,
    ) -> int:
        """Embed each searchable node's search_text and store the vector as a
        float32 BLOB. Same Ollama batching as LatticeBackend.

        node_ids here are CANONICAL ids (strings), not internal ints -- this
        backend has no internal node id. That is a real signature divergence
        from LatticeBackend.build_vector_index; it is not part of the
        CodeGraphBackend Protocol, so nothing type-checks against it, but a
        caller written for LatticeBackend would pass the wrong thing.
        """
        if not self.enable_vectors:
            raise RuntimeError(
                "build_vector_index requires a SqliteBackend opened with enable_vectors=True"
            )
        cur = self.conn.cursor()
        types = node_types if node_types is not None else list(SEARCHABLE_TEXT_FIELDS)
        count = 0
        for label in types:
            text_col = SEARCHABLE_TEXT_FIELDS.get(label)
            if text_col is None:
                continue
            pk = NODE_PRIMARY_KEY[label]
            sql = f'SELECT "{pk}" AS nid, "{text_col}" AS txt FROM "{label}" WHERE "{text_col}" IS NOT NULL AND "{text_col}" != \'\''
            params: List[Any] = []
            if node_ids is not None:
                ids = list(node_ids)
                if not ids:
                    continue
                marks = ", ".join("?" for _ in ids)
                sql += f' AND "{pk}" IN ({marks})'
                params = ids
            pending = cur.execute(sql, params).fetchall()
            for batch in _chunked(pending, _EMBED_BATCH_SIZE):
                vectors = embed_texts([r["txt"] for r in batch], model=model)
                self.conn.executemany(
                    "INSERT OR REPLACE INTO node_vectors (node_type, node_id, vec) VALUES (?, ?, ?)",
                    [
                        (label, r["nid"], np.asarray(v, dtype=np.float32).tobytes())
                        for r, v in zip(batch, vectors)
                    ],
                )
                count += len(batch)
                if on_progress is not None:
                    for _ in batch:
                        on_progress()
            self.conn.commit()
        self._vector_cache = None
        return count

    def _load_vectors(self) -> Tuple[List[Tuple[str, str]], np.ndarray]:
        """Load every stored vector into one (N, D) float32 matrix, cached
        per open connection.

        HYPOTHESIS: at this project's scale (~15k x 768 = ~46MB) reading the
        whole matrix once per process is cheaper than any index, and a single
        numpy matmul dominates any per-vector Python loop. The cost that this
        hides is the FIRST search_vector() call in a process, which pays the
        whole load -- measured in perfo/benchmark_sqlite_backend.py. It stops
        being viable somewhere around a few hundred thousand vectors, where
        sqlite-vec (optional, not required) or a real ANN index takes over.
        """
        if self._vector_cache is not None:
            return self._vector_cache
        keys: List[Tuple[str, str]] = []
        blobs: List[bytes] = []
        for r in self.conn.execute("SELECT node_type, node_id, vec FROM node_vectors"):
            keys.append((r["node_type"], r["node_id"]))
            blobs.append(r["vec"])
        if not blobs:
            matrix = np.zeros((0, self.vector_dimensions), dtype=np.float32)
        else:
            matrix = np.frombuffer(b"".join(blobs), dtype=np.float32).reshape(
                len(blobs), -1
            )
        self._vector_cache = (keys, matrix)
        return self._vector_cache

    def search_vector(
        self,
        query_text: str,
        node_types: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[SearchResult]:
        """Brute-force cosine distance over every stored vector.

        `score` is a DISTANCE (lower = more similar), matching
        LatticeBackend.search_vector's contract, not search_text's
        higher-is-better BM25 score.
        """
        if not self.enable_vectors:
            raise RuntimeError(
                "search_vector requires a SqliteBackend opened with enable_vectors=True"
            )
        keys, matrix = self._load_vectors()
        if matrix.shape[0] == 0:
            return []
        q = np.asarray(embed_text(query_text), dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = 1.0
        sims = (matrix @ q) / (norms * (np.linalg.norm(q) or 1.0))
        distances = 1.0 - sims

        wanted = set(node_types) if node_types is not None else None
        order = np.argsort(distances)
        results: List[SearchResult] = []
        cur = self.conn.cursor()
        for idx in order:
            label, nid = keys[idx]
            if wanted is not None and label not in wanted:
                continue
            pk = NODE_PRIMARY_KEY[label]
            row = cur.execute(
                f'SELECT name, file FROM "{label}" WHERE "{pk}" = ?', (nid,)
            ).fetchone()
            if row is None:
                continue
            results.append(
                SearchResult(
                    node_id=nid,
                    node_type=label,
                    name=row["name"] or "",
                    file=row["file"] or "",
                    score=float(distances[idx]),
                )
            )
            if len(results) >= limit:
                break
        return results

    # -- maintenance -------------------------------------------------------

    def optimize(self) -> None:
        """ANALYZE + FTS5 optimize + VACUUM. Not called during ingest --
        exposed so the benchmark can measure its cost and its effect on
        database size separately from ingest wall time.
        """
        cur = self.conn.cursor()
        for tbl in self._text_tables():
            cur.execute(f"INSERT INTO {tbl}({tbl}) VALUES('optimize')")
        cur.execute("ANALYZE")
        self.conn.commit()
        cur.execute("VACUUM")


def _to_sql(value: Any) -> Any:
    """Map a NodeRecord/EdgeRecord property value to a SQLite storage class.

    bool -> int (SQLite has no boolean), list/dict -> JSON text (the only
    non-scalar the extractors produce today is Class.bases, which
    graph/ingest.py already flattens to a string before it reaches here).
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return value


_FTS_SPECIAL = re.compile(r"[^\w]+", re.UNICODE)


def _bounded_levenshtein(a: str, b: str, max_distance: int) -> int:
    """Levenshtein distance, short-circuiting at max_distance + 1.

    Pure Python on purpose (no rapidfuzz dependency) -- it only ever runs
    over the trigram shortlist, not the whole corpus. The length check below
    is what keeps it cheap: most candidate tokens differ in length by more
    than max_distance and are rejected without any DP work at all.
    """
    if abs(len(a) - len(b)) > max_distance:
        return max_distance + 1
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        if min(current) > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]


def _fts_match_expression(query: str) -> str:
    """Turn a free-text query into a safe FTS5 MATCH expression.

    Every token is quoted, so FTS5 operators a user happens to type (AND, OR,
    NEAR, ^, *, ") are treated as literal text rather than syntax. Tokens are
    OR-ed: an all-AND query returns nothing for the multi-word natural
    language queries this search is meant for.

    HYPOTHESIS: OR-ing lets bm25() do the ranking (a document matching all
    terms outranks one matching a single term), which matches how the
    LatticeDB path behaved in practice. It does mean a two-word query can
    return hits containing only the commoner word -- acceptable for a ranked
    top-N, wrong if a caller expected conjunctive filtering.
    """
    tokens = [t for t in _FTS_SPECIAL.split(query) if t]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)

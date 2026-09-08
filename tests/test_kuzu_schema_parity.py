"""Guard against schema.py and bulk_loader.py's node table DDLs diverging.

Two independent, hand-maintained `CREATE NODE TABLE` definitions exist for
the same Kuzu tables: `SchemaManager.create_schema` (schema.py, used by
`KuzuBackend.initialize_schema`) and `create_schema` (bulk_loader.py, used
by the COPY FROM bulk-load path `analyze` actually runs through). This is
exactly the class of bug fixed this session: schema.py once declared a
`search_text` column on Function/Class that bulk_loader.py's Parquet export
never wrote, which surfaced as a Kuzu `Binder exception: Number of columns
mismatch` (see test_kuzu_bulk_load_schema.py) -- but only when
`SchemaManager.create_schema`'s definition was the one that ended up
persisted on disk, which is timing-sensitive (depends on open/close
ordering between the two `kuzu.Database` handles involved). Comparing the
DDL text directly catches the divergence unconditionally, regardless of
that race.
"""

import re
from pathlib import Path

_TABLE_RE = re.compile(
    r"CREATE NODE TABLE IF NOT EXISTS (\w+)\((.*?)\n\s*\)", re.S
)


def _parse_tables(text: str) -> dict:
    tables = {}
    for match in _TABLE_RE.finditer(text):
        name, body = match.group(1), match.group(2)
        columns = []
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.upper().startswith("PRIMARY KEY"):
                continue
            columns.append(line.split()[0])
        tables[name] = columns
    return tables


def test_shared_node_tables_have_identical_columns_in_both_schemas() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    schema_text = (
        repo_root / "src" / "code_explorer" / "graph" / "schema.py"
    ).read_text(encoding="utf-8")
    bulk_loader_text = (
        repo_root / "src" / "code_explorer" / "graph" / "bulk_loader.py"
    ).read_text(encoding="utf-8")

    schema_tables = _parse_tables(schema_text)
    bulk_loader_tables = _parse_tables(bulk_loader_text)

    assert bulk_loader_tables, "regex found no tables in bulk_loader.py -- DDL format changed?"
    assert schema_tables, "regex found no tables in schema.py -- DDL format changed?"

    shared = set(schema_tables) & set(bulk_loader_tables)
    assert shared, "expected at least File/Function/Class in both files"

    mismatches = {
        name: (schema_tables[name], bulk_loader_tables[name])
        for name in sorted(shared)
        if schema_tables[name] != bulk_loader_tables[name]
    }
    assert not mismatches, (
        "schema.py and bulk_loader.py disagree on these tables' columns "
        f"(schema.py, bulk_loader.py): {mismatches}"
    )

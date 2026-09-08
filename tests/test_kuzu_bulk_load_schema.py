"""Regression test for the Kuzu Function/Class COPY FROM schema mismatch.

`schema.py`'s SchemaManager (used by KuzuBackend, the default `analyze`
backend) once created Function/Class node tables with an extra `search_text`
column that the Parquet exporter (`analyzer/export_parquet.py`) never wrote
and KuzuBackend never populated or queried (`search_text` is a
NotImplementedError there -- BM25 lives on the sqlite backend instead). The
mismatch made every `COPY FROM` for Function/Class -- and every edge table
referencing them (CONTAINS_FUNCTION, CONTAINS_CLASS, METHOD_OF, CALLS) --
fail silently: `analyze` reported success, but `stats`/`trace`/`visualize`
saw zero functions and classes.
"""

from pathlib import Path

from click.testing import CliRunner

from code_explorer.cli import cli
from code_explorer.graph.graph import DependencyGraph


def test_analyze_loads_functions_and_classes_into_kuzu(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "module.py").write_text(
        "def helper(x):\n"
        "    return x + 1\n"
        "\n"
        "\n"
        "def my_function(a, b):\n"
        "    return helper(a) + b\n"
        "\n"
        "\n"
        "class Foo:\n"
        "    def method(self):\n"
        "        return my_function(1, 2)\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "graph.db"
    result = CliRunner().invoke(
        cli, ["analyze", str(project), "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    assert "Failed to load" not in result.output

    graph = DependencyGraph(db_path=db_path, read_only=True)
    try:
        function_count = graph.backend.query(
            "MATCH (f:Function) RETURN COUNT(f) AS c"
        )[0]["c"]
        class_count = graph.backend.query("MATCH (c:Class) RETURN COUNT(c) AS c")[0][
            "c"
        ]
        calls_count = graph.backend.query(
            "MATCH ()-[r:CALLS]->() RETURN COUNT(r) AS c"
        )[0]["c"]
    finally:
        graph.backend.close()

    # helper, my_function, Foo.method
    assert function_count == 3
    assert class_count == 1
    # my_function -> helper, Foo.method -> my_function
    assert calls_count == 2

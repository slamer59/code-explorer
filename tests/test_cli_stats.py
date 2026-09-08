"""CLI-level tests for `code-explorer stats`.

Real backend, no mocking: `analyze` then `stats` against the actual Kuzu
graph, asserting on the graph's own data (via a direct query) rather than
parsing rendered table stdout -- this is exactly the kind of test that would
have caught the Function/Class COPY FROM schema mismatch fixed this session
(see test_kuzu_bulk_load_schema.py).
"""

from pathlib import Path

from click.testing import CliRunner

from code_explorer.cli import cli
from code_explorer.graph.graph import DependencyGraph


def _analyze(project: Path, db_path: Path) -> None:
    result = CliRunner().invoke(
        cli, ["analyze", str(project), "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output


def test_stats_reports_real_function_and_class_counts(
    sample_python_file: Path, tmp_path: Path
) -> None:
    project = sample_python_file.parent
    db_path = tmp_path / "graph.db"
    _analyze(project, db_path)

    graph = DependencyGraph(db_path=db_path, read_only=True)
    try:
        function_count = graph.backend.query(
            "MATCH (f:Function) RETURN COUNT(f) AS c"
        )[0]["c"]
        class_count = graph.backend.query("MATCH (c:Class) RETURN COUNT(c) AS c")[0][
            "c"
        ]
    finally:
        graph.backend.close()

    # public_function, _private_function, caller_function, method_one, method_two
    assert function_count == 5
    assert class_count == 1

    result = CliRunner().invoke(cli, ["stats", "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "5" in result.output
    assert "1" in result.output


def test_stats_top_flag_does_not_crash_on_truncation(
    sample_python_file: Path, tmp_path: Path
) -> None:
    project = sample_python_file.parent
    db_path = tmp_path / "graph.db"
    _analyze(project, db_path)

    result = CliRunner().invoke(
        cli, ["stats", "--db-path", str(db_path), "--top", "1"]
    )
    assert result.exit_code == 0, result.output


def test_stats_without_prior_analyze_reports_missing_database(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "does-not-exist.db"

    result = CliRunner().invoke(cli, ["stats", "--db-path", str(db_path)])

    assert result.exit_code == 1
    assert "Run 'analyze' command first" in result.output

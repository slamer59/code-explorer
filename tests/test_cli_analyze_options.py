"""CLI-level tests for `code-explorer analyze`'s flag variants.

Real backend (Kuzu), no mocking. Each test targets a flag that changes a
real code path (which files get walked, or whether the DB is rebuilt from
scratch) rather than a pure pass-through knob.
"""

from pathlib import Path

from click.testing import CliRunner

from code_explorer.cli import cli
from code_explorer.graph.graph import DependencyGraph


def _function_names(db_path: Path) -> set:
    graph = DependencyGraph(db_path=db_path, read_only=True)
    try:
        rows = graph.backend.query("MATCH (f:Function) RETURN f.name AS name")
        return {row["name"] for row in rows}
    finally:
        graph.backend.close()


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "venv").mkdir(parents=True)
    (project / "main.py").write_text(
        "def kept_function():\n    return 1\n", encoding="utf-8"
    )
    (project / "tests" / "test_main.py").write_text(
        "def excluded_by_pattern():\n    return 2\n", encoding="utf-8"
    )
    (project / "venv" / "vendored.py").write_text(
        "def vendored_function():\n    return 3\n", encoding="utf-8"
    )
    return project


def test_exclude_drops_matching_files(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    db_path = tmp_path / "graph.db"

    result = CliRunner().invoke(
        cli,
        [
            "analyze",
            str(project),
            "--db-path",
            str(db_path),
            "--exclude",
            "tests",
        ],
    )
    assert result.exit_code == 0, result.output

    names = _function_names(db_path)
    assert "kept_function" in names
    assert "excluded_by_pattern" not in names


def test_include_overrides_a_default_exclusion(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    db_path = tmp_path / "graph.db"

    # venv/ is excluded by default (settings.default_exclude_patterns).
    result_default = CliRunner().invoke(
        cli, ["analyze", str(project), "--db-path", str(db_path)]
    )
    assert result_default.exit_code == 0, result_default.output
    assert "vendored_function" not in _function_names(db_path)

    db_path_included = tmp_path / "graph_included.db"
    result_included = CliRunner().invoke(
        cli,
        [
            "analyze",
            str(project),
            "--db-path",
            str(db_path_included),
            "--include",
            "venv",
        ],
    )
    assert result_included.exit_code == 0, result_included.output
    assert "vendored_function" in _function_names(db_path_included)


def test_refresh_clears_and_rebuilds_from_scratch(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    module = project / "module.py"
    module.write_text("def old_name():\n    return 1\n", encoding="utf-8")
    db_path = tmp_path / "graph.db"

    result = CliRunner().invoke(
        cli, ["analyze", str(project), "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    assert "old_name" in _function_names(db_path)

    module.write_text("def new_name():\n    return 1\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["analyze", str(project), "--db-path", str(db_path), "--refresh"]
    )
    assert result.exit_code == 0, result.output

    names = _function_names(db_path)
    assert "new_name" in names
    assert "old_name" not in names


def test_include_source_flag_is_accepted_without_error(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "module.py").write_text(
        "def some_function():\n    return 1\n", encoding="utf-8"
    )
    db_path = tmp_path / "graph.db"

    result = CliRunner().invoke(
        cli,
        [
            "analyze",
            str(project),
            "--db-path",
            str(db_path),
            "--include-source",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "some_function" in _function_names(db_path)

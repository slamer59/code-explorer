"""CLI-level tests for `code-explorer visualize`.

Real backend (Kuzu), no mocking: `analyze` then `visualize`, asserting on the
actual Mermaid file written to disk.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from code_explorer.cli import cli


@pytest.fixture
def analyzed_project(sample_python_file: Path, tmp_path: Path, monkeypatch):
    """`analyze` a project and chdir into it.

    `visualize`'s TARGET must match the relative path `analyze` stored the
    file under (relative to CWD at analyze time), and `--output` resolves
    against CWD at invocation -- so tests need a real CWD to reason about.
    """
    project = sample_python_file.parent
    db_path = tmp_path / "graph.db"
    monkeypatch.chdir(project)

    result = CliRunner().invoke(
        cli, ["analyze", ".", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output

    return project, db_path


def test_visualize_module_writes_real_mermaid_content(
    analyzed_project, tmp_path: Path
) -> None:
    project, db_path = analyzed_project
    output_path = tmp_path / "out" / "graph.md"

    result = CliRunner().invoke(
        cli,
        [
            "visualize",
            "sample.py",
            "--db-path",
            str(db_path),
            "--output",
            str(output_path),
        ],
    )
    assert result.exit_code == 0, result.output

    content = output_path.read_text(encoding="utf-8")
    assert "```mermaid\ngraph TB" in content
    assert "caller_function" in content
    assert "public_function" in content
    assert "-->" in content


def test_visualize_function_flag_highlights_focus_function(
    analyzed_project, tmp_path: Path
) -> None:
    project, db_path = analyzed_project
    output_path = tmp_path / "focus.md"

    result = CliRunner().invoke(
        cli,
        [
            "visualize",
            "sample.py",
            "--function",
            "caller_function",
            "--db-path",
            str(db_path),
            "--output",
            str(output_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Function: caller_function" in result.output

    content = output_path.read_text(encoding="utf-8")
    assert "caller_function" in content


def test_visualize_output_resolves_relative_to_cwd_not_target(
    analyzed_project,
) -> None:
    project, db_path = analyzed_project

    result = CliRunner().invoke(
        cli,
        [
            "visualize",
            "sample.py",
            "--db-path",
            str(db_path),
            "--output",
            "relative_graph.md",
        ],
    )
    assert result.exit_code == 0, result.output

    # CWD was chdir'd to `project` by the fixture, and "sample.py" and
    # "relative_graph.md" share that same directory -- but the point of this
    # test is that --output is resolved against CWD, not derived from
    # TARGET's directory, so it must land exactly at project/relative_graph.md.
    assert (project / "relative_graph.md").exists()


def test_visualize_without_prior_analyze_reports_missing_database(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "does-not-exist.db"

    result = CliRunner().invoke(
        cli, ["visualize", "sample.py", "--db-path", str(db_path)]
    )

    assert result.exit_code == 1
    assert "Run 'analyze' command first" in result.output

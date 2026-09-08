"""CLI-level tests for `code-explorer impact`.

Real backend (sqlite by default, lattice as an alternative), no mocking.
`impact` builds/updates its own search index on demand -- no prior `analyze`
needed. Follows `test_cli_json_output.py`'s `indexed_project` convention of
`git init`-ing the fixture project before invoking index-building commands.
"""

from pathlib import Path
import subprocess

import pytest
from click.testing import CliRunner

from code_explorer.cli import cli


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "module.py").write_text(
        "def helper(x):\n"
        "    return x + 1\n"
        "\n"
        "\n"
        "def my_function(a, b):\n"
        "    return helper(a) + b\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    return root


@pytest.fixture
def project_with_long_callee(tmp_path: Path) -> Path:
    """A callee long enough that a mid-size budget degrades it to a
    signature instead of excluding it outright (see test_impact_small_budget)."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "module.py").write_text(
        "def helper(x):\n"
        '    """A helper with a longer body so it costs more tokens than the seed."""\n'
        "    total = 0\n"
        "    for i in range(10):\n"
        "        total += x + i\n"
        "        total -= 1\n"
        "        total *= 2\n"
        "        total //= 2\n"
        "    return total\n"
        "\n"
        "\n"
        "def my_function(a, b):\n"
        "    return helper(a) + b\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    return root


def test_impact_both_directions(project: Path) -> None:
    result = CliRunner().invoke(
        cli, ["impact", "module.py:my_function", str(project), "--names-only"]
    )
    assert result.exit_code == 0, result.output
    assert "helper" in result.output


def test_impact_downstream_only_excludes_callers(project: Path) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "module.py:helper",
            str(project),
            "--downstream",
            "--names-only",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "my_function" not in result.output


def test_impact_upstream_only_excludes_callees(project: Path) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "module.py:my_function",
            str(project),
            "--upstream",
            "--names-only",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "helper" not in result.output


def test_impact_small_budget_degrades_to_signature_only(
    project_with_long_callee: Path,
) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "module.py:my_function",
            str(project_with_long_callee),
            "--budget",
            "60",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "signature only" in result.output


@pytest.mark.parametrize(
    "backend,index_glob",
    [("sqlite", "graph.sqlite"), ("lattice", "graph.lattice")],
)
def test_impact_backend_choice_builds_matching_index(
    project: Path, backend: str, index_glob: str
) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "module.py:my_function",
            str(project),
            "--backend",
            backend,
            "--names-only",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (project / ".code-explorer" / index_glob).exists()

"""Tests for fast, ignore-aware source-file discovery."""

import subprocess

from code_explorer.analyzer.base_analyzer import discover_python_files


def test_discovery_respects_gitignore_and_default_exclusions(temp_dir):
    subprocess.run(
        ["git", "init", "--quiet", str(temp_dir)],
        check=True,
    )
    (temp_dir / ".gitignore").write_text("ignored/\n")
    (temp_dir / "included.py").write_text("pass\n")
    (temp_dir / "ignored").mkdir()
    (temp_dir / "ignored" / "ignored.py").write_text("pass\n")
    (temp_dir / "package").mkdir()
    (temp_dir / "package" / ".gitignore").write_text("nested_ignored.py\n")
    (temp_dir / "package" / "included.py").write_text("pass\n")
    (temp_dir / "package" / "nested_ignored.py").write_text("pass\n")
    (temp_dir / ".worktrees").mkdir()
    (temp_dir / ".worktrees" / "duplicate.py").write_text("pass\n")

    discovered = discover_python_files(temp_dir)

    assert set(discovered) == {
        temp_dir / "included.py",
        temp_dir / "package" / "included.py",
    }


def test_non_git_discovery_prunes_default_exclusions(temp_dir):
    (temp_dir / "package").mkdir()
    (temp_dir / "package" / "included.py").write_text("pass\n")
    (temp_dir / ".worktrees").mkdir()
    (temp_dir / ".worktrees" / "duplicate.py").write_text("pass\n")

    discovered = discover_python_files(temp_dir)

    assert discovered == [temp_dir / "package" / "included.py"]

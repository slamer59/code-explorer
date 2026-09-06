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


def test_project_nested_in_an_ignoring_repo_is_not_reported_empty(temp_dir):
    """A corpus vendored under a parent repo that ignores it still indexes.

    `git -C <dir> ls-files` answers for the *enclosing* repository, so a
    directory the parent gitignores lists zero files with returncode 0 --
    indistinguishable from "there is no Python here". Discovery must fall back
    to the filesystem walk unless the directory is itself a worktree root.
    """
    subprocess.run(["git", "init", "--quiet", str(temp_dir)], check=True)
    (temp_dir / ".gitignore").write_text("vendored/\n")
    (temp_dir / "outer.py").write_text("pass\n")
    nested = temp_dir / "vendored" / "project"
    nested.mkdir(parents=True)
    (nested / "included.py").write_text("pass\n")

    assert discover_python_files(nested) == [nested / "included.py"]
    # The parent is unaffected: it is a worktree root, so git still answers.
    assert discover_python_files(temp_dir) == [temp_dir / "outer.py"]

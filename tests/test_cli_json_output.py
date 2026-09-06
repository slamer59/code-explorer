"""Tests for `code-explorer search --json`, the machine-driven surface.

The benchmark harness in bench/ drives the real CLI rather than importing the
package, so stdout is a contract: every query must yield one parseable
document, and the assembled bundle must be available as data and not only as
rendered markdown.
"""

import json
import subprocess

import pytest
from click.testing import CliRunner

from code_explorer.cli import cli
from code_explorer.graph.import_resolver import resolve_import_aware


def test_resolver_returns_zeroed_stats_when_nothing_changed(temp_dir):
    """An empty result set must still carry every key the summary indexes.

    `search --reindex` on an up-to-date corpus analyses zero files and reaches
    this path; returning a bare {} raised KeyError('calls_unresolved') and made
    the command unusable on any corpus that was already indexed.
    """
    resolved, stats = resolve_import_aware([], temp_dir)

    assert resolved == []
    assert stats == {
        "calls_resolved": 0,
        "calls_unresolved": 0,
        "calls_skipped_unattributable": 0,
        "external_edges": 0,
    }


@pytest.fixture
def indexed_project(sample_project):
    """A tiny project with a built search index, addressed by path."""
    subprocess.run(["git", "init", "--quiet", str(sample_project)], check=True)
    return sample_project


def _search(project, *args):
    result = CliRunner().invoke(
        cli, ["search", *args, str(project), "--json"]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_json_emits_a_document_even_with_no_hits(indexed_project):
    """"No results" and "the command crashed" must not look identical."""
    payload = _search(indexed_project, "--reindex", "zzz_no_such_symbol_zzz")

    assert payload["hits"] == []
    assert payload["context"] is None
    assert payload["query"] == "zzz_no_such_symbol_zzz"


def test_json_exposes_the_bundle_as_data(indexed_project):
    """context_nodes lets a harness ask which files expansion pulled in."""
    payload = _search(indexed_project, "--reindex", "process")

    assert payload["hits"], "fixture project should contain a `process` function"
    assert payload["seed"]["name"]
    nodes = payload["context_nodes"]
    assert nodes, "seed has neighbours in the fixture project"
    assert set(nodes[0]) == {
        "file", "name", "section", "role", "distance", "abridged"
    }
    assert payload["context_tokens"] > 0

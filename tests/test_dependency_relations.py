"""Influence that is not a function call: DEPENDS_ON edges.

The product question is "what influences this code, and what does it
influence". Before these edges the graph only knew CALLS, so a base class
that fifteen plugins extend answered "(none)" -- confidently wrong on
exactly the plugin-style codebases where indirection matters most.

Both ingest paths are covered because they resolve differently: the generic
path is handed the whole corpus at once, while the streaming path sees one
file at a time and resolves against the database after the last batch. They
must agree.
"""

from pathlib import Path

import pytest

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph
from code_explorer.graph.ingest import file_analyses_to_records

BASE_SOURCE = '''
REGISTRY = {}


def register(cls):
    """Class decorator that records a plugin."""
    REGISTRY[cls.__name__] = cls
    return cls


class BasePlugin:
    """Base class every plugin extends."""

    def run(self):
        raise NotImplementedError
'''

PLUGINS_SOURCE = '''
import functools

from demo.base import BasePlugin
from demo.base import register


@register
class AlphaPlugin(BasePlugin):
    def run(self):
        return "alpha"


class BetaPlugin(BasePlugin):
    @functools.lru_cache
    def run(self):
        return "beta"
'''


@pytest.fixture
def plugin_project(temp_dir: Path) -> Path:
    package = temp_dir / "demo"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "base.py").write_text(BASE_SOURCE)
    (package / "plugins.py").write_text(PLUGINS_SOURCE)
    return temp_dir


def _relations(edges, nodes):
    """(kind, src label, dst label) for every DEPENDS_ON edge."""
    label = {}
    for node in nodes:
        properties = node.properties
        if node.type == "File":
            label[node.id] = properties["path"]
        elif node.type == "ExternalSymbol":
            label[node.id] = properties["qualified_name"]
        else:
            label[node.id] = f"{properties['file']}::{properties['name']}"
    return {
        (edge.properties["kind"], label[edge.src_id], label[edge.dst_id])
        for edge in edges
        if edge.type == "DEPENDS_ON"
    }


def test_generic_path_emits_inherits_decorates_and_imports(plugin_project):
    results = CodeAnalyzer().analyze_directory(plugin_project)

    nodes, edges = file_analyses_to_records(results, project_root=plugin_project)
    relations = _relations(edges, nodes)

    # Direction is "depends on": the subclass points at the base, not the
    # other way round. An LLM asking "is this change safe" needs the
    # upstream set specifically, so getting this backwards is worse than
    # having no edge.
    assert (
        "inherits",
        "demo/plugins.py::AlphaPlugin",
        "demo/base.py::BasePlugin",
    ) in relations
    assert (
        "inherits",
        "demo/plugins.py::BetaPlugin",
        "demo/base.py::BasePlugin",
    ) in relations
    assert (
        "decorates",
        "demo/plugins.py::AlphaPlugin",
        "demo/base.py::register",
    ) in relations
    assert ("imports", "demo/plugins.py", "demo/base.py") in relations
    # A decorator from a library we never parse lands on the existing
    # external-symbol boundary rather than being dropped or inventing a
    # second unresolved-target concept.
    assert (
        "decorates",
        "demo/plugins.py::run",
        "functools.lru_cache",
    ) in relations


def test_inheritance_is_queryable_in_both_directions(plugin_project, temp_dir):
    """The two questions the bundle builder asks, as Cypher."""
    results = CodeAnalyzer().analyze_directory(plugin_project)
    backend = LatticeBackend(temp_dir / "graph.lattice")
    graph = DependencyGraph(
        db_path=temp_dir / "graph.lattice",
        project_root=plugin_project,
        backend=backend,
    )
    graph.ingest_results(results)

    downstream = graph.backend.query(
        "MATCH (dependent:Class)-[r:DEPENDS_ON]->(target:Class) "
        "WHERE target.name = $name RETURN dependent.name AS name",
        {"name": "BasePlugin"},
    )
    assert {row["name"] for row in downstream} == {"AlphaPlugin", "BetaPlugin"}

    upstream = graph.backend.query(
        "MATCH (dependent:Class)-[r:DEPENDS_ON]->(target:Class) "
        "WHERE dependent.name = $name RETURN target.name AS name",
        {"name": "AlphaPlugin"},
    )
    assert [row["name"] for row in upstream] == ["BasePlugin"]


def test_streaming_path_agrees_with_generic_path(plugin_project, temp_dir):
    backend = LatticeBackend(temp_dir / "streamed.lattice")
    graph = DependencyGraph(
        db_path=temp_dir / "streamed.lattice",
        project_root=plugin_project,
        backend=backend,
    )
    stats = graph.ingest_analysis_stream(
        CodeAnalyzer().iter_analyze_directory(plugin_project),
        # One file per batch: the point of the test is that a base class
        # defined in a *previous* batch still resolves, which per-batch
        # resolution could not do.
        batch_size=1,
        batch_bytes=1,
        assume_new=True,
    )

    assert stats["dependencies_inherits"] == 2
    assert stats["dependencies_imports"] == 1
    # @register x1 (AlphaPlugin) + @functools.lru_cache x1.
    assert stats["dependencies_decorates"] == 2

    rows = graph.backend.query(
        "MATCH (dependent:Class)-[r:DEPENDS_ON]->(target:Class) "
        "WHERE target.name = $name RETURN dependent.name AS name, r.kind AS kind",
        {"name": "BasePlugin"},
    )
    assert {(row["name"], row["kind"]) for row in rows} == {
        ("AlphaPlugin", "inherits"),
        ("BetaPlugin", "inherits"),
    }


def test_reindexing_a_base_class_keeps_its_subclass_edges(plugin_project, temp_dir):
    """Re-indexing one file deletes every edge touching its nodes, including
    edges pointing *at* it from files that did not change. Without the
    republish, touching a base class silently restored the "(none)" answer
    these edges exist to remove."""
    backend = LatticeBackend(temp_dir / "reindex.lattice")
    graph = DependencyGraph(
        db_path=temp_dir / "reindex.lattice",
        project_root=plugin_project,
        backend=backend,
    )
    analyzer = CodeAnalyzer()
    graph.ingest_analysis_stream(
        analyzer.iter_analyze_directory(plugin_project),
        batch_size=1000,
        batch_bytes=8 << 20,
        assume_new=True,
    )

    def subclasses():
        return sorted(
            row["name"]
            for row in graph.backend.query(
                "MATCH (d:Class)-[r:DEPENDS_ON]->(t:Class) "
                "WHERE t.name = $name RETURN d.name AS name",
                {"name": "BasePlugin"},
            )
        )

    assert subclasses() == ["AlphaPlugin", "BetaPlugin"]

    base = plugin_project / "demo" / "base.py"
    base.write_text(BASE_SOURCE + "\n\n# touched\n")
    graph.backend.delete_file("demo/base.py")
    graph.ingest_analysis_stream(
        [analyzer.analyze_file(base)], batch_size=1000, batch_bytes=8 << 20
    )

    assert subclasses() == ["AlphaPlugin", "BetaPlugin"]


def test_object_and_protocol_bases_do_not_become_edges(temp_dir):
    """`object` and the typing markers would be one hub node the whole
    corpus points at, which answers nothing."""
    (temp_dir / "m.py").write_text(
        "from typing import Protocol\n\n\n"
        "class A(object):\n    pass\n\n\n"
        "class B(Protocol):\n    pass\n"
    )
    results = CodeAnalyzer().analyze_directory(temp_dir)

    _, edges = file_analyses_to_records(results, project_root=temp_dir)

    assert not [
        edge
        for edge in edges
        if edge.type == "DEPENDS_ON" and edge.properties["kind"] == "inherits"
    ]

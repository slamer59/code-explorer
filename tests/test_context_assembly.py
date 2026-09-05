"""Tests for context.py's minimal LLM context assembly.

Kept small (matching this repo's established convention): one proving the
Function happy path (seed + callers/callees with source attached), one
proving the node-budget cap actually truncates and reports how much -- then
the same two for a Class seed, whose neighbourhoods are instantiation sites
/ methods / bases / subclasses instead.
"""

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.call_resolver import CallResolver
from code_explorer.context import ContextAssembler
from code_explorer.graph.backends.kuzu_backend import KuzuBackend
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph
from code_explorer.graph.records import EdgeRecord, NodeRecord


def _graph(temp_dir):
    return DependencyGraph(
        db_path=temp_dir / "graph.db",
        project_root=temp_dir,
        backend=KuzuBackend(temp_dir / "graph.db"),
    )


def test_assemble_context_returns_seed_with_callees_and_source(
    sample_python_file, temp_dir
):
    result = CodeAnalyzer().analyze_file(sample_python_file)
    resolved_calls = CallResolver([result]).resolve_all_calls()
    graph = _graph(temp_dir)
    graph.ingest_results([result], resolved_calls=resolved_calls)

    ctx = ContextAssembler(graph).assemble_context(
        str(sample_python_file), "caller_function"
    )

    assert ctx.seed.name == "caller_function"
    assert "value = public_function(5, 10)" in ctx.seed.source_code

    callee_names = {c.name for c in ctx.callees}
    assert callee_names == {"public_function", "_private_function"}
    for callee in ctx.callees:
        assert callee.source_code  # source was actually attached, not blank
    assert ctx.callers == []
    assert ctx.callers_truncated == 0
    assert ctx.callees_truncated == 0

    # Rendered output should be readable and contain the seed + callee code.
    md = ctx.to_markdown()
    assert "Seed:" in md
    assert "sample.py::caller_function" in md
    assert "public_function" in md


def test_assemble_context_truncates_to_node_budget(temp_dir):
    # Source is now read from disk (see source_provider.py), not a stored
    # NodeRecord property -- write a real backing file covering every
    # start_line/end_line used below (target: 1-2, callers: 10-16).
    (temp_dir / "a.py").write_text("\n" * 20)
    graph = _graph(temp_dir)

    target = NodeRecord(
        id="fn_target", type="Function",
        properties={"id": "fn_target", "name": "target", "file": "a.py",
                    "start_line": 1, "end_line": 2, "is_public": True,
                    "source_code": "def target(): pass"},
    )
    callers = [
        NodeRecord(
            id=f"fn_caller_{i}", type="Function",
            properties={"id": f"fn_caller_{i}", "name": f"caller_{i}", "file": "a.py",
                        "start_line": 10 + i, "end_line": 11 + i, "is_public": True,
                        "source_code": f"def caller_{i}(): target()"},
        )
        for i in range(5)
    ]
    graph.backend.upsert_nodes([target] + callers)
    graph.backend.upsert_edges([
        EdgeRecord(src_id=f"fn_caller_{i}", dst_id="fn_target", type="CALLS",
                   properties={"call_line": 10 + i})
        for i in range(5)
    ])

    # budget: seed (1) + 3 remaining -> caller_budget=2, callee_budget=1
    ctx = ContextAssembler(graph).assemble_context("a.py", "target", max_nodes=4)

    assert ctx.seed.name == "target"
    assert len(ctx.callers) == 2
    assert ctx.callers_truncated == 3  # 5 total callers - 2 kept
    assert ctx.callees_truncated == 0


def _lattice_graph(temp_dir):
    """A LatticeDB-backed graph -- the Class path needs one.

    Not Kuzu: its CALLS table is declared Function->Function (schema.py), so
    a constructor call can't even be stored as an edge on a Class node
    there, and its Function table has no parent_class column to find methods
    by. `search`, the only caller of the Class path, is LatticeDB-only
    anyway (see cli.py's search docstring).
    """
    db_path = temp_dir / "graph.lattice"
    return DependencyGraph(
        db_path=db_path,
        project_root=temp_dir,
        backend=LatticeBackend(db_path),
    )


def _write(temp_dir, name: str, source: str):
    path = temp_dir / name
    path.write_text(source, encoding="utf-8")
    return CodeAnalyzer().analyze_file(path)


def test_assemble_class_context_gives_methods_bases_and_instantiation_sites(temp_dir):
    models = _write(
        temp_dir,
        "models.py",
        "class BaseWidget:\n"
        "    def describe(self):\n"
        "        return 'base'\n"
        "\n"
        "\n"
        "class Widget(BaseWidget):\n"
        "    def __init__(self, label):\n"
        "        self.label = label\n"
        "\n"
        "    def render(self):\n"
        "        return self.label\n"
        "\n"
        "\n"
        "class FancyWidget(Widget):\n"
        "    def render(self):\n"
        "        return '*'\n",
    )
    app = _write(
        temp_dir,
        "app.py",
        "from models import Widget\n"
        "\n"
        "\n"
        "def build_widget(label):\n"
        "    return Widget(label)\n",
    )
    graph = _lattice_graph(temp_dir)
    graph.ingest_analysis_stream(iter([models, app]), batch_size=8, assume_new=True)

    ctx = ContextAssembler(graph).assemble("models.py", "Widget", node_type="Class")

    assert ctx.seed.name == "Widget"
    assert "class Widget(BaseWidget):" in ctx.seed.source_code
    by_title = {s.title: {n.name for n in s.nodes} for s in ctx.resolved_sections()}
    # The instantiation site is the whole point of the Class path: a
    # constructor call resolves to the Class node, so it arrives as an
    # incoming CALLS edge on it.
    assert by_title["Instantiation sites"] == {"build_widget"}
    assert by_title["Methods"] == {"__init__", "render"}
    assert by_title["Base classes"] == {"BaseWidget"}
    assert by_title["Subclasses"] == {"FancyWidget"}
    for section in ctx.resolved_sections():
        for node in section.nodes:
            assert node.source_code  # source actually attached, not blank

    md = ctx.to_markdown()
    assert "models.py::Widget" in md
    assert "app.py::build_widget (instantiation site)" in md

    graph.backend.close()


def test_class_context_respects_the_node_budget(temp_dir):
    methods = "".join(f"    def m{i}(self):\n        return {i}\n\n" for i in range(6))
    models = _write(temp_dir, "models.py", "class Big:\n" + methods)
    graph = _lattice_graph(temp_dir)
    graph.ingest_analysis_stream(iter([models]), batch_size=8, assume_new=True)

    # budget: seed (1) + 4 remaining, split evenly over 4 sections -> 1 each
    ctx = ContextAssembler(graph).assemble_class_context(
        "models.py", "Big", max_nodes=5
    )

    methods_section = next(s for s in ctx.resolved_sections() if s.title == "Methods")
    assert len(methods_section.nodes) == 1
    assert methods_section.truncated == 5  # 6 methods - 1 kept
    assert "... 5 more not shown (budget)" in ctx.to_markdown()

    graph.backend.close()

"""Tests for context.py's minimal LLM context assembly.

Kept small (2-3 tests, matching this repo's established convention): one
proving the happy path (seed + callers/callees with source attached), one
proving the node-budget cap actually truncates and reports how much.
"""

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.call_resolver import CallResolver
from code_explorer.context import ContextAssembler
from code_explorer.graph.backends.kuzu_backend import KuzuBackend
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

"""Red/green coverage for bounded LatticeDB search-index ingestion."""

from click.testing import CliRunner

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.cli import cli
from code_explorer.graph.backends.lattice_backend import (
    UNRESOLVED_CALL_STREAM,
    LatticeBackend,
)
from code_explorer.graph.graph import DependencyGraph
from code_explorer.graph.lattice_streaming import (
    AdaptiveBatchController,
    iter_lattice_ingest_batches,
)


def _analyze(temp_dir, relative_path: str, source: str):
    path = temp_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return CodeAnalyzer().analyze_file(path)


def _graph(temp_dir):
    db_path = temp_dir / "graph.lattice"
    return DependencyGraph(
        db_path=db_path,
        project_root=temp_dir,
        backend=LatticeBackend(db_path),
    )


def _unresolved(graph):
    return [
        dict(record.payload)
        for record in graph.backend.db.read_stream(
            UNRESOLVED_CALL_STREAM, after_sequence=0, limit=10_000
        )
    ]


def test_stream_resolves_an_explicit_import_when_target_arrives_later(temp_dir):
    caller = _analyze(
        temp_dir,
        "caller.py",
        "from target import save as imported_save\n\ndef run():\n    imported_save()\n",
    )
    unrelated_override = _analyze(
        temp_dir,
        "plugin.py",
        "def save():\n    pass\n",
    )
    imported_target = _analyze(
        temp_dir,
        "target.py",
        "def save():\n    pass\n",
    )
    graph = _graph(temp_dir)

    stats = graph.ingest_analysis_stream(
        iter([caller, unrelated_override, imported_target]),
        batch_size=4,
        assume_new=True,
    )

    edges = graph.backend.query(
        "MATCH (a:Function)-[c:CALLS]->(b:Function) "
        "RETURN a.name AS caller, b.file AS target_file, "
        "c.resolution_method AS method, c.confidence AS confidence"
    )
    assert edges == [
        {
            "caller": "run",
            "target_file": "target.py",
            "method": "explicit_import",
            "confidence": "high",
        }
    ]
    assert _unresolved(graph) == []
    assert stats["batches"] >= 2
    assert stats["calls_resolved"] == 1
    assert stats["calls_unresolved"] == 0


def test_stream_keeps_an_ambiguous_plugin_call_as_a_reference(temp_dir):
    caller = _analyze(
        temp_dir,
        "caller.py",
        "def run():\n    save()\n",
    )
    plugin_a = _analyze(temp_dir, "plugin_a.py", "def save():\n    pass\n")
    plugin_b = _analyze(temp_dir, "plugin_b.py", "def save():\n    pass\n")
    graph = _graph(temp_dir)

    stats = graph.ingest_analysis_stream(
        iter([caller, plugin_a, plugin_b]),
        batch_size=4,
        assume_new=True,
    )

    assert (
        graph.backend.query(
            "MATCH (:Function)-[c:CALLS]->(:Function) RETURN c.call_line AS line"
        )
        == []
    )
    references = _unresolved(graph)
    assert [(r["called_name"], r["status"]) for r in references] == [
        ("save", "call.ambiguous")
    ]
    assert stats["calls_resolved"] == 0
    assert stats["calls_unresolved"] == 1


def test_final_call_resolution_reports_streamed_progress(temp_dir):
    caller = _analyze(temp_dir, "caller.py", "def run():\n    missing()\n")
    graph = _graph(temp_dir)
    updates = []

    graph.ingest_analysis_stream(
        iter([caller]),
        batch_size=1000,
        assume_new=True,
        on_finalize_progress=lambda progress: updates.append(progress),
    )

    assert updates[0] == {
        "total": 1,
        "processed": 0,
        "resolved": 0,
        "unresolved": 0,
        "windows": 0,
    }
    assert updates[-1] == {
        "total": 1,
        "processed": 1,
        "resolved": 0,
        "unresolved": 1,
        "windows": 1,
    }


def test_same_file_call_is_materialized_without_waiting_for_end_of_stream(temp_dir):
    first = _analyze(
        temp_dir,
        "first.py",
        "def helper():\n    pass\n\ndef run():\n    helper()\n",
    )
    second_consumed = False

    def analyses():
        nonlocal second_consumed
        yield first
        second_consumed = True
        yield _analyze(temp_dir, "second.py", "def unrelated():\n    pass\n")

    graph = _graph(temp_dir)
    observed_before_second_file = []

    stats = graph.ingest_analysis_stream(
        analyses(),
        batch_size=5,
        assume_new=True,
        on_batch_committed=lambda _stats: observed_before_second_file.append(
            (
                second_consumed,
                len(
                    graph.backend.query(
                        "MATCH (:Function)-[c:CALLS]->(:Function) "
                        "RETURN c.call_line AS line"
                    )
                ),
            )
        ),
    )

    assert observed_before_second_file[0] == (False, 1)
    assert stats["calls_resolved"] == 1


def test_analyzer_preserves_attribute_call_qualifiers(temp_dir):
    result = _analyze(
        temp_dir,
        "qualified.py",
        "def run(self):\n    service.save()\n    self.clean()\n",
    )

    calls = {(call.called_name, call.qualifier) for call in result.function_calls}
    assert calls == {("save", "service"), ("clean", "self")}


def test_analysis_iterator_is_lazy_in_sequential_mode(temp_dir, monkeypatch):
    for index in range(3):
        (temp_dir / f"file_{index}.py").write_text(
            f"def function_{index}():\n    pass\n", encoding="utf-8"
        )
    analyzer = CodeAnalyzer()
    original = analyzer.analyze_file
    analyzed = []

    def recording_analyze_file(path, *args, **kwargs):
        analyzed.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(analyzer, "analyze_file", recording_analyze_file)

    results = analyzer.iter_analyze_directory(temp_dir, parallel=False)

    assert analyzed == []
    next(results)
    assert len(analyzed) == 1


def test_stream_flushes_on_byte_budget_even_below_record_limit(temp_dir):
    first = _analyze(temp_dir, "first.py", "def first():\n    pass\n")
    second = _analyze(temp_dir, "second.py", "def second():\n    pass\n")
    graph = _graph(temp_dir)

    stats = graph.ingest_analysis_stream(
        iter([first, second]),
        batch_size=1000,
        batch_bytes=1,
        assume_new=True,
    )

    assert stats["batches"] == 2


def test_batch_iterator_reads_the_next_limit_after_each_committed_batch(temp_dir):
    analyses = [_analyze(temp_dir, f"file_{index}.py", "") for index in range(3)]
    current_limit = {"operations": 1}
    batches = iter_lattice_ingest_batches(
        iter(analyses),
        temp_dir,
        batch_size=1,
        batch_bytes=1024 * 1024,
        batch_size_provider=lambda: current_limit["operations"],
    )

    first = next(batches)
    current_limit["operations"] = 2
    second = next(batches)

    assert first.operation_count == 1
    assert first.target_operations == 1
    assert second.operation_count == 2
    assert second.target_operations == 2


def test_adaptive_batch_controller_selects_smallest_size_near_peak_throughput():
    controller = AdaptiveBatchController(
        initial_size=100,
        max_size=400,
        samples_per_size=2,
        throughput_tolerance=0.05,
    )
    throughput_by_size = {100: 950.0, 200: 1000.0, 400: 1020.0}

    observed_targets = []
    for _ in range(6):
        target = controller.current_size
        observed_targets.append(target)
        controller.observe(
            target_size=target,
            operation_count=target,
            estimated_bytes=target * 100,
            duration_seconds=target / throughput_by_size[target],
        )

    assert observed_targets == [100, 200, 400, 100, 200, 400]
    assert controller.selected_size == 200
    assert controller.current_size == 200


def test_streaming_ingest_feeds_commit_measurements_into_next_batch(temp_dir):
    analyses = [_analyze(temp_dir, f"adaptive_{index}.py", "") for index in range(5)]
    observed_targets = []
    graph = _graph(temp_dir)

    stats = graph.ingest_analysis_stream(
        iter(analyses),
        batch_size=1,
        batch_bytes=1024 * 1024,
        adaptive=True,
        max_batch_size=2,
        calibration_batches=1,
        assume_new=True,
        on_batch_committed=lambda batch_stats: observed_targets.append(
            batch_stats["batch_target_size"]
        ),
    )

    assert observed_targets[:2] == [1, 2]
    assert stats["adaptive_samples"] == 2
    assert stats["selected_batch_size"] in {1, 2}


def test_search_reindex_uses_streaming_analysis_not_full_repository_list(
    temp_dir, monkeypatch
):
    (temp_dir / "service.py").write_text(
        "def rebuild_helper():\n    pass\n", encoding="utf-8"
    )

    def full_list_path_must_not_run(*args, **kwargs):
        raise AssertionError("search reindex must consume iter_analyze_directory")

    monkeypatch.setattr(CodeAnalyzer, "analyze_directory", full_list_path_must_not_run)

    result = CliRunner().invoke(
        cli,
        ["search", "rebuild_helper", str(temp_dir), "--reindex", "--no-context"],
    )

    assert result.exit_code == 0, result.output
    assert "rebuild_helper" in result.output


def test_search_reindex_displays_committed_graph_batches(temp_dir):
    (temp_dir / "service.py").write_text(
        "def rebuild_helper():\n    pass\n", encoding="utf-8"
    )

    result = CliRunner().invoke(
        cli,
        ["search", "rebuild_helper", str(temp_dir), "--reindex", "--no-context"],
    )

    assert result.exit_code == 0, result.output
    assert "Graph:" in result.output
    assert "1 batch" in result.output
    assert "2 nodes" in result.output


def test_search_reindex_displays_final_call_resolution_progress(temp_dir):
    (temp_dir / "service.py").write_text(
        "def rebuild_helper():\n    missing()\n", encoding="utf-8"
    )

    result = CliRunner().invoke(
        cli,
        ["search", "rebuild_helper", str(temp_dir), "--reindex", "--no-context"],
    )

    assert result.exit_code == 0, result.output
    assert "Resolving pending calls" in result.output
    assert "1 unresolved" in result.output


def test_self_call_resolves_to_its_class_despite_plugin_overrides(temp_dir):
    model = _analyze(
        temp_dir,
        "model.py",
        "class Model:\n"
        "    def save(self):\n        pass\n\n"
        "    def run(self):\n        self.save()\n",
    )
    override = _analyze(
        temp_dir,
        "plugin.py",
        "class Plugin:\n    def save(self):\n        pass\n",
    )
    graph = _graph(temp_dir)

    graph.ingest_analysis_stream(iter([model, override]), batch_size=5, assume_new=True)

    assert graph.backend.query(
        "MATCH (a:Function)-[c:CALLS]->(b:Function) "
        "RETURN a.name AS caller, b.file AS target_file, "
        "c.resolution_method AS method"
    ) == [{"caller": "run", "target_file": "model.py", "method": "same_class"}]


def test_self_call_resolves_when_direct_base_arrives_in_a_later_batch(temp_dir):
    plugin = _analyze(
        temp_dir,
        "plugin.py",
        "class Plugin(BasePlugin):\n    def run(self):\n        self.process()\n",
    )
    base = _analyze(
        temp_dir,
        "base.py",
        "class BasePlugin:\n    def process(self):\n        pass\n",
    )
    graph = _graph(temp_dir)

    graph.ingest_analysis_stream(iter([plugin, base]), batch_size=4, assume_new=True)

    assert graph.backend.query(
        "MATCH (a:Function)-[c:CALLS]->(b:Function) "
        "RETURN a.name AS caller, b.file AS target_file, "
        "c.resolution_method AS method"
    ) == [{"caller": "run", "target_file": "base.py", "method": "direct_base"}]


def test_two_calls_to_same_target_on_one_line_remain_distinct_references(temp_dir):
    analysis = _analyze(
        temp_dir,
        "same_line.py",
        "def helper():\n    pass\n\ndef run():\n    helper(); helper()\n",
    )
    graph = _graph(temp_dir)

    stats = graph.ingest_analysis_stream(
        iter([analysis]), batch_size=1000, assume_new=True
    )

    edges = graph.backend.query(
        "MATCH (:Function)-[c:CALLS]->(:Function) "
        "RETURN c.call_line AS line, c.call_reference_id AS reference_id"
    )
    assert len({edge["reference_id"] for edge in edges}) == 2
    assert [edge["line"] for edge in edges] == [5, 5]
    assert _unresolved(graph) == []
    assert stats["calls_resolved"] == 2


def test_incremental_target_change_requeues_and_later_resolves_call_reference(
    temp_dir,
):
    caller_path = temp_dir / "caller.py"
    target_path = temp_dir / "target.py"
    caller_path.write_text(
        "from target import save\n\ndef run():\n    save()\n", encoding="utf-8"
    )
    target_path.write_text("def save():\n    pass\n", encoding="utf-8")
    analyzer = CodeAnalyzer()
    graph = _graph(temp_dir)
    graph.ingest_analysis_stream(
        iter([analyzer.analyze_file(caller_path), analyzer.analyze_file(target_path)]),
        batch_size=4,
        assume_new=True,
    )

    target_path.write_text("def renamed():\n    pass\n", encoding="utf-8")
    graph.ingest_incremental(temp_dir)

    assert (
        graph.backend.query(
            "MATCH (:Function)-[c:CALLS]->(:Function) RETURN c.call_line AS line"
        )
        == []
    )
    assert [r["status"] for r in _unresolved(graph)] == ["call.unresolved"]

    target_path.write_text("def save():\n    pass\n", encoding="utf-8")
    graph.ingest_incremental(temp_dir)

    assert graph.backend.query(
        "MATCH (:Function)-[c:CALLS]->(:Function) RETURN c.call_line AS line"
    ) == [{"line": 4}]
    assert _unresolved(graph) == []

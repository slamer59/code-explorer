"""Memory-shape tests for large-repository indexing."""

from code_explorer.analyzer import base_analyzer
from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.graph.backends.lattice_backend import _chunked


def test_parallel_analysis_caps_in_flight_futures(temp_dir, monkeypatch):
    for index in range(10):
        (temp_dir / f"file_{index}.py").write_text(f"VALUE = {index}\n")

    wait_sizes = []

    class ImmediateFuture:
        def __init__(self, value):
            self.value = value

        def result(self):
            return self.value

    class ImmediateExecutor:
        def __init__(self, max_workers=None):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, function, *args):
            return ImmediateFuture(function(*args))

    def complete_one(futures, return_when=None):
        wait_sizes.append(len(futures))
        completed = {next(iter(futures))}
        return completed, set(futures) - completed

    monkeypatch.setattr(base_analyzer, "ProcessPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(base_analyzer, "wait", complete_one)

    results = CodeAnalyzer().analyze_directory(temp_dir, max_workers=2)

    assert len(results) == 10
    assert max(wait_sizes) == 4


def test_search_profile_drops_unused_metadata_and_full_source(temp_dir):
    source = temp_dir / "module.py"
    source.write_text(
        "import os\n"
        "VALUE = 1\n"
        "def useful(argument: str) -> str:\n"
        "    return os.path.join(argument, str(VALUE))\n"
    )

    result = CodeAnalyzer(
        search_only=True,
        retain_full_source=False,
    ).analyze_file(source)

    assert result.functions[0].source_code == "def useful(argument: str) -> str:\n"
    assert result.imports == []
    assert result.variables == []
    assert result._source_content is None
    assert result._source_lines is None


def test_lattice_batches_consume_iterables_lazily():
    consumed = []

    def records():
        for value in range(5):
            consumed.append(value)
            yield value

    batches = _chunked(records(), 2)

    assert consumed == []
    assert next(batches) == [0, 1]
    assert consumed == [0, 1]
    assert next(batches) == [2, 3]
    assert consumed == [0, 1, 2, 3]

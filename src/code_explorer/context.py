"""Minimal LLM context assembly for a single function.

A small, bounded companion to ImpactAnalyzer (impact.py): given a seed
function, returns the seed itself plus its direct (one-hop) callers and
callees, each with source code attached, capped to a node budget. This is
NOT transitive/multi-hop impact analysis -- see ImpactAnalyzer for that.

Ranked #2 (tied with BM25 search) in docs/explanation/latticedb-migration.md's
"Implementation Status" section, for the explicit goal of giving an LLM "a
real nice context" from a single seed, per that spec's Section 18 (LLM
Context Strategy). Deliberately minimal per that ranking: one hop, a node
cap, source attached -- no confidence scoring, no multi-hop expansion, no
runtime/config evidence, no byte-budget trimming.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from .graph import DependencyGraph
from .source_provider import FilesystemSourceProvider, SourceProvider


@dataclass
class ContextNode:
    """A single function's source, with its call-site/definition location."""

    name: str
    file: str
    line_number: int
    source_code: str


@dataclass
class CodeContext:
    """A bounded, LLM-ready bundle of code directly relevant to a seed function."""

    seed: ContextNode
    callers: List[ContextNode] = field(default_factory=list)
    callees: List[ContextNode] = field(default_factory=list)
    callers_truncated: int = 0
    callees_truncated: int = 0

    def to_markdown(self) -> str:
        """Render as a readable, LLM-consumable markdown bundle."""
        lines: List[str] = []

        lines.append("Seed:")
        lines.append(f"    {self.seed.file}::{self.seed.name}")
        lines.append("")

        lines.append("Direct callers:")
        if self.callers:
            for c in self.callers:
                lines.append(f"    {c.name} ({c.file}:{c.line_number})")
        else:
            lines.append("    (none)")
        if self.callers_truncated:
            lines.append(f"    ... {self.callers_truncated} more not shown (node budget)")
        lines.append("")

        lines.append("Direct callees:")
        if self.callees:
            for c in self.callees:
                lines.append(f"    {c.name} ({c.file}:{c.line_number})")
        else:
            lines.append("    (none)")
        if self.callees_truncated:
            lines.append(f"    ... {self.callees_truncated} more not shown (node budget)")
        lines.append("")

        lines.append("---")
        lines.append("")
        lines.append(f"### {self.seed.file}::{self.seed.name} (seed)")
        lines.append("```python")
        lines.append(self.seed.source_code)
        lines.append("```")
        lines.append("")

        for c in self.callers:
            lines.append(f"### {c.file}::{c.name} (caller)")
            lines.append("```python")
            lines.append(c.source_code)
            lines.append("```")
            lines.append("")

        for c in self.callees:
            lines.append(f"### {c.file}::{c.name} (callee)")
            lines.append("```python")
            lines.append(c.source_code)
            lines.append("```")
            lines.append("")

        return "\n".join(lines)


class ContextAssembler:
    """Assembles a bounded CodeContext bundle around a seed function."""

    def __init__(self, graph: DependencyGraph, source_provider: Optional[SourceProvider] = None):
        self.graph = graph
        self.source_provider = source_provider or FilesystemSourceProvider(graph.project_root)

    def _get_source(self, file: str, name: str) -> Optional[dict]:
        """Fetch a function's start_line/end_line, then read its source from
        disk via SourceProvider.

        DependencyGraph.get_function()/FunctionNode don't carry line ranges
        today, so this queries the backend directly rather than widening
        that shared API as a side effect of this feature. Source is no
        longer read from a stored graph property -- see
        docs/explanation/source-of-truth-and-search-representations.md.
        """
        rel_file = self.graph._to_relative_path(file)
        rows = self.graph.backend.query(
            "MATCH (f:Function {file: $file, name: $name}) "
            "RETURN f.start_line AS start_line, f.end_line AS end_line",
            {"file": rel_file, "name": name},
        )
        if not rows:
            return None
        row = rows[0]
        source_code = self.source_provider.get_range(rel_file, row["start_line"], row["end_line"])
        return {"start_line": row["start_line"], "source_code": source_code}

    def assemble_context(
        self, file: str, function: str, max_nodes: int = 20
    ) -> CodeContext:
        """Build a bounded context bundle for `function` in `file`.

        Args:
            file: File path where the function is defined.
            function: Function name.
            max_nodes: Total node budget (seed + callers + callees).

        Returns:
            CodeContext with the seed, its direct callers/callees (source
            attached), and truncation counts if the budget was exceeded.

        Raises:
            ValueError: If the seed function isn't found in the graph, or a
                resolved line range is out of bounds for the current file.
            FileNotFoundError: If the seed's source file can't be read from
                disk (moved/deleted since indexing).
        """
        seed_row = self._get_source(file, function)
        if seed_row is None:
            raise ValueError(f"Function not found: {file}::{function}")

        rel_file = self.graph._to_relative_path(file)
        seed = ContextNode(
            name=function,
            file=rel_file,
            line_number=seed_row["start_line"],
            source_code=seed_row["source_code"] or "",
        )

        remaining = max(max_nodes - 1, 0)
        callee_budget = remaining // 2
        caller_budget = remaining - callee_budget

        # One shared function-id resolution + 2 queries total (not 2 separate
        # get_callers()/get_callees() calls, each re-resolving the id, plus
        # one _get_source() query per caller/callee) -- see
        # docs/explanation/latticedb-migration.md's Performance Findings:
        # this cut a measured 23-query/38.7ms context assembly down
        # substantially by fetching each node's (start_line, end_line)
        # straight from the already-matched CALLS-edge node instead of a
        # second per-node lookup.
        caller_rows, callee_rows = self.graph.get_callers_and_callees_with_lines(
            file, function
        )

        callers = self._resolve_nodes(caller_rows[:caller_budget])
        callees = self._resolve_nodes(callee_rows[:callee_budget])

        return CodeContext(
            seed=seed,
            callers=callers,
            callees=callees,
            callers_truncated=max(len(caller_rows) - caller_budget, 0),
            callees_truncated=max(len(callee_rows) - callee_budget, 0),
        )

    def _resolve_nodes(self, rows) -> List[ContextNode]:
        """Build ContextNodes from (file, name, call_line, start_line,
        end_line) rows, best-effort: unlike the seed (assemble_context
        raises if that fails -- it's the thing being asked about), one
        caller/callee whose source can't be read (stale line range, moved
        file) shouldn't abort the whole bundle -- note it inline instead
        and keep the rest. No DB query here -- start_line/end_line already
        came from the caller/callee query itself; this is a local disk read.
        """
        nodes: List[ContextNode] = []
        for row_file, row_name, call_line, start_line, end_line in rows:
            try:
                source_code = self.source_provider.get_range(row_file, start_line, end_line)
            except (ValueError, FileNotFoundError) as e:
                source_code = f"(could not read source: {e})"
            nodes.append(
                ContextNode(
                    name=row_name,
                    file=row_file,
                    line_number=call_line,
                    source_code=source_code,
                )
            )
        return nodes

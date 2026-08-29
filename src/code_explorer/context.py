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

    def __init__(self, graph: DependencyGraph):
        self.graph = graph

    def _get_source(self, file: str, name: str) -> Optional[dict]:
        """Fetch a function's source_code + start_line directly.

        DependencyGraph.get_function()/FunctionNode don't carry source_code
        today, so this queries the backend directly rather than widening
        that shared API as a side effect of this feature.
        """
        rel_file = self.graph._to_relative_path(file)
        rows = self.graph.backend.query(
            "MATCH (f:Function {file: $file, name: $name}) "
            "RETURN f.start_line AS start_line, f.source_code AS source_code",
            {"file": rel_file, "name": name},
        )
        return rows[0] if rows else None

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
            ValueError: If the seed function isn't found in the graph.
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

        caller_rows = self.graph.get_callers(file, function)
        callee_rows = self.graph.get_callees(file, function)

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
        nodes: List[ContextNode] = []
        for row_file, row_name, line in rows:
            src = self._get_source(row_file, row_name)
            nodes.append(
                ContextNode(
                    name=row_name,
                    file=row_file,
                    line_number=line,
                    source_code=(src["source_code"] if src else "") or "",
                )
            )
        return nodes

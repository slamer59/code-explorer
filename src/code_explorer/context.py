"""Minimal LLM context assembly for a single function or class.

A small, bounded companion to ImpactAnalyzer (impact.py): given a seed
function, returns the seed itself plus its direct (one-hop) callers and
callees, each with source code attached, capped to a node budget. This is
NOT transitive/multi-hop impact analysis -- see ImpactAnalyzer for that.

A Class seed gets the same shape with the class-flavoured analogue of each
neighbourhood: instantiation sites (incoming CALLS edges -- call resolution
now targets Class nodes for constructor calls, see
LatticeBackend.find_symbols_by_properties), its methods, its base classes
and its subclasses. Verified on a 2-file fixture: a `Widget(label)` call
site really does produce a CALLS edge whose target is the Class node.

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

# How many BM25 Class hits to probe when looking for subclasses defined
# outside the seed's own file. Small on purpose: this is a best-effort
# widening of an inherently approximate lookup (see _subclass_rows), not a
# search feature, and every hit costs one indexed name lookup.
_SUBCLASS_PROBE_LIMIT = 25


@dataclass
class ContextNode:
    """A single function's source, with its call-site/definition location."""

    name: str
    file: str
    line_number: int
    source_code: str


@dataclass
class ContextSection:
    """One named neighbourhood of the seed, with its own truncation count.

    Exists so a Class seed can render four neighbourhoods (instantiation
    sites / methods / base classes / subclasses) through the *same*
    to_markdown() the Function path uses, instead of a parallel renderer.
    The Function path keeps its two hardcoded fields (callers/callees) and
    derives its sections from them, so its rendered output is unchanged
    byte-for-byte.
    """

    title: str  # section heading, e.g. "Direct callers"
    role: str  # per-node source-block suffix, e.g. "caller"
    nodes: List[ContextNode] = field(default_factory=list)
    truncated: int = 0


@dataclass
class CodeContext:
    """A bounded, LLM-ready bundle of code directly relevant to a seed node."""

    seed: ContextNode
    callers: List[ContextNode] = field(default_factory=list)
    callees: List[ContextNode] = field(default_factory=list)
    callers_truncated: int = 0
    callees_truncated: int = 0
    # Set only by the Class path; None means "derive the two call-graph
    # sections from callers/callees" (the Function path).
    sections: Optional[List[ContextSection]] = None

    def resolved_sections(self) -> List[ContextSection]:
        if self.sections is not None:
            return self.sections
        return [
            ContextSection("Direct callers", "caller", self.callers, self.callers_truncated),
            ContextSection("Direct callees", "callee", self.callees, self.callees_truncated),
        ]

    def to_markdown(self) -> str:
        """Render as a readable, LLM-consumable markdown bundle."""
        lines: List[str] = []
        sections = self.resolved_sections()

        lines.append("Seed:")
        lines.append(f"    {self.seed.file}::{self.seed.name}")
        lines.append("")

        for section in sections:
            lines.append(f"{section.title}:")
            if section.nodes:
                for c in section.nodes:
                    lines.append(f"    {c.name} ({c.file}:{c.line_number})")
            else:
                lines.append("    (none)")
            if section.truncated:
                lines.append(f"    ... {section.truncated} more not shown (node budget)")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append(f"### {self.seed.file}::{self.seed.name} (seed)")
        lines.append("```python")
        lines.append(self.seed.source_code)
        lines.append("```")
        lines.append("")

        for section in sections:
            for c in section.nodes:
                lines.append(f"### {c.file}::{c.name} ({section.role})")
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

    def assemble(
        self, file: str, name: str, node_type: str = "Function", max_nodes: int = 20
    ) -> CodeContext:
        """Dispatch to the Function or Class assembler by seed node type.

        The single entry point cli.py should use: search hits already carry
        a node_type, so the caller doesn't have to know which assembler
        exists. Unknown node types fall back to the Function path (the only
        other searchable label today is Class -- see
        LatticeBackend.SEARCHABLE_TEXT_FIELDS).
        """
        if node_type == "Class":
            return self.assemble_class_context(file, name, max_nodes=max_nodes)
        return self.assemble_context(file, name, max_nodes=max_nodes)

    # ---- Class seeds -------------------------------------------------
    #
    # Everything below reaches the graph through indexed property matches
    # (Class.file/name, Function.file/parent_class -- all declared in
    # LatticeBackend.initialize_schema) or through the imperative edge API,
    # never through a relationship MATCH: measured on this project, a Cypher
    # `MATCH (a)-[:CALLS]->(b)` compiles to a LabelScan+Expand plan ~7,500x
    # slower than get_incoming_edges (see CodeGraphBackend.
    # get_call_edges_with_lines), and a bare label scan measured 288ms.

    def _class_row(self, rel_file: str, class_name: str) -> Optional[dict]:
        rows = self.graph.backend.query(
            "MATCH (c:Class {file: $file, name: $name}) "
            "RETURN c.id AS id, c.start_line AS start_line, "
            "c.end_line AS end_line, c.bases AS bases "
            "ORDER BY c.start_line ASC LIMIT 1",
            {"file": rel_file, "name": class_name},
        )
        # Same (file, name) ambiguity as QueryOperations._resolve_function_id:
        # two classes can share a name in one file (conditional definitions).
        # Lowest start_line wins -- well-defined rather than silently merged.
        return rows[0] if rows else None

    def _instantiation_sites(self, class_id: str):
        """Rows for the functions that construct this class.

        The exact analogue of "callers" for a function: constructor calls
        resolve to the Class node, so they arrive as incoming CALLS edges on
        it (verified on a fixture: `Widget(label)` in app.py produces
        app.py::build_widget -CALLS-> models.py::Widget).

        Uses the backend's own traversal with label="Class". Backends that
        predate that parameter, or that cannot host Class call targets at
        all (KuzuBackend declares CALLS as Function->Function), simply yield
        nothing rather than erroring.
        """
        backend = self.graph.backend
        try:
            callers, _ = backend.get_call_edges_with_lines(class_id, label="Class")
        except TypeError:
            return []
        return callers

    def _method_rows(self, rel_file: str, class_name: str):
        """Methods of the class, via the indexed Function.parent_class property.

        Approximation, worth stating: METHOD_OF edges are declared in the
        schema but ingest.py doesn't emit them today, so parent_class is the
        only signal. It is a bare name, so a method is matched by
        (file, parent_class) -- which is wrong only for two same-named
        classes in one file (the ambiguity _class_row already picks a side
        on).
        """
        rows = self.graph.backend.query(
            "MATCH (f:Function {file: $file, parent_class: $name}) "
            "RETURN f.name AS name, f.file AS file, "
            "f.start_line AS start_line, f.end_line AS end_line "
            "ORDER BY f.start_line ASC",
            {"file": rel_file, "name": class_name},
        )
        return [
            (r["file"], r["name"], r["start_line"], r["start_line"], r["end_line"])
            for r in rows
        ]

    def _classes_named(self, class_name: str) -> List[dict]:
        return self.graph.backend.query(
            "MATCH (c:Class {name: $name}) "
            "RETURN c.name AS name, c.file AS file, c.bases AS bases, "
            "c.start_line AS start_line, c.end_line AS end_line",
            {"name": class_name},
        )

    @staticmethod
    def _base_names(bases: Optional[str]) -> List[str]:
        # ingest.py stores bases as a comma-joined string of whatever the
        # parser saw, so a qualified base arrives as "models.Widget" --
        # compare on the last dotted segment.
        return [b.strip().split(".")[-1] for b in (bases or "").split(",") if b.strip()]

    def _base_rows(self, bases: Optional[str]):
        """Base classes, resolved by name through the indexed Class.name.

        Approximation: `bases` holds unqualified names with no module, so a
        base resolves to *every* project class of that name (all are kept,
        capped by the budget) and a base defined outside the project (or in
        a file that wasn't indexed) resolves to nothing and is simply absent
        from the bundle. INHERITS edges would be exact, but ingest.py emits
        none today -- verified on the fixture, where the only edges on a
        Class node were CONTAINS_CLASS and CALLS.
        """
        rows = []
        for base in self._base_names(bases):
            for r in self._classes_named(base):
                rows.append(
                    (r["file"], r["name"], r["start_line"], r["start_line"], r["end_line"])
                )
        return rows

    def _subclass_rows(self, rel_file: str, class_name: str):
        """Classes listing this one in their `bases`.

        Approximation, two ways. (1) `bases` is not an indexed property and
        cannot be, being a comma-joined string, so this can't be a direct
        lookup: candidates come from the same file (indexed Class.file) plus
        whatever BM25 surfaces for the class name -- a subclass in another
        file that BM25 doesn't rank in the top `_SUBCLASS_PROBE_LIMIT` is
        missed. A label scan over every Class would be exact but measured
        288ms on this project, which is not worth it for one bundle section.
        (2) Base names are unqualified, so a class inheriting a *different*
        class that happens to share this name is a false positive.
        """
        candidates = self.graph.backend.query(
            "MATCH (c:Class {file: $file}) "
            "RETURN c.name AS name, c.file AS file, c.bases AS bases, "
            "c.start_line AS start_line, c.end_line AS end_line",
            {"file": rel_file},
        )
        try:
            hits = self.graph.backend.search_text(
                class_name, node_types=["Class"], limit=_SUBCLASS_PROBE_LIMIT
            )
        except Exception:
            # KuzuBackend raises NotImplementedError (no FTS engine); a
            # missing/empty FTS index raises backend-specific errors. Neither
            # is worth failing a bundle over -- same-file candidates stand.
            hits = []
        for hit in hits:
            if hit.file == rel_file:
                continue  # already covered by the same-file candidates
            candidates.extend(self._classes_named(hit.name))

        rows = []
        seen = set()
        for r in candidates:
            if r["name"] == class_name and r["file"] == rel_file:
                continue  # the seed itself
            if class_name not in self._base_names(r["bases"]):
                continue
            key = (r["file"], r["name"], r["start_line"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                (r["file"], r["name"], r["start_line"], r["start_line"], r["end_line"])
            )
        return rows

    def assemble_class_context(
        self, file: str, class_name: str, max_nodes: int = 20
    ) -> CodeContext:
        """Build a bounded context bundle for `class_name` in `file`.

        Same bounded shape as assemble_context, with the class-flavoured
        neighbourhoods: who constructs it, its methods, its bases, its
        subclasses. The budget is split evenly across the four sections
        (rather than weighted) so no single huge class -- a 60-method one --
        can crowd the other three out of the bundle.

        Raises:
            ValueError: If the seed class isn't found in the graph.
            FileNotFoundError: If the seed's source file can't be read.
        """
        rel_file = self.graph._to_relative_path(file)
        row = self._class_row(rel_file, class_name)
        if row is None:
            raise ValueError(f"Class not found: {file}::{class_name}")

        seed = ContextNode(
            name=class_name,
            file=rel_file,
            line_number=row["start_line"],
            source_code=self.source_provider.get_range(
                rel_file, row["start_line"], row["end_line"]
            )
            or "",
        )

        all_rows = [
            ("Instantiation sites", "instantiation site", self._instantiation_sites(row["id"])),
            ("Methods", "method", self._method_rows(rel_file, class_name)),
            ("Base classes", "base class", self._base_rows(row.get("bases"))),
            ("Subclasses", "subclass", self._subclass_rows(rel_file, class_name)),
        ]

        remaining = max(max_nodes - 1, 0)
        per_section = remaining // len(all_rows)
        sections = [
            ContextSection(
                title=title,
                role=role,
                nodes=self._resolve_nodes(rows[:per_section]),
                truncated=max(len(rows) - per_section, 0),
            )
            for title, role, rows in all_rows
        ]
        return CodeContext(seed=seed, sections=sections)

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

"""LLM context assembly for a single function or class.

Given a seed, returns the seed itself plus the code that influences it and
the code it influences -- collected to depth 2-3, ranked as one set, and
rendered under a token budget. This is the engine behind both `search`
(find a seed, then expand) and `impact` (expand a seed you already named).

Collect-then-rank, not beam search. expand() walks the reachable set to
`depth` *without* pruning the frontier level by level, then ranks the whole
set at once, so a depth-3 node can legitimately outrank a depth-1 one.
Pruning per level is myopic: a dull direct neighbour is very often the only
path to the most relevant node two hops out. This is affordable only
because of a cost asymmetry we measured: traversing edges is cheap
(get_call_edges_with_lines, ~1.1ms per hop) while fetching source is a disk
read per node -- so expand() traverses wide, ranks, and reads source only
for the winners.

The older one-hop entry points (assemble_context / assemble_class_context)
are still here: a Class seed's neighbourhoods are structural (methods,
bases, subclasses), not call-graph paths, so multi-hop isn't defined for
them and expand() delegates that case unchanged.

That Class seed gets the class-flavoured analogue of each neighbourhood:
instantiation sites (incoming CALLS edges -- call resolution now targets
Class nodes for constructor calls, see
LatticeBackend.find_symbols_by_properties), its methods, its base classes
and its subclasses. Verified on a 2-file fixture: a `Widget(label)` call
site really does produce a CALLS edge whose target is the Class node.

Serves the goal in docs/explanation/latticedb-migration.md's Section 18
(LLM Context Strategy): one command that gives an LLM "a real nice context"
from a single seed, in place of a grep loop.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .analyzer.export_parquet import make_class_id, make_function_id
from .graph import DependencyGraph
from .source_provider import FilesystemSourceProvider, SourceProvider

# How many BM25 Class hits to probe when looking for subclasses defined
# outside the seed's own file. Small on purpose: this is a best-effort
# widening of an inherently approximate lookup (see _subclass_rows), not a
# search feature, and every hit costs one indexed name lookup.
_SUBCLASS_PROBE_LIMIT = 25

# Rough token estimate: ~4 characters per token. Deliberately not a real
# tokenizer -- adding tiktoken/transformers as a dependency to budget a
# code bundle isn't worth it. What this can get wrong: dense code with many
# short symbols tokenizes worse than 4 chars/token, so a bundle sized at
# the budget can overshoot by roughly 10-25% on code-heavy input. Treat the
# budget as a target, not a hard ceiling.
_CHARS_PER_TOKEN = 4

# Per-node markdown overhead (heading + fences + blank line), in tokens.
_NODE_OVERHEAD_TOKENS = 12

# Depth 3 rather than 2 because the measurement below says the third hop is
# nearly free on an accurately-resolved graph: on gemseo's LatticeDB index
# the median seed reaches 2 nodes at depth 2 and still only 2 at depth 3
# (p90: 10 -> 11), for 8ms of traversal. Depth 2 would leave that recall on
# the table for no saving. The token budget, not the depth, is what bounds
# the bundle.
DEFAULT_DEPTH = 3
DEFAULT_TOKEN_BUDGET = 12_000

# Skip expanding *through* a node with more than this many edges in the
# direction being followed; the node itself is still returned as a result.
#
# Measured, not guessed: perfo/benchmark_fanout.py over seeds sampled from
# gemseo's 11,416 Function nodes (2,103 files). Reachable-set size,
# median / p90 / max.
#
# On the SQLite index (naive CallResolver, 338,072 CALLS edges, 40 seeds):
#
#            depth 1        depth 2          depth 3
#   no cap   2 / 36 / 518   8 /  534 / 1083  14 / 1187 / 1664
#   cap 20   2 / 36 / 518   4 /  118 /  727   4 /  239 /  897
#   cap 60   2 / 36 / 518   6 /  244 /  758  14 /  593 /  946
#   cap 150  2 / 36 / 518   6 /  264 /  758  14 /  754 /  959
#
# On the LatticeDB index (import-aware resolution, ~22x fewer and far more
# accurate CALLS edges, 20 seeds):
#
#            depth 1       depth 2       depth 3
#   no cap   1 / 5 / 11    2 / 10 / 19   2 / 11 / 19
#   cap 60   1 / 5 / 11    2 / 10 / 19   2 / 11 / 19   (identical -- no-op)
#
# What the data says, and it is not what was expected. Hub explosion is a
# symptom of *spurious* edges, not of real code: on the accurate graph the
# worst seed of 20 reaches 19 nodes at depth 3 and the cap never fires at
# all. On the naive graph it fires hard -- the p90 seed reaches 1,187
# nodes, a tenth of every function in the repo, which says nothing about
# the seed. So the guard is kept, but as insurance for the sqlite backend
# (and for any future corpus with genuine god-functions), not as the load-
# bearing mechanism it was assumed to be.
#
# 60 rather than something tighter because a tight cap prunes ordinary
# code, not hubs: 20 cuts the sqlite p90 from 1,187 to 239 but also guts
# the *median* seed there, 14 -> 4. 60 leaves the median untouched at every
# depth on both backends and still halves the p90.
#
# It is a threshold on fan-out in the direction being followed, not on
# importance: a 300-caller helper like a logger is still returned when it
# is a neighbour, it just doesn't drag its 300 callers in behind it.
DEFAULT_HUB_DEGREE = 60


@dataclass
class ContextNode:
    """A single function's source, with its call-site/definition location."""

    name: str
    file: str
    line_number: int
    source_code: str
    # Hops from the seed. 0 for the seed, 1 for a direct neighbour. Left at
    # 1 by the one-hop assemblers, which only ever produce direct neighbours.
    distance: int = 1
    # True when the token budget ran out and `source_code` holds only the
    # signature + first docstring line instead of the body (see
    # _fill_sources): degrading beats truncating mid-function, which yields
    # code an LLM will read as complete and isn't.
    abridged: bool = False


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
                    hops = f" [{c.distance} hop{'s' if c.distance != 1 else ''}]" if c.distance > 1 else ""
                    abridged = " (signature only -- token budget)" if c.abridged else ""
                    lines.append(
                        f"    {c.name} ({c.file}:{c.line_number}){hops}{abridged}"
                    )
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
                suffix = section.role
                if c.distance > 1:
                    suffix += f", {c.distance} hops"
                if c.abridged:
                    suffix += ", signature only"
                lines.append(f"### {c.file}::{c.name} ({suffix})")
                lines.append("```python")
                lines.append(c.source_code)
                lines.append("```")
                lines.append("")

        return "\n".join(lines)


@dataclass
class ReachedNode:
    """One node found while traversing out from the seed, before ranking.

    Carries only what traversal already handed us for free -- no source
    (that's a disk read, deferred until after ranking) and no extra query.
    """

    node_id: str
    label: str  # "Function" or "Class"
    name: str
    file: str
    call_line: int
    start_line: int
    end_line: int
    distance: int
    direction: str  # "caller" (upstream) or "callee" (downstream)
    # Fan-out of this node, filled in only if we actually expanded it (a
    # node found at max depth is never expanded, so its degree stays 0 --
    # see _centrality_signal for what that costs the ranking).
    in_degree: int = 0
    out_degree: int = 0
    score: float = 0.0


def _estimate_tokens(text: str) -> int:
    """len/4, see _CHARS_PER_TOKEN."""
    return len(text) // _CHARS_PER_TOKEN


def _signature_of(source_code: str) -> str:
    """Signature + first docstring line, for a node degraded by the budget.

    A local re-implementation rather than an import of ingest.py's
    _signature_text: that one exists to build BM25 text and doesn't carry
    the docstring, and ingest.py is another module's concern. Same cheap
    rule -- join lines until one ends in ':' -- plus the first docstring
    line, which is usually the single most informative line for a reader
    deciding whether to go look at the body.
    """
    lines = source_code.splitlines()
    out: List[str] = []
    for line in lines[:20]:
        out.append(line.rstrip())
        if line.rstrip().endswith(":"):
            break
    for line in lines[len(out) : len(out) + 3]:
        stripped = line.strip()
        if stripped.startswith(('"""', "'''", '"', "'")):
            out.append(line.rstrip())
            break
    out.append("    ...  # body omitted (token budget)")
    return "\n".join(out)


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

    # ---- Multi-hop expansion ------------------------------------------
    #
    # Collect to `depth`, rank the whole set, then read source only for the
    # winners. See the module docstring for why the frontier is NOT pruned
    # level by level.

    def _neighbour_id(self, file: str, name: str, start_line: int, label: str) -> str:
        """Canonical id of a node we only know by (file, name, start_line).

        get_call_edges_with_lines returns neighbours as tuples, not ids, so
        multi-hop traversal needs an id to keep walking. Rather than pay a
        lookup query per neighbour (which is what would make wide traversal
        expensive), we recompute the id: it is a pure sha256 of
        "rel_file::name::start_line" (analyzer/export_parquet.make_function_id),
        and every writer -- generic ingest, the streaming path, the Kuzu
        bulk loader -- goes through those same two helpers.

        The hypothesis, stated because it is a real coupling: if some future
        ingest path ever mints ids differently, expansion silently stops at
        depth 1 (the recomputed id matches nothing) instead of erroring.
        perfo/benchmark_fanout.py catches that -- a broken id scheme shows
        up immediately as depth-2 sets no bigger than depth-1 ones.
        """
        make = make_class_id if label == "Class" else make_function_id
        return make(file, name, start_line, self.graph.project_root)

    def _edges(self, node_id: str, label: str):
        """(callers, callees) for one node, tolerating backends whose
        get_call_edges_with_lines predates the `label` parameter."""
        try:
            return self.graph.backend.get_call_edges_with_lines(node_id, label=label)
        except TypeError:
            if label != "Function":
                return [], []
            return self.graph.backend.get_call_edges_with_lines(node_id)
        except Exception:
            # One unreachable node shouldn't abort a bundle -- same
            # best-effort stance as _resolve_nodes.
            return [], []

    def collect(
        self,
        seed_id: str,
        seed_label: str = "Function",
        depth: int = DEFAULT_DEPTH,
        direction: str = "both",
        hub_degree: int = DEFAULT_HUB_DEGREE,
    ) -> List[ReachedNode]:
        """Breadth-first reachable set out to `depth`, both directions.

        Expansion is direction-pure: a node reached by following callers
        only ever expands its own callers. Mixing directions mid-path would
        return "callees of my callers" -- siblings, which are usually
        unrelated and which multiply the frontier by in-degree x out-degree
        per level. Keeping paths pure preserves the two things the caller
        actually asked for: what influences the seed, and what it influences.

        hub_degree caps expansion *through* a node, never its inclusion --
        see DEFAULT_HUB_DEGREE for the measurement behind the number.
        """
        want_up = direction in ("both", "upstream")
        want_down = direction in ("both", "downstream")

        best: Dict[str, ReachedNode] = {}
        seen: set = {(seed_id, "caller"), (seed_id, "callee")}

        seed_callers, seed_callees = self._edges(seed_id, seed_label)
        pending: List[tuple] = []
        if want_up:
            pending.extend((*row, "caller") for row in seed_callers)
        if want_down:
            pending.extend((*row, "callee") for row in seed_callees)

        # Level by level, so `distance` is the true shortest hop count: the
        # first time a node is seen is necessarily via a shortest path.
        for dist in range(1, depth + 1):
            next_pending: List[tuple] = []
            for file, name, call_line, start_line, end_line, arrow in pending:
                if start_line is None or end_line is None:
                    continue  # an external-symbol endpoint: no source to show
                node_id = self._neighbour_id(file, name, start_line, "Function")
                if (node_id, arrow) in seen:
                    continue
                seen.add((node_id, arrow))
                node = ReachedNode(
                    node_id=node_id,
                    label="Function",
                    name=name,
                    file=file,
                    call_line=call_line if call_line is not None else start_line,
                    start_line=start_line,
                    end_line=end_line,
                    distance=dist,
                    direction=arrow,
                )
                # A node reachable both ways (mutual recursion, or a helper
                # that both calls and is called by the seed's neighbourhood)
                # keeps whichever side found it first -- i.e. the shorter path.
                if node_id not in best:
                    best[node_id] = node
                if dist >= depth:
                    continue
                callers, callees = self._edges(node_id, "Function")
                node.in_degree = len(callers)
                node.out_degree = len(callees)
                rows = callers if arrow == "caller" else callees
                fan_out = node.in_degree if arrow == "caller" else node.out_degree
                if hub_degree and fan_out > hub_degree:
                    continue  # hub: keep the node, don't expand through it
                next_pending.extend((*row, arrow) for row in rows)
            pending = next_pending
            if not pending:
                break
        return list(best.values())

    def _bm25_scores(self, query: Optional[str], probe: int = 100) -> Dict[str, float]:
        """{node_id: normalized BM25 score} for the query, or {} without one.

        One search call, not one per node: BM25 can only tell us about the
        nodes it ranks, so anything outside the top `probe` simply gets no
        query signal (score 0) rather than a wrong one. `probe` is much
        larger than the search command's own --limit on purpose -- a depth-2
        neighbour that BM25 ranked 40th is exactly the case this is for.
        """
        if not query:
            return {}
        try:
            hits = self.graph.backend.search_text(query, limit=probe)
        except Exception:
            # No FTS engine (Kuzu) or no index built -- expansion still
            # works, it just ranks on graph signals alone.
            return {}
        if not hits:
            return {}
        top = max(h.score for h in hits) or 1.0
        return {h.node_id: max(h.score, 0.0) / top for h in hits}

    @staticmethod
    def _centrality_signal(in_degree: int) -> float:
        """log-scaled in-degree, 0..1, saturating around 20 callers.

        Deliberately a small term in the score. In-degree is an ambiguous
        signal: a function several places call is more likely to matter to
        a reader than one nothing calls, but at the extreme it inverts --
        everything calls log(), and log() tells you nothing about the seed.
        That inverted end is handled structurally by the hub cap rather
        than by the score, so this stays a gentle nudge. Nodes we never
        expanded have in_degree 0 and get nothing here: that under-rates
        the deepest level, which is acceptable since distance already ranks
        it last anyway.
        """
        return min(math.log1p(in_degree) / math.log1p(20), 1.0)

    def rank(
        self, nodes: List[ReachedNode], query: Optional[str] = None
    ) -> List[ReachedNode]:
        """Score the whole collected set at once and sort it, best first.

        score = 1/(1+distance) + 0.6*bm25 + 0.15*centrality

        Weights are a judgement call, not a fit. Distance dominates (a
        direct neighbour beats a two-hop one, all else equal) but 0.6 of
        BM25 is enough for a strong query match at depth 2 (1/3 + 0.6 =
        0.93) to outrank a depth-1 node with no query signal (0.5) -- which
        is the entire point of collecting first and ranking after. Weighted
        below ~0.34, no depth-2 node could ever overtake a depth-1 one and
        this would be beam search with extra steps.

        Not used, and worth stating: CALLS edges carry only call_line today
        (graph/ingest.py), so edge confidence / resolution_method are not
        available to this ranking without a backend change.
        """
        bm25 = self._bm25_scores(query)
        for node in nodes:
            node.score = (
                1.0 / (1 + node.distance)
                + 0.6 * bm25.get(node.node_id, 0.0)
                + 0.15 * self._centrality_signal(node.in_degree)
            )
        return sorted(nodes, key=lambda n: (-n.score, n.distance, n.file, n.name))

    def _fill_sources(self, ranked: List[ReachedNode], token_budget: int):
        """Read source for as many ranked nodes as the budget allows.

        The only place this walk touches disk, and it walks in rank order,
        so the expensive operation is paid for winners only -- the cost
        asymmetry the whole design rests on (see the module docstring).

        Degrade, don't truncate: once a node's full source doesn't fit, it
        and everything after it are rendered as signature + docstring line.
        A mid-function cut would hand an LLM code that reads as complete and
        isn't. Stops entirely when even a signature no longer fits.

        Returns (kept, dropped) where kept is [(node, source, abridged)].
        """
        kept: List[Tuple[ReachedNode, str, bool]] = []
        spent = 0
        degraded = False
        for i, node in enumerate(ranked):
            try:
                source = self.source_provider.get_range(
                    node.file, node.start_line, node.end_line
                )
            except (ValueError, FileNotFoundError) as e:
                source = f"(could not read source: {e})"
            cost = _estimate_tokens(source) + _NODE_OVERHEAD_TOKENS
            if degraded or spent + cost > token_budget:
                degraded = True
                source = _signature_of(source)
                cost = _estimate_tokens(source) + _NODE_OVERHEAD_TOKENS
                if spent + cost > token_budget:
                    return kept, len(ranked) - i
            spent += cost
            kept.append((node, source, degraded))
        return kept, 0

    def expand(
        self,
        file: str,
        name: str,
        node_type: str = "Function",
        depth: int = DEFAULT_DEPTH,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        query: Optional[str] = None,
        direction: str = "both",
        hub_degree: int = DEFAULT_HUB_DEGREE,
    ) -> CodeContext:
        """Collect to `depth`, rank, and render under `token_budget`.

        The single expansion engine behind both `search` (which finds the
        seed first) and `impact` (which is handed one). `query`, when the
        seed came from a search, feeds BM25 relevance into the ranking.

        A Class seed delegates to assemble_class_context: its
        neighbourhoods are structural (methods, bases, subclasses), so
        "two hops away" isn't a defined thing there. The token budget is
        applied to that bundle too.

        Raises:
            ValueError: if the seed isn't in the index.
            FileNotFoundError: if the seed's file can't be read from disk.
        """
        if node_type == "Class":
            return self._apply_budget(
                self.assemble_class_context(file, name), token_budget
            )

        rel_file = self.graph._to_relative_path(file)
        rows = self.graph.backend.query(
            "MATCH (f:Function {file: $file, name: $name}) "
            "RETURN f.id AS id, f.start_line AS start_line, f.end_line AS end_line "
            "ORDER BY f.start_line ASC LIMIT 1",
            {"file": rel_file, "name": name},
        )
        if not rows:
            raise ValueError(f"Function not found: {file}::{name}")
        seed_row = rows[0]
        seed = ContextNode(
            name=name,
            file=rel_file,
            line_number=seed_row["start_line"],
            source_code=self.source_provider.get_range(
                rel_file, seed_row["start_line"], seed_row["end_line"]
            )
            or "",
            distance=0,
        )

        reached = self.collect(
            seed_row["id"],
            "Function",
            depth=depth,
            direction=direction,
            hub_degree=hub_degree,
        )
        ranked = self.rank(reached, query=query)
        # The seed's own source is never negotiable -- it is the thing being
        # asked about -- so it comes off the budget before anything else.
        remaining = max(token_budget - _estimate_tokens(seed.source_code), 0)
        kept, dropped = self._fill_sources(ranked, remaining)

        up: List[ContextNode] = []
        down: List[ContextNode] = []
        for node, source, abridged in kept:
            ctx_node = ContextNode(
                name=node.name,
                file=node.file,
                line_number=node.call_line,
                source_code=source,
                distance=node.distance,
                abridged=abridged,
            )
            (up if node.direction == "caller" else down).append(ctx_node)

        dropped_nodes = ranked[len(kept):]
        n_up_dropped = sum(1 for n in dropped_nodes if n.direction == "caller")
        sections = [
            ContextSection(
                f"Upstream -- what calls this (<= {depth} hops)",
                "caller",
                up,
                n_up_dropped,
            ),
            ContextSection(
                f"Downstream -- what this calls (<= {depth} hops)",
                "callee",
                down,
                len(dropped_nodes) - n_up_dropped,
            ),
        ]
        return CodeContext(seed=seed, callers=up, callees=down, sections=sections)

    def _apply_budget(self, ctx: CodeContext, token_budget: int) -> CodeContext:
        """Degrade an already-assembled bundle's nodes to signatures once the
        budget runs out.

        Used for the Class path, whose sections come from structural queries
        rather than from rank order, so there is nothing to rank and the
        source has already been read. Same degrade-don't-truncate rule.
        """
        spent = _estimate_tokens(ctx.seed.source_code)
        degraded = False
        for section in ctx.resolved_sections():
            for node in section.nodes:
                cost = _estimate_tokens(node.source_code) + _NODE_OVERHEAD_TOKENS
                if degraded or spent + cost > token_budget:
                    degraded = True
                    node.source_code = _signature_of(node.source_code)
                    node.abridged = True
                    cost = _estimate_tokens(node.source_code) + _NODE_OVERHEAD_TOKENS
                spent += cost
        return ctx

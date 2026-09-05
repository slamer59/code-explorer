#!/usr/bin/env python3
"""Measure how much of the unresolved-call tail is *polymorphic method calls*.

The finalize pass on gemseo leaves ~7.7K unresolved references, of which the
report buckets ~97% as "no import resolved" -- `discipline.execute()`,
`design_space.add_variable()`. That bucket lumps two very different things
together:

  * a method name that IS defined on some class in the corpus (resolvable in
    principle, if the receiver's type were known), and
  * a builtin / stdlib / third-party name that never will be (`append`,
    `len`, `array.reshape`).

This script splits them, then asks how ambiguous the first group is (how many
distinct classes define a method of that name) and whether a cheap signal --
a type annotation on the receiver, or a constructor assignment in the same
function -- would disambiguate it.

It does NOT write an index. It re-runs the same resolver the sqlite build
uses (graph/import_resolver.py's two-pass loop over
LatticeStreamingIngestor._resolution) and inspects the leftovers.

    uv run --python 3.12 --extra dev python perfo/benchmark_duck_typing.py /path/to/repo
"""

from __future__ import annotations

import argparse
import ast
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from rich.console import Console
from rich.table import Table

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.export_parquet import (
    make_class_id,
    make_function_id,
    to_relative_path,
)
from code_explorer.graph.lattice_streaming import (
    LatticeStreamingIngestor,
    ProjectScope,
    _records_for_file,
)

console = Console()


def build(results, project_root: Path):
    scope = ProjectScope.from_project_root(project_root)
    index: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    info_by_id: Dict[str, Tuple[str, str, int]] = {}
    for analysis in results:
        rel_file = to_relative_path(analysis.file_path, project_root)
        module = scope.module_for(rel_file)
        for function in analysis.functions:
            fid = make_function_id(
                analysis.file_path, function.name, function.start_line, project_root
            )
            candidate = {
                "id": fid,
                "name": function.name,
                "file": rel_file,
                "module": module,
                "parent_class": function.parent_class or "",
                "node_type": "Function",
            }
            index[("name", function.name)].append(candidate)
            index[("file", rel_file)].append(candidate)
            index[("module", module)].append(candidate)
            if function.parent_class:
                index[("parent_class", function.parent_class)].append(candidate)
            info_by_id[fid] = (rel_file, function.name, function.start_line)
        for class_info in analysis.classes:
            cid = make_class_id(
                analysis.file_path, class_info.name, class_info.start_line, project_root
            )
            candidate = {
                "id": cid,
                "name": class_info.name,
                "file": rel_file,
                "module": module,
                "parent_class": "",
                "node_type": "Class",
            }
            index[("name", class_info.name)].append(candidate)
            index[("file", rel_file)].append(candidate)
            index[("module", module)].append(candidate)
            info_by_id[cid] = (rel_file, class_info.name, class_info.start_line)
    return scope, index, info_by_id


def unresolved_references(results, project_root: Path, scope, index):
    references: List[Dict[str, Any]] = []
    for analysis in results:
        _n, _e, refs, _x, _d, _s = _records_for_file(
            analysis, project_root, include_source=False, scope=scope
        )
        references.extend(refs)

    def resolve_one(reference, finalize):
        lookup = reference["target_name"] or reference["called_name"]
        by_id = {c["id"]: c for c in index[("name", lookup)]}
        if reference["target_module"]:
            by_id.update(
                {c["id"]: c for c in index[("module", reference["target_module"])]}
            )
        by_id.update({c["id"]: c for c in index[("file", reference["caller_file"])]})
        for base in reference["caller_bases"] or []:
            by_id.update({c["id"]: c for c in index[("parent_class", base)]})
        return LatticeStreamingIngestor._resolution(
            reference, list(by_id.values()), finalize=finalize
        )

    resolved = 0
    pending = references
    for finalize in (False, True):
        batch, pending = pending, []
        for reference in batch:
            target, method = resolve_one(reference, finalize=finalize)
            if target is not None and method is not None:
                resolved += 1
            else:
                pending.append(reference)
    return len(references), resolved, pending


# ---------------------------------------------------------------- signals


class _Signals:
    """Per-function receiver-type evidence, harvested with one AST pass.

    HYPOTHESIS: the cheap signals a resolver could use without a type
    inferencer are (a) a parameter annotation naming a class, (b) a local
    assignment from a constructor call, (c) `self.x` where the class body or
    __init__ annotates/assigns x from a constructor. Everything else needs
    real inference. What this can get wrong: it reads annotations
    syntactically, so `d: Discipline | None` and `d: Sequence[Discipline]`
    are recorded by their outermost name (`Discipline` and `Sequence`), and
    a rebinding later in the function is not tracked.
    """

    def __init__(self) -> None:
        # (relative_file, function_start_line) -> {receiver name: evidence kind}
        self.by_function: Dict[Tuple[str, int], Dict[str, Tuple[str, str]]] = {}
        # (relative_file, class_name) -> {attribute name: evidence kind}
        self.by_class_attr: Dict[Tuple[str, str], Dict[str, Tuple[str, str]]] = {}

    @staticmethod
    def _annotation_name(node) -> str:
        while isinstance(node, ast.Subscript):
            node = node.value
        if isinstance(node, ast.BinOp):  # X | None
            return _Signals._annotation_name(node.left)
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                return _Signals._annotation_name(
                    ast.parse(node.value, mode="eval").body
                )
            except SyntaxError:
                return ""
        return ""

    @staticmethod
    def _ctor_name(node) -> str:
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                return func.id
            if isinstance(func, ast.Attribute):
                return func.attr
        return ""

    def scan(self, path: Path, rel_file: str) -> None:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                attrs = self.by_class_attr.setdefault((rel_file, node.name), {})
                for sub in ast.walk(node):
                    if isinstance(sub, ast.AnnAssign):
                        target = sub.target
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                        ):
                            name = self._annotation_name(sub.annotation)
                            if name:
                                attrs[target.attr] = ("annotation", name)
                        elif isinstance(target, ast.Name):
                            name = self._annotation_name(sub.annotation)
                            if name:
                                attrs[target.id] = ("annotation", name)
                    elif isinstance(sub, ast.Assign):
                        ctor = self._ctor_name(sub.value)
                        if not ctor:
                            continue
                        for target in sub.targets:
                            if (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == "self"
                            ):
                                attrs.setdefault(target.attr, ("constructor", ctor))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                receivers: Dict[str, Tuple[str, str]] = {}
                args = node.args
                for arg in (
                    list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
                ):
                    if arg.annotation is None:
                        continue
                    name = self._annotation_name(arg.annotation)
                    if name:
                        receivers[arg.arg] = ("annotation", name)
                for sub in ast.walk(node):
                    if isinstance(sub, ast.AnnAssign) and isinstance(
                        sub.target, ast.Name
                    ):
                        name = self._annotation_name(sub.annotation)
                        if name:
                            receivers.setdefault(sub.target.id, ("annotation", name))
                    elif isinstance(sub, ast.Assign):
                        ctor = self._ctor_name(sub.value)
                        if not ctor:
                            continue
                        for target in sub.targets:
                            if isinstance(target, ast.Name):
                                receivers.setdefault(target.id, ("constructor", ctor))
                self.by_function[(rel_file, node.lineno)] = receivers

    def evidence(self, reference, caller_line: int) -> Tuple[str, str]:
        """(evidence kind, the type name it names) for this call's receiver."""
        qualifier = reference["qualifier"] or ""
        if not qualifier:
            return "no receiver", ""
        key = (reference["caller_file"], caller_line)
        if qualifier.startswith("self."):
            attr = qualifier.split(".", 1)[1]
            attrs = self.by_class_attr.get(
                (reference["caller_file"], reference["caller_class"]), {}
            )
            return attrs.get(attr, ("none", ""))
        if "." in qualifier:
            return "none", ""  # chained receiver: a.b.c -- out of scope
        return self.by_function.get(key, {}).get(qualifier, ("none", ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    root = args.path.resolve()

    t0 = time.perf_counter()
    results = list(
        CodeAnalyzer().iter_analyze_directory(root, max_workers=args.workers)
    )
    console.print(f"parsed {len(results):,} files in {time.perf_counter() - t0:.1f}s")

    scope, index, info_by_id = build(results, root)
    total, resolved, pending = unresolved_references(results, root, scope, index)
    console.print(
        f"[cyan]{total:,}[/cyan] internal references: "
        f"[green]{resolved:,}[/green] resolved, [yellow]{len(pending):,}[/yellow] not"
    )

    # Method names defined anywhere in the corpus, and on how many classes.
    classes_by_method: Dict[str, set] = defaultdict(set)
    for (key, value), candidates in list(index.items()):
        if key != "name":
            continue
        for candidate in candidates:
            if candidate["parent_class"]:
                classes_by_method[value].add(
                    (candidate["file"], candidate["parent_class"])
                )
    any_definition = {value for (key, value) in index if key == "name"}

    # ---- (1) the split
    split: Counter = Counter()
    method_refs: List[Dict[str, Any]] = []
    for reference in pending:
        if reference["target_module"]:
            split["had an import (other gap)"] += 1
            continue
        name = reference["target_name"] or reference["called_name"]
        if name in classes_by_method:
            split["names a known method"] += 1
            method_refs.append(reference)
        elif name in any_definition:
            split["names a known module-level def/class"] += 1
        else:
            split["no definition anywhere (builtin/3rd-party)"] += 1

    table = Table(title="(1) unresolved references, split")
    table.add_column("bucket")
    table.add_column("count", justify="right")
    for bucket, count in split.most_common():
        table.add_row(bucket, f"{count:,}")
    console.print(table)

    # ---- (2) ambiguity histogram over the method-naming references
    buckets = [("1", 1, 1), ("2-3", 2, 3), ("4-10", 4, 10), ("11+", 11, 10**9)]
    hist_refs: Counter = Counter()
    hist_names: Counter = Counter()
    seen_names = set()
    for reference in method_refs:
        name = reference["target_name"] or reference["called_name"]
        n = len(classes_by_method[name])
        for label, low, high in buckets:
            if low <= n <= high:
                hist_refs[label] += 1
                if name not in seen_names:
                    hist_names[label] += 1
                break
        seen_names.add(name)

    table = Table(title="(2) how many classes define that method name")
    table.add_column("classes defining it")
    table.add_column("references", justify="right")
    table.add_column("distinct names", justify="right")
    for label, _l, _h in buckets:
        table.add_row(label, f"{hist_refs[label]:,}", f"{hist_names[label]:,}")
    console.print(table)

    # ---- (2b) what option (a) -- a duck-typed candidate edge per class,
    # capped at N candidates -- would actually cost in distinct CALLS edges.
    table = Table(title="(2b) cost of emitting duck-typed edges at cap N")
    table.add_column("cap")
    table.add_column("references covered", justify="right")
    table.add_column("distinct new edges", justify="right")
    table.add_column("vs resolved edges", justify="right")
    for cap in (1, 2, 3, 5, 10):
        covered = 0
        pairs = set()
        for reference in method_refs:
            name = reference["target_name"] or reference["called_name"]
            sites = classes_by_method[name]
            if len(sites) > cap:
                continue
            covered += 1
            for site in sites:
                pairs.add((reference["caller_id"], site, name))
        table.add_row(
            str(cap),
            f"{covered:,}",
            f"{len(pairs):,}",
            f"+{100.0 * len(pairs) / resolved:.0f}%",
        )
    console.print(table)

    # ---- (3) disambiguation signals
    signals = _Signals()
    files_by_rel = {}
    for analysis in results:
        rel = to_relative_path(analysis.file_path, root)
        files_by_rel[rel] = Path(analysis.file_path)
    needed = {reference["caller_file"] for reference in method_refs}
    t0 = time.perf_counter()
    for rel in needed:
        path = files_by_rel.get(rel)
        if path is not None:
            signals.scan(path, rel)
    console.print(
        f"AST signal pass over {len(needed):,} files in {time.perf_counter() - t0:.1f}s"
    )

    # Class hierarchy, by *name* -- the only handle an annotation or a
    # constructor call gives us. A name defined by more than one class in the
    # corpus is treated as unusable rather than guessed at.
    sites_by_class_name: Dict[str, List[Tuple[str, str, List[str]]]] = defaultdict(list)
    methods_by_site: Dict[Tuple[str, str], set] = defaultdict(set)
    for analysis in results:
        rel = to_relative_path(analysis.file_path, root)
        for class_info in analysis.classes:
            sites_by_class_name[class_info.name].append(
                (rel, class_info.name, list(class_info.bases))
            )
        for function in analysis.functions:
            if function.parent_class:
                methods_by_site[(rel, function.parent_class)].add(function.name)

    def target_for(type_name: str, method: str) -> str:
        """Walk `type_name` and its bases by name; report what we'd resolve to.

        HYPOTHESIS: a base-class name is enough to find the method, because
        the definition lives on the class or on an ancestor whose name is
        written literally in `bases`. What this can get wrong: a base
        imported under an alias, a generic base (`Generic[T]`), and multiple
        inheritance ordering -- all treated as "unknown type" or a miss
        rather than guessed.
        """
        seen = set()
        frontier = [type_name]
        depth = 0
        while frontier:
            depth += 1
            name = frontier.pop(0)
            if name in seen:
                continue
            seen.add(name)
            sites = sites_by_class_name.get(name, [])
            if len(sites) != 1:
                # 0 -> a stdlib/third-party type; >1 -> the name alone is
                # not a class identity in this corpus.
                continue
            rel, cname, bases = sites[0]
            if method in methods_by_site.get((rel, cname), ()):
                return "resolved" if name == type_name else "resolved via a base"
            frontier.extend(b.split("[")[0].split(".")[-1] for b in bases)
        return "type known, method not found" if type_name in sites_by_class_name else (
            "type not a project class"
        )

    caller_line_by_id = {fid: info[2] for fid, info in info_by_id.items()}
    evidence: Counter = Counter()
    evidence_small: Counter = Counter()
    outcome: Counter = Counter()
    new_pairs: set = set()
    direct_pairs: set = set()
    for reference in method_refs:
        line = caller_line_by_id.get(reference["caller_id"])
        if line is None:
            evidence["unknown caller"] += 1
            continue
        kind, type_name = signals.evidence(reference, line)
        evidence[kind] += 1
        name = reference["target_name"] or reference["called_name"]
        if len(classes_by_method[name]) <= 3:
            evidence_small[kind] += 1
        if kind in ("annotation", "constructor"):
            verdict = target_for(type_name, name)
            outcome[f"{kind}: {verdict}"] += 1
            if verdict.startswith("resolved"):
                new_pairs.add((reference["caller_id"], type_name, name))
                if verdict == "resolved":
                    direct_pairs.add((reference["caller_id"], type_name, name))

    table = Table(title="(3a) receiver evidence on method-naming references")
    table.add_column("evidence")
    table.add_column("all", justify="right")
    table.add_column("<=3 candidate classes", justify="right")
    for kind, count in evidence.most_common():
        table.add_row(kind, f"{count:,}", f"{evidence_small[kind]:,}")
    console.print(table)

    table = Table(title="(3b) does that evidence actually name the target?")
    table.add_column("outcome")
    table.add_column("count", justify="right")
    for kind, count in outcome.most_common():
        table.add_row(kind, f"{count:,}")
    console.print(table)

    console.print(
        f"[bold]distinct new CALLS edges[/bold]: {len(direct_pairs):,} "
        f"(method on the named class itself) / {len(new_pairs):,} "
        f"(also walking base classes)"
    )

    table = Table(title="top unresolved method names")
    table.add_column("name")
    table.add_column("refs", justify="right")
    table.add_column("classes defining it", justify="right")
    counts: Counter = Counter(
        (r["target_name"] or r["called_name"]) for r in method_refs
    )
    for name, count in counts.most_common(20):
        table.add_row(name, f"{count:,}", f"{len(classes_by_method[name]):,}")
    console.print(table)


if __name__ == "__main__":
    main()

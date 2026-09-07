"""Score the run files with ranx and render markdown.

Three properties make a benchmark worth re-running, and all three are about
plumbing rather than measurement:

1. **Every run is appended, never overwritten.** results/history.jsonl is
   committed, so a regression is visible as a delta rather than as a number
   nobody remembers the old value of.
2. **Every run records what produced it** -- tool sha, dirty flag, corpus
   sha, host, cpu count, date.
3. **The report is generated, never edited.** Hand-maintained tables drift
   from the code that produced them within a week; this one is regenerated
   from the run files every time, so it cannot.

Output is one markdown file per tool plus one summary per corpus. The
summary's cross-tool table comes from `ranx.compare()`, which does paired
Fisher randomization significance testing -- so "A is ahead of B" arrives
with a p-value attached rather than as two numbers placed side by side.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
from ranx import Qrels, Run, compare, evaluate

from . import config
from .qrels import build as build_qrels
from .qrels import load_cases

#: Reported for every run. recall@10 is the headline -- an agent reads ten
#: results, and a relevant file at rank 9 is still a file it read.
METRICS = ["recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10"]


#: Doc id used to pad a query the tool returned nothing for. ranx scores only
#: the queries present in a run, so an unpadded miss would vanish from the
#: denominator and inflate recall. A sentinel that is never relevant makes the
#: miss count as a miss. Padding must happen before Run() is constructed --
#: ranx backs a Run with a numba typed dict that rejects later insertion.
_MISS = "__no_result__"


def _padded(data: dict, qrels: Qrels, name: str) -> Run:
    """A Run covering exactly the qrels' queries -- no more, no fewer.

    Padding alone is not enough once qrels can be a subset (code-only,
    test-only): the run then carries queries the qrels no longer score, and
    ranx refuses the pair. Restricting as well as padding keeps every
    comparison over the same denominator.
    """
    wanted = set(qrels.qrels)
    run = {qid: dict(docs) for qid, docs in data["run"].items() if qid in wanted}
    for qid in wanted:
        run.setdefault(qid, {_MISS: 0.0})
    return Run(run, name=name)


def _load_runs(corpus: str) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    directory = config.RUNS / corpus
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        out[(data["tool"], data["kind"])] = data
    return out


def _cost_row(data: dict) -> dict:
    per_query = data["per_query"]
    ok = [q for q in per_query if not q["error"]]
    n = max(len(ok), 1)
    return {
        "queries": len(per_query),
        "errors": len(per_query) - len(ok),
        "median_ms": sorted(q["wall_ms"] for q in ok)[len(ok) // 2] if ok else 0.0,
        "mean_tokens": sum(q["tokens"] for q in ok) / n,
    }


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _provenance_block(data: dict) -> str:
    p = data["provenance"]
    dirty = " (dirty)" if p["tool_dirty"] else ""
    return (
        f"Generated {p['utc']} on {p['host']} ({p['cpus']} CPUs, "
        f"Python {p['python']}).\n"
        f"Tool at `{p['tool_sha']}`{dirty}, corpus at `{p['corpus_sha']}`.\n"
    )


def _scored(qrels: Qrels, data: dict) -> dict[str, float]:
    if not data["run"]:
        return {m: 0.0 for m in METRICS}
    return evaluate(qrels, _padded(data, qrels, f"{data['tool']}.{data['kind']}"), METRICS)


def render_tool(corpus: str, tool: str, runs: dict, qrels: Qrels) -> str:
    seed, bundle = runs[(tool, "seed")], runs[(tool, "bundle")]
    delivered = runs.get((tool, "delivered"), seed)
    body = [f"# {tool} on {corpus}", "", _provenance_block(seed), ""]

    body += [
        "## Retrieval quality (file level)", "",
        "`delivered` is everything one call puts in front of the model, and "
        "is the number that matters. `seed` (what search ranked) and "
        "`bundle` (what expansion added) are its two halves, shown because "
        "the split says *where* a tool wins or loses -- not because either "
        "half is what a caller receives.",
        "" if seed["expands"] else
        "This tool has no expansion step, so `bundle` repeats `seed` -- that "
        "is the correct answer for it, not a missing measurement.",
        "",
    ]
    rows = []
    for kind, data in (("delivered", delivered), ("seed", seed), ("bundle", bundle)):
        scores = _scored(qrels, data)
        rows.append([kind] + [f"{scores[m]:.3f}" for m in METRICS])
    body.append(_table(["run", *METRICS], rows))

    body += ["", "## Cost", ""]
    cost = _cost_row(seed)
    per_1k = 0.0
    if cost["mean_tokens"]:
        per_1k = _scored(qrels, delivered)["recall@10"] / (cost["mean_tokens"] / 1000)
    body.append(_table(
        ["queries", "errors", "median latency", "mean tokens", "recall@10 per 1k tokens"],
        [[str(cost["queries"]), str(cost["errors"]),
          f"{cost['median_ms']:.0f} ms", f"{cost['mean_tokens']:.0f}",
          f"{per_1k:.3f}"]],
    ))

    failures = [q for q in seed["per_query"] if q["error"]]
    if failures:
        body += ["", "## Errors", ""]
        body += [f"- `{q['qid'][:8]}` {q['query'][:60]} -- {q['error'][:120]}"
                 for q in failures[:20]]
    return "\n".join(body) + "\n"


def _unique_reach(qrels: Qrels, runs: dict, tools: list[str], kind: str) -> str:
    """Relevant files each tool found that a given other tool never returned.

    Recall says who retrieves more; it cannot say whether the tools are
    finding the *same* things. Two tools at recall 0.6 that agree completely
    are interchangeable; two that overlap barely are complementary, and the
    right answer is to run both. Only this table distinguishes those cases,
    and it is the one place a graph traversal can show what keyword and
    vector matching structurally cannot reach.
    """
    rel = qrels.qrels
    rows = []
    for tool in tools:
        mine = runs.get((tool, kind))
        if mine is None:
            continue
        for other in tools:
            if other == tool or (other, kind) not in runs:
                continue
            theirs = runs[(other, kind)]
            n = sum(
                len((set(mine["run"].get(q, {})) & set(docs))
                    - set(theirs["run"].get(q, {})))
                for q, docs in rel.items()
            )
            total = sum(len(set(mine["run"].get(q, {})) & set(docs))
                        for q, docs in rel.items())
            share = f"{n / total:.0%}" if total else "--"
            rows.append([tool, other, str(n), str(total), share])
    return _table(
        ["tool", "vs", "relevant files it alone found", "relevant files it found", "share unique"],
        rows,
    )


def render_summary(corpus: str, runs: dict, qrels: Qrels, n_queries: int,
                   cases_for_subset: list[dict] | None = None) -> str:
    tools = sorted({tool for tool, _ in runs})
    body = [
        f"# {corpus}: cross-tool summary", "",
        f"{n_queries} queries mined from the corpus's own git history: the "
        "commit subject is the query, the files it touched are the relevant "
        "documents. Scored at **file level**, the only identifier every code "
        "search tool can produce.", "",
    ]
    any_run = next(iter(runs.values()))
    body += [_provenance_block(any_run), ""]

    # The split first, because the aggregate hides the finding: a query set
    # mined from commits mixes two opposite questions, and averaging them
    # rewards a tool for being mediocre at both.
    for subset, question in (("code", "« où est-ce implémenté ? »"),
                             ("test", "« qu'est-ce qui couvre ça ? »")):
        sub_qrels = Qrels(build_qrels(cases_for_subset, "file", subset))
        present = [(t, runs[(t, "delivered")]) for t in tools
                   if (t, "delivered") in runs and runs[(t, "delivered")]["run"]]
        if len(present) < 2:
            continue
        report = compare(
            sub_qrels, [_padded(d, sub_qrels, t) for t, d in present],
            METRICS, max_p=0.05,
        )
        body += [
            f"## `delivered`, ground truth = {subset} only", "",
            f"The {len(sub_qrels.qrels)} queries whose answer set contains "
            f"non-test files ({subset} = {question}).", "",
            "```", str(report).rstrip(), "```", "",
        ]

    for kind in ("delivered", "seed", "bundle"):
        present = [(t, runs[(t, kind)]) for t in tools if (t, kind) in runs]
        present = [(t, d) for t, d in present if d["run"]]
        if len(present) < 2:
            continue
        ranx_runs = [_padded(data, qrels, tool) for tool, data in present]
        report = compare(qrels, ranx_runs, METRICS, max_p=0.05)
        # str(report), not to_dataframe(): the dataframe drops the
        # superscripts, which are the only part of the table that says
        # whether a gap is real or noise.
        body += [
            f"## `{kind}`", "",
            "```", str(report).rstrip(), "```", "",
            "A superscript marks a win that is statistically significant over "
            "the lettered model (paired Fisher randomization, p < 0.05). "
            "A bare number is a gap the data does not support.", "",
        ]

    body += [
        "## Complementarity", "",
        "Recall says who retrieves more. It cannot say whether two tools "
        "retrieve the *same* things -- and that is the difference between a "
        "tool being redundant and a tool being worth running alongside "
        "another.", "",
        _unique_reach(qrels, runs, tools, "delivered"),
        "",
        "A high share-unique against a stronger tool means the two are "
        "complementary rather than ranked: the files behind that number are "
        "ones the other tool never returned at any rank.", "",
    ]

    body += [
        "## Cost", "",
        "Query latency and tokens are paid on every question the agent asks. "
        "Index build is paid once per corpus, and is only reported for a run "
        "that actually rebuilt -- a tool whose index was reused shows "
        "`reused`, never a misleadingly small number.", "",
    ]
    rows = []
    for tool in tools:
        data = runs.get((tool, "seed"))
        if data is None:
            continue
        cost = _cost_row(data)
        ms = data.get("index_ms")
        build = f"{ms / 60000:.1f} min" if ms else "reused"
        rows.append([tool, str(cost["errors"]), f"{cost['median_ms']:.0f} ms",
                     f"{cost['mean_tokens']:.0f}", build])
    body.append(_table(
        ["tool", "errors", "median latency", "mean tokens", "index build"], rows))

    body += ["## What actually ran", "", _table(
        ["tool", "observed retrieval mode(s)", "vector model", "expansion step"],
        [[tool,
          ", ".join(sorted({q["mode"] for q in runs[(tool, "seed")]["per_query"]
                            if q.get("mode")})) or "not reported",
          runs[(tool, "seed")].get("embedding") or "none",
          "yes" if runs[(tool, "seed")]["expands"] else "no"]
         for tool in tools if (tool, "seed") in runs],
    ), "",
        "Retrieval mode is read back from each tool per query, not assumed: "
        "it usually depends on which indexes were built rather than on a "
        "documented default. The vector model is recorded because a hybrid "
        "tool's quality is a property of its embedding as much as of its "
        "retrieval logic -- two tools compared under different models are "
        "partly a comparison of the models.", ""]

    notes = [
        (tool, note)
        for tool in tools
        for note in (config.tool_options(tool).get("notes") or [])
    ]
    if notes:
        body += [
            "## Asymmetries", "",
            "Declared by each adapter, stated and not corrected for -- "
            "silently normalising them would hide real differences in what "
            "each tool is for.", "",
        ]
        body += [f"- **{tool}** -- {note}" for tool, note in notes]
        body += [""]
    return "\n".join(body) + "\n"


@click.command()
@click.option("--corpus", "corpora", multiple=True)
def main(corpora: tuple[str, ...]) -> None:
    """Render one report per tool plus a summary, per corpus."""
    for corpus in (list(corpora) or list(config.corpora())):
        runs = _load_runs(corpus)
        if not runs:
            click.echo(f"{corpus}: no run files; run `python -m bench.runner` first")
            continue
        _, cases = load_cases(config.queryset_path(corpus))
        n = next(iter(runs.values()))["n_queries"]
        qrels = Qrels(build_qrels(cases[:n], "file"))

        out = config.REPORTS / corpus
        out.mkdir(parents=True, exist_ok=True)
        for tool in sorted({t for t, _ in runs}):
            if (tool, "seed") not in runs or (tool, "bundle") not in runs:
                continue
            (out / f"{tool}.md").write_text(render_tool(corpus, tool, runs, qrels))
        (out / "summary.md").write_text(
            render_summary(corpus, runs, qrels, n, cases[:n]))
        click.echo(f"{corpus}: wrote {out}")


if __name__ == "__main__":
    main()

# Benchmarking: measuring whether the answer is right

`perfo/` holds twenty-odd benchmark scripts and every one of them measures
*mechanics* — ingest speed, batch size, index size, fan-out. Not one measures
whether what comes back is **correct**. That is the only number the product
goal cares about, and every performance argument this project has had was
settled without it.

`bench/` exists to produce that number, and to produce it for other tools too.

## Why the harness is external

The first version lived in `perfo/eval/`, imported `code_explorer` in-process,
computed its own recall, and rendered its own tables. It could only ever grade
one tool — and a benchmark that can only grade its author's tool is not a
benchmark, it is a press release.

So `bench/` is a separate package with its own `pyproject.toml`, and it may
never import `code_explorer`. Every tool under test is a **subprocess**: the
harness gives it a corpus path and a query string, reads its stdout, and
normalises whatever comes back. Adding a third tool is an adapter file, not a
refactor. It also means the numbers include interpreter startup and index-open
cost, because the user pays those too.

## Ground truth without hand-labeling

The obvious approach — write fifty queries and mark the right answers by hand —
is slow, does not move to a new repository, and is biased: you write queries for
code you already know is indexed well.

A merged commit is a free labeled example instead. Its subject line is the
query a developer would have asked; the files it touched are the answer set.
`bench/bench/queryset.py` mines them, thousands per repo, no manual labeling.

Selection is deliberately narrow. A commit qualifies only if it touches 2–8
distinct symbols across ≥2 files: single-symbol commits are findable by grep and
prove nothing, and 50-symbol refactors have no coherent "answer". What is left is
exactly the case the product claims — evidence spans files, the entry point is
not known in advance.

The subject line is used **verbatim**, with only conventional-commit noise
(`fix:`, `[core]`) and issue refs (`(#1234)`) stripped. Polishing it into
something BM25 likes would be marking our own homework; an agent's guess is messy
prose too.

Known limits, stated rather than hidden: the miner parses `def`/`class` from diff
hunks, so it is **Python-only**; and a corpus needs its own git history, which
rules out any checkout whose `.git` resolves to an enclosing repository.

## The interchange format is what makes it generic

Every tool is reduced to TREC-style rows: `(query_id, doc_id, rank, score)`.

**`doc_id` is the repo-relative file path.** This is the only honest common
denominator. `zg` returns text chunks with no guaranteed symbol identity;
code-explorer returns whole symbols. Both know which file a result came from.
Scoring at file level is what makes them comparable at all — symbol-level numbers
are reported separately and never mixed into a cross-tool table.

Because a run file is just those rows plus provenance, it stays re-scorable years
later under a metric nobody had thought of when it was recorded.

## Two runs per tool, one ground truth

- **`seed`** — the ranked hits search returned. Does step 1 work?
- **`bundle`** — the files the tool actually puts in front of the model. For
  code-explorer that is the seed plus everything graph expansion reached; for a
  tool with no expansion step it repeats `seed`, which is that tool's correct
  answer rather than a missing measurement.

Scoring both against the same qrels is what tests the product's central claim. A
commit touched N files; search finds one; does expansion supply the other N−1, or
does it spend tokens narrowing the answer? The `bundle` row is where that gets
settled, and it is free to come out badly.

## Best configuration, not default configuration

Comparing two tools' out-of-the-box defaults measures packaging decisions. So
`adapters.toml` holds one entry per **configuration**, and a tool may appear
several times — `code-explorer` (FTS only) and `code-explorer-hybrid` (FTS fused
with a vector index) are separate rows of the same adapter.

This matters here because code-explorer's retrieval mode is not a fixed default
at all: `search` fuses a vector index whenever one exists on the corpus
(`cli.py`, `hybrid = not fuzzy and not semantic and vector_db_path.exists()`).
The mode therefore depends on what was built, not on what was documented — which
is exactly the kind of claim that belongs in a measurement.

Two mechanisms keep that honest, both declarative and both tool-neutral:

- `prepare` — extra flag sets run once at index time, so a configuration can
  build the capability it claims (`[["--semantic"]]` builds the vector index).
- `reset` — corpus-relative paths deleted before indexing, so a capability built
  by one configuration does not leak into the next one that shares its index
  directory.

And the report does not take any of it on trust: every adapter reports the
retrieval mode it observed **per query**, and the summary prints what actually
ran next to the scores.

## Nothing is scored by us

| Half | Tool | Why |
|---|---|---|
| Retrieval quality | [`ranx`](https://github.com/AmenRa/ranx) | TREC/BEIR-standard recall@k, MRR, nDCG. `ranx.compare()` does paired Fisher randomization, so a cross-tool table carries significance markers instead of two numbers placed side by side. |
| Latency | [`hyperfine`](https://github.com/sharkdp/hyperfine) | Warmups, outlier detection, shell-spawn compensation, JSON export. A hand-rolled timing loop gets all four subtly wrong and reports a mean with no confidence interval. |

Reimplementing either would mean defending our own arithmetic in every argument
about the results. Delegating means the only thing left to argue about is the
measurement design, which is the part worth arguing about.

## Three properties that make a report worth re-running

All three are plumbing rather than measurement, and all three are load-bearing:

1. **Every run is appended, never overwritten.** `bench/results/history.jsonl` is
   committed, so a regression shows up as a delta rather than as a number nobody
   remembers the old value of.
2. **Every run records what produced it** — tool sha, dirty flag, corpus sha,
   host, CPU count, date. A number without provenance cannot be argued with later.
3. **The report is generated, never edited.** Hand-maintained tables drift from
   the code that produced them within a week.

Rule 3 binds this document too. **No results are reproduced here.** They live in
`bench/results/reports/<corpus>/`, regenerated from the committed run files on
every run.

## Running it

```bash
cd bench
uv venv --python 3.12 && uv pip install -e .
cargo install hyperfine          # or: sudo dnf install hyperfine

# ground truth, once per corpus
uv run python -m bench.queryset <corpus-path> --out querysets/<name>.json

# quality: every configuration in adapters.toml, every corpus in corpora.toml
uv run python -m bench.runner --corpus django --index -k 10
uv run python -m bench.report --corpus django

# latency
uv run python -m bench.perf --corpus django --runs 10
```

`--limit N` runs only the first N queries, for smoke-testing a new adapter
without paying for the full sweep.

## Output

One markdown file per configuration plus one summary, per corpus:

```
bench/results/reports/<corpus>/<configuration>.md
bench/results/reports/<corpus>/summary.md
```

The summary carries the cross-tool significance table, the observed-mode table,
the cost table, and each adapter's declared asymmetries — which are stated and
never corrected for. Silently normalising away "zg indexes every file type,
code-explorer indexes Python only" would hide a real difference in what the two
tools are for.

## CI

Split by cost, because these are different questions on different clocks:

- **Per PR** — quality only, on a small fixture corpus, one configuration. Fails
  the build on a recall regression beyond the noise floor. Must finish in minutes.
- **Nightly** — every configuration on the full corpora, plus `hyperfine`.
  Appends to `history.jsonl` and commits the regenerated reports.

A grep enforcing that nothing under `bench/` imports `code_explorer` belongs in
the per-PR job: it is the one property that makes the rest of it credible.

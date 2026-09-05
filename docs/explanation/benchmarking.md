# Benchmarking: measuring whether the answer is right

`perfo/` holds twenty-odd benchmark scripts and every one of them measures
*mechanics* — ingest speed, batch size, index size, fan-out. Not one measures
whether what comes back is **correct**. That is the only number the product
goal cares about, and every performance argument this project has had was
settled without it.

This document describes the evaluation harness in `perfo/eval/`, which exists
to produce that number.

## Ground truth without hand-labeling

The obvious approach — write fifty queries and mark the right answers by hand —
is slow, does not move to a new repository, and is biased: you write queries for
code you already know the index handles well.

**Git history labels itself.** A merged commit is a free example: its subject
line is the question a developer would have asked, and the functions it touched
are the answer set. `build_queryset.py` mines thousands of these per repository
with no manual work.

Selection is deliberately narrow — a commit qualifies only if it touches 2–8
distinct Python functions across at least two files. Single-function commits are
findable by grep and prove nothing; fifty-function refactors have no coherent
answer. What remains is exactly the case the product claims to serve: evidence
spans files, and the entry point is not known in advance.

Subject lines are used nearly verbatim. Conventional-commit prefixes (`fix:`,
`[core]`), issue refs (`(#1234)`) and Django's `Fixed #37293 --` lead are
stripped because they are vocabulary of the *process*, not the code. Nothing
else is cleaned: an agent's guess is messy prose too, and polishing queries into
something BM25 likes would be marking our own homework.

## The tiers

Each tier gates the next. Running them out of order wastes effort measuring
quality on a corpus that cannot be indexed, or tuning an embedding model whose
recall nobody has priced.

### T0 — scale gate (`t0_scale.py`)

Does the indexer survive a large corpus? Not a score, a gate. Measured through
the **real CLI**, because an agent pays process startup, index open and
rendering too, and a library-level harness hides exactly those costs.

Reference numbers (SQLite backend, 16 CPUs):

| corpus | `.py` files | cold build | peak RSS | index | search | re-index 1 file |
|---|---:|---:|---:|---:|---:|---:|
| gemseo | 2,312 | 5.6s | 0.31 GB | 47 MB | 0–2 ms | 0.5s |
| django | 2,930 | 15.4s | 0.51 GB | 107 MB | 0–2 ms | 0.5s |
| home-assistant | 18,631 | 80.8s | 1.70 GB | 524 MB | 6–59 ms | 1.0s |

8× the files costs 14× the build and 5.5× the memory. The column that matters
for an agent is the last one: after the first build, ~1s per invocation on an
18k-file repository, of which ~0.45s is Python interpreter startup.

Open question this raised: search latency grows 30× (1–2 ms → 6–59 ms) while
the corpus grows 6×. Not blocking at 59 ms, not yet explained.

### T1 — seed accuracy (`t1_seed_accuracy.py`)

Step 1 of the retrieval model is "the LLM guesses a plausible name, BM25 finds
it". T1 measures whether that works, on queries nobody wrote to flatter it.

Metric is recall@k over symbols. **Recall@1 matters most**: the context bundle
is seeded from the top hit alone, so a correct answer at rank 4 still bundles
the wrong neighbourhood. MRR is reported alongside because recall@5 cannot
distinguish rank 2 from rank 9.

### T2 — bundle recall

Given the seed, does expansion pull in the *rest* of the commit's symbols?
Reported as recall **and tokens spent**, so the headline is recall per 1k
tokens. This is the number that justifies the depth-3 collect-then-rank design.

### T3 — beating the grep loop

The baseline is not another tool, it is what an agent does today: ripgrep the
query terms, open the top N files. Same recall metric, same token accounting.
Without T3 the claim "replaces a grep loop" is unfalsifiable.

### T4 — embedding choice

`potion-retrieval-32m` (Model2Vec — a static token→vector lookup table, no
transformer forward pass) against a contextual model. Deliberately last: a
static embedding has no context, so `dimension` gets the same vector in "output
dimension" and "design space dimension". "Faster" is only interesting once T1
can price what it costs in recall.

## Comparing against other tools

The harness is tool-agnostic by design, so the same query sets can score
`zvec-grep` (`zg`) or plain ripgrep.

One asymmetry has to be stated up front, because it decides what a comparison
can mean. `zg` returns **passages ranked by relevance**; this project returns
**a seed plus its call graph**. On T1 (find the right code) that is a fair
fight. On T2 it is not like-for-like — graph expansion is the thing we do that
they do not, so T2's honest baseline is ripgrep, not `zg`.

A second asymmetry is granularity: T1 scores symbols, while a passage-based
tool returns file+line spans. Where the other tool cannot reliably name the
enclosing function, score **both** at file level. Scoring ourselves at symbol
level and the competitor at file level would not be a measurement.

## `--json`: why the CLI grew an output mode

`search --json` emits hits and the context bundle as a JSON document on stdout,
with every human-facing line (progress, timings, the ingest summary) redirected
to stderr.

It exists because the rendered table **truncates long names with an ellipsis**,
so benchmark code cannot parse results back reliably — and neither can an agent
consuming this as a tool. The redirect is applied to the shared module-level
`console` rather than a local one, because the ingest helpers print through it
too and would otherwise corrupt the document.

## Running it

```bash
# One tier, one corpus.
uv run --python 3.12 --extra dev python perfo/eval/t0_scale.py .benchmarks/django

# Build a query set from history (needs a non-shallow clone).
uv run --python 3.12 --extra dev python perfo/eval/build_queryset.py \
    .benchmarks/django --out perfo/eval/queryset-django.json --limit 150

# Everything, appending to history and regenerating the report.
uv run --python 3.12 --extra dev python perfo/eval/run_report.py
```

Corpora live in `.benchmarks/`, which is gitignored. They need real history for
`build_queryset.py`, so clone without `--depth 1` (or `git fetch --deepen`).

## The report

`run_report.py` appends one record per run to `perfo/eval/results/history.jsonl`
and regenerates `results/report.md` from it. Three properties make a benchmark
worth re-running, and all three are plumbing rather than measurement:

1. **Runs are appended, never overwritten.** The history file is committed, so a
   regression shows as a delta against the previous run rather than a number
   whose old value nobody remembers.
2. **Every run records its provenance** — commit sha, dirty flag, host, CPU
   count, date. A number without provenance cannot be argued with later.
3. **The report is generated, never edited.** Hand-maintained tables drift from
   the code that produced them.

Changes under 5% are suppressed as noise; wall-clock on a laptop is not tighter
than that.

## CI

T0 needs ~2 GB of checkouts and 100s across three corpora, so it cannot run per
PR. The split:

- **Per PR:** T1 only, against a small committed query-set fixture and a small
  corpus. Seconds, no clones — and it is the tier that catches ranking
  regressions. The `demote_tests`-after-truncation bug would have been caught
  here.
- **Nightly or on demand:** T0 plus full T1, corpora restored from cache,
  results appended and the report regenerated.
- **Gate on deltas, not absolutes.** Wall-clock on a shared runner is noise;
  "recall@1 fell 8% against the last recorded run" is signal.

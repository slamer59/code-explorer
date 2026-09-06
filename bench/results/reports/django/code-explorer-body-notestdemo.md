# code-explorer-body-notestdemo on django

Generated 2026-09-06T13:29:16+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `1df789e6` (dirty), corpus at `b3f4d83a`.


## Retrieval quality (file level)

`delivered` is everything one call puts in front of the model, and is the number that matters. `seed` (what search ranked) and `bundle` (what expansion added) are its two halves, shown because the split says *where* a tool wins or loses -- not because either half is what a caller receives.


| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| delivered | 0.328 | 0.658 | 0.692 | 0.792 | 0.665 |
| seed | 0.328 | 0.645 | 0.659 | 0.792 | 0.646 |
| bundle | 0.328 | 0.454 | 0.454 | 0.747 | 0.512 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 150 | 0 | 474 ms | 1507 | 0.459 |

# code-explorer-body-d10 on django

Generated 2026-09-06T13:22:17+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `1df789e6` (dirty), corpus at `b3f4d83a`.


## Retrieval quality (file level)

`delivered` is everything one call puts in front of the model, and is the number that matters. `seed` (what search ranked) and `bundle` (what expansion added) are its two halves, shown because the split says *where* a tool wins or loses -- not because either half is what a caller receives.


| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| delivered | 0.232 | 0.445 | 0.542 | 0.615 | 0.468 |
| seed | 0.232 | 0.425 | 0.440 | 0.614 | 0.424 |
| bundle | 0.232 | 0.379 | 0.379 | 0.540 | 0.403 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 150 | 0 | 473 ms | 2310 | 0.234 |

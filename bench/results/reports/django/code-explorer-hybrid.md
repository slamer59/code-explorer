# code-explorer-hybrid on django

Generated 2026-09-06T11:19:35+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `6f9f364c` (dirty), corpus at `b3f4d83a`.


## Retrieval quality (file level)

`delivered` is everything one call puts in front of the model, and is the number that matters. `seed` (what search ranked) and `bundle` (what expansion added) are its two halves, shown because the split says *where* a tool wins or loses -- not because either half is what a caller receives.


| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| delivered | 0.196 | 0.480 | 0.592 | 0.592 | 0.482 |
| seed | 0.196 | 0.463 | 0.533 | 0.592 | 0.455 |
| bundle | 0.196 | 0.332 | 0.336 | 0.472 | 0.353 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 150 | 0 | 718 ms | 1727 | 0.343 |

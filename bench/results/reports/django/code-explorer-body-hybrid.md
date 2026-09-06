# code-explorer-body-hybrid on django

Generated 2026-09-06T12:05:11+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `d9707b3c` (dirty), corpus at `b3f4d83a`.


## Retrieval quality (file level)

`delivered` is everything one call puts in front of the model, and is the number that matters. `seed` (what search ranked) and `bundle` (what expansion added) are its two halves, shown because the split says *where* a tool wins or loses -- not because either half is what a caller receives.


| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| delivered | 0.252 | 0.536 | 0.631 | 0.675 | 0.542 |
| seed | 0.252 | 0.522 | 0.575 | 0.675 | 0.518 |
| bundle | 0.252 | 0.391 | 0.394 | 0.580 | 0.422 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 150 | 0 | 727 ms | 2201 | 0.287 |

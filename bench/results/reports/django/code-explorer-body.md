# code-explorer-body on django

Generated 2026-09-06T11:54:32+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `e334a91a` (dirty), corpus at `b3f4d83a`.


## Retrieval quality (file level)

`delivered` is everything one call puts in front of the model, and is the number that matters. `seed` (what search ranked) and `bundle` (what expansion added) are its two halves, shown because the split says *where* a tool wins or loses -- not because either half is what a caller receives.


| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| delivered | 0.235 | 0.491 | 0.586 | 0.630 | 0.499 |
| seed | 0.235 | 0.471 | 0.505 | 0.629 | 0.464 |
| bundle | 0.235 | 0.382 | 0.382 | 0.547 | 0.407 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 150 | 0 | 471 ms | 2300 | 0.255 |

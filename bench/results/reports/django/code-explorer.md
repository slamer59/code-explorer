# code-explorer on django

Generated 2026-09-06T11:11:39+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `4e12dfa2` (dirty), corpus at `b3f4d83a`.


## Retrieval quality (file level)

`delivered` is everything one call puts in front of the model, and is the number that matters. `seed` (what search ranked) and `bundle` (what expansion added) are its two halves, shown because the split says *where* a tool wins or loses -- not because either half is what a caller receives.


| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| delivered | 0.153 | 0.382 | 0.518 | 0.501 | 0.405 |
| seed | 0.153 | 0.375 | 0.458 | 0.498 | 0.380 |
| bundle | 0.153 | 0.278 | 0.282 | 0.387 | 0.288 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 150 | 0 | 461 ms | 1840 | 0.282 |

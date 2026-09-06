# code-explorer-body-potion-d10 on django

Generated 2026-09-06T13:26:02+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `1df789e6` (dirty), corpus at `b3f4d83a`.


## Retrieval quality (file level)

`delivered` is everything one call puts in front of the model, and is the number that matters. `seed` (what search ranked) and `bundle` (what expansion added) are its two halves, shown because the split says *where* a tool wins or loses -- not because either half is what a caller receives.


| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| delivered | 0.194 | 0.426 | 0.532 | 0.570 | 0.445 |
| seed | 0.194 | 0.412 | 0.461 | 0.569 | 0.415 |
| bundle | 0.194 | 0.337 | 0.342 | 0.470 | 0.353 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 150 | 0 | 1192 ms | 2238 | 0.238 |

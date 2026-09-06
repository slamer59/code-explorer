# code-explorer-body on home-assistant

Generated 2026-09-06T13:52:48+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `a0d3b948` (dirty), corpus at `932838840b3`.


## Retrieval quality (file level)

`delivered` is everything one call puts in front of the model, and is the number that matters. `seed` (what search ranked) and `bundle` (what expansion added) are its two halves, shown because the split says *where* a tool wins or loses -- not because either half is what a caller receives.


| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| delivered | 0.266 | 0.427 | 0.470 | 0.675 | 0.466 |
| seed | 0.266 | 0.423 | 0.460 | 0.675 | 0.462 |
| bundle | 0.266 | 0.285 | 0.288 | 0.584 | 0.350 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 200 | 0 | 1083 ms | 1426 | 0.329 |

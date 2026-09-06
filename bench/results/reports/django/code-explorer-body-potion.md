# code-explorer-body-potion on django

Generated 2026-09-06T13:02:05+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `d98d1d8d` (dirty), corpus at `b3f4d83a`.


## Retrieval quality (file level)

`delivered` is everything one call puts in front of the model, and is the number that matters. `seed` (what search ranked) and `bundle` (what expansion added) are its two halves, shown because the split says *where* a tool wins or loses -- not because either half is what a caller receives.


| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| delivered | 0.203 | 0.446 | 0.578 | 0.578 | 0.469 |
| seed | 0.203 | 0.436 | 0.499 | 0.577 | 0.436 |
| bundle | 0.203 | 0.361 | 0.364 | 0.485 | 0.374 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 150 | 0 | 1191 ms | 2234 | 0.259 |

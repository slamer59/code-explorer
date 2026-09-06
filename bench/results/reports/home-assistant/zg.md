# zg on home-assistant

Generated 2026-09-06T14:13:37+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `a0d3b948` (dirty), corpus at `932838840b3`.


## Retrieval quality (file level)

`delivered` is everything one call puts in front of the model, and is the number that matters. `seed` (what search ranked) and `bundle` (what expansion added) are its two halves, shown because the split says *where* a tool wins or loses -- not because either half is what a caller receives.
This tool has no expansion step, so `bundle` repeats `seed` -- that is the correct answer for it, not a missing measurement.

| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| delivered | 0.176 | 0.433 | 0.527 | 0.500 | 0.434 |
| seed | 0.176 | 0.433 | 0.527 | 0.500 | 0.434 |
| bundle | 0.176 | 0.433 | 0.527 | 0.500 | 0.434 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 200 | 0 | 5838 ms | 387 | 1.364 |

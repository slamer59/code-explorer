# ripwire on home-assistant

Generated 2026-09-08T16:48:13+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `456c68da` (dirty), corpus at `932838840b3`.


## Retrieval quality (file level)

`delivered` is everything one call puts in front of the model, and is the number that matters. `seed` (what search ranked) and `bundle` (what expansion added) are its two halves, shown because the split says *where* a tool wins or loses -- not because either half is what a caller receives.
This tool has no expansion step, so `bundle` repeats `seed` -- that is the correct answer for it, not a missing measurement.

| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| delivered | 0.193 | 0.367 | 0.403 | 0.558 | 0.379 |
| seed | 0.193 | 0.367 | 0.403 | 0.558 | 0.379 |
| bundle | 0.193 | 0.367 | 0.403 | 0.558 | 0.379 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 200 | 0 | 3941 ms | 3427 | 0.118 |

# ripwire on django

Generated 2026-09-08T16:34:53+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `1a7e98ae` (dirty), corpus at `b3f4d83a`.


## Retrieval quality (file level)

`delivered` is everything one call puts in front of the model, and is the number that matters. `seed` (what search ranked) and `bundle` (what expansion added) are its two halves, shown because the split says *where* a tool wins or loses -- not because either half is what a caller receives.
This tool has no expansion step, so `bundle` repeats `seed` -- that is the correct answer for it, not a missing measurement.

| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| delivered | 0.224 | 0.375 | 0.424 | 0.610 | 0.408 |
| seed | 0.224 | 0.375 | 0.424 | 0.610 | 0.408 |
| bundle | 0.224 | 0.375 | 0.424 | 0.610 | 0.408 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 150 | 0 | 578 ms | 3294 | 0.129 |

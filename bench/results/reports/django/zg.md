# zg on django

Generated 2026-09-06T10:58:44+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `13f0bbf9` (dirty), corpus at `b3f4d83a`.


## Retrieval quality (file level)

`seed` is what search returned. `bundle` is what the tool actually puts in front of the model.
This tool has no expansion step, so `bundle` repeats `seed` -- that is the correct answer for it, not a missing measurement.

| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| seed | 0.257 | 0.599 | 0.629 | 0.691 | 0.578 |
| bundle | 0.257 | 0.599 | 0.629 | 0.691 | 0.578 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 150 | 0 | 1170 ms | 344 | 1.827 |

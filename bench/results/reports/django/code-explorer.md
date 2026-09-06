# code-explorer on django

Generated 2026-09-06T10:47:55+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `1d81f6b8` (dirty), corpus at `b3f4d83a`.


## Retrieval quality (file level)

`seed` is what search returned. `bundle` is what the tool actually puts in front of the model.


| run | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| seed | 0.153 | 0.375 | 0.458 | 0.498 | 0.380 |
| bundle | 0.153 | 0.278 | 0.282 | 0.387 | 0.288 |

## Cost

| queries | errors | median latency | mean tokens | recall@10 per 1k tokens |
|---|---|---|---|---|
| 150 | 0 | 454 ms | 1840 | 0.153 |

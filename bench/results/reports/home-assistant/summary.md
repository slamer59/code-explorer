# home-assistant: cross-tool summary

200 queries mined from the corpus's own git history: the commit subject is the query, the files it touched are the relevant documents. Scored at **file level**, the only identifier every code search tool can produce.

Generated 2026-09-06T13:52:48+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `a0d3b948` (dirty), corpus at `932838840b3`.


## `delivered`

```
#    Model               Recall@1      Recall@5  Recall@10    MRR@10      NDCG@10
---  ------------------  ----------  ----------  -----------  --------  ---------
a    code-explorer-body  0.266ᵇ           0.427  0.470        0.675ᵇ        0.466
b    zg                  0.176            0.433  0.527ᵃ       0.500         0.434
```

A superscript marks a win that is statistically significant over the lettered model (paired Fisher randomization, p < 0.05). A bare number is a gap the data does not support.

## `seed`

```
#    Model               Recall@1      Recall@5  Recall@10    MRR@10      NDCG@10
---  ------------------  ----------  ----------  -----------  --------  ---------
a    code-explorer-body  0.266ᵇ           0.423  0.460        0.675ᵇ        0.462
b    zg                  0.176            0.433  0.527ᵃ       0.500         0.434
```

A superscript marks a win that is statistically significant over the lettered model (paired Fisher randomization, p < 0.05). A bare number is a gap the data does not support.

## `bundle`

```
#    Model               Recall@1    Recall@5    Recall@10    MRR@10    NDCG@10
---  ------------------  ----------  ----------  -----------  --------  ---------
a    code-explorer-body  0.266ᵇ      0.285       0.288        0.584ᵇ    0.350
b    zg                  0.176       0.433ᵃ      0.527ᵃ       0.500     0.434ᵃ
```

A superscript marks a win that is statistically significant over the lettered model (paired Fisher randomization, p < 0.05). A bare number is a gap the data does not support.

## Complementarity

Recall says who retrieves more. It cannot say whether two tools retrieve the *same* things -- and that is the difference between a tool being redundant and a tool being worth running alongside another.

| tool | vs | relevant files it alone found | relevant files it found | share unique |
|---|---|---|---|---|
| code-explorer-body | zg | 73 | 211 | 35% |
| zg | code-explorer-body | 97 | 235 | 41% |

A high share-unique against a stronger tool means the two are complementary rather than ranked: the files behind that number are ones the other tool never returned at any rank.

## Cost

Query latency and tokens are paid on every question the agent asks. Index build is paid once per corpus, and is only reported for a run that actually rebuilt -- a tool whose index was reused shows `reused`, never a misleadingly small number.

| tool | errors | median latency | mean tokens | index build |
|---|---|---|---|---|
| code-explorer-body | 0 | 1083 ms | 1426 | 1.5 min |
| zg | 0 | 5838 ms | 387 | reused |
## What actually ran

| tool | observed retrieval mode(s) | vector model | expansion step |
|---|---|---|---|
| code-explorer-body | BM25 | none | yes |
| zg | fts+vector, fts+vector,vector, fts,fts+vector, fts,fts+vector,vector, fts,vector | local/potion-retrieval-32m | no |

Retrieval mode is read back from each tool per query, not assumed: it usually depends on which indexes were built rather than on a documented default. The vector model is recorded because a hybrid tool's quality is a property of its embedding as much as of its retrieval logic -- two tools compared under different models are partly a comparison of the models.

## Asymmetries

Declared by each adapter, stated and not corrected for -- silently normalising them would hide real differences in what each tool is for.

- **code-explorer-body** -- Indexes Python only.
- **code-explorer-body** -- FTS/BM25 over name + signature + docstring + callee names + the source body (capped at 2,000 chars). No vector component.
- **code-explorer-body** -- Returns whole symbols, and has a second expansion step.
- **zg** -- Indexes every file type, so it can reach relevant files code-explorer never sees.
- **zg** -- Hybrid FTS+vector by default. Both tools have full-text search; the difference is whether a vector component is fused, which the observed-mode table above records per run.
- **zg** -- Returns text chunks, not whole symbols -- which is why scoring is at file level.
- **zg** -- Has no expansion step, so its `bundle` row repeats its `seed` row. That is its correct answer, not a missing measurement.


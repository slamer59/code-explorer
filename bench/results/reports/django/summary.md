# django: cross-tool summary

150 queries mined from the corpus's own git history: the commit subject is the query, the files it touched are the relevant documents. Scored at **file level**, the only identifier every code search tool can produce.

Generated 2026-09-06T12:05:11+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `d9707b3c` (dirty), corpus at `b3f4d83a`.


## `delivered`

```
#    Model                      Recall@1    Recall@5    Recall@10    MRR@10    NDCG@10
---  -------------------------  ----------  ----------  -----------  --------  ---------
a    code-explorer              0.153       0.382       0.518        0.501     0.405
b    code-explorer-body         0.235ᵃ      0.491ᵃ      0.586ᵃ       0.630ᵃ    0.499ᵃ
c    code-explorer-body-hybrid  0.252ᵃᵈᵍ    0.536ᵃᵇᵈ    0.631ᵃᵇᵍ     0.675ᵃᵈᵍ  0.542ᵃᵇᵈᵍ
d    code-explorer-hybrid       0.196ᵃ      0.480ᵃ      0.592ᵃ       0.592ᵃ    0.482ᵃ
e    zg                         0.257ᵃᵈᵍ    0.599ᵃᵇᶜᵈᵍ  0.629ᵃᵍ      0.691ᵃᵈᵍ  0.578ᵃᵇᵈᵍ
f    zg-full                    0.257ᵃᵈᵍ    0.599ᵃᵇᶜᵈᵍ  0.629ᵃᵍ      0.691ᵃᵈᵍ  0.578ᵃᵇᵈᵍ
g    zg-symbol                  0.193       0.488ᵃ      0.559        0.577     0.473ᵃ
```

A superscript marks a win that is statistically significant over the lettered model (paired Fisher randomization, p < 0.05). A bare number is a gap the data does not support.

## `seed`

```
#    Model                      Recall@1    Recall@5    Recall@10    MRR@10    NDCG@10
---  -------------------------  ----------  ----------  -----------  --------  ----------
a    code-explorer              0.153       0.375       0.458        0.498     0.380
b    code-explorer-body         0.235ᵃ      0.471ᵃ      0.505        0.629ᵃ    0.464ᵃ
c    code-explorer-body-hybrid  0.252ᵃᵈᵍ    0.522ᵃᵇᵈ    0.575ᵃᵇ      0.675ᵃᵈᵍ  0.518ᵃᵇᵈ
d    code-explorer-hybrid       0.196ᵃ      0.463ᵃ      0.533ᵃ       0.592ᵃ    0.455ᵃ
e    zg                         0.257ᵃᵈᵍ    0.599ᵃᵇᶜᵈᵍ  0.629ᵃᵇᵈᵍ    0.691ᵃᵈᵍ  0.578ᵃᵇᶜᵈᵍ
f    zg-full                    0.257ᵃᵈᵍ    0.599ᵃᵇᶜᵈᵍ  0.629ᵃᵇᵈᵍ    0.691ᵃᵈᵍ  0.578ᵃᵇᶜᵈᵍ
g    zg-symbol                  0.193       0.488ᵃ      0.559ᵃ       0.577ᵃ    0.473ᵃ
```

A superscript marks a win that is statistically significant over the lettered model (paired Fisher randomization, p < 0.05). A bare number is a gap the data does not support.

## `bundle`

```
#    Model                      Recall@1    Recall@5    Recall@10    MRR@10      NDCG@10
---  -------------------------  ----------  ----------  -----------  ----------  ----------
a    code-explorer              0.153       0.278       0.282        0.387       0.288
b    code-explorer-body         0.235ᵃ      0.382ᵃ      0.382ᵃ       0.547ᵃ      0.407ᵃ
c    code-explorer-body-hybrid  0.252ᵃᵈᵍ    0.391ᵃᵈ     0.394ᵃᵈ      0.580ᵃᵈ     0.422ᵃᵈ
d    code-explorer-hybrid       0.196ᵃ      0.332ᵃ      0.336ᵃ       0.472ᵃ      0.353ᵃ
e    zg                         0.257ᵃᵈᵍ    0.599ᵃᵇᶜᵈᵍ  0.629ᵃᵇᶜᵈᵍ   0.691ᵃᵇᶜᵈᵍ  0.578ᵃᵇᶜᵈᵍ
f    zg-full                    0.257ᵃᵈᵍ    0.599ᵃᵇᶜᵈᵍ  0.629ᵃᵇᶜᵈᵍ   0.691ᵃᵇᶜᵈᵍ  0.578ᵃᵇᶜᵈᵍ
g    zg-symbol                  0.193       0.488ᵃᵇᶜᵈ   0.559ᵃᵇᶜᵈ    0.577ᵃᵈ     0.473ᵃᵇᵈ
```

A superscript marks a win that is statistically significant over the lettered model (paired Fisher randomization, p < 0.05). A bare number is a gap the data does not support.

## Complementarity

Recall says who retrieves more. It cannot say whether two tools retrieve the *same* things -- and that is the difference between a tool being redundant and a tool being worth running alongside another.

| tool | vs | relevant files it alone found | relevant files it found | share unique |
|---|---|---|---|---|
| code-explorer | code-explorer-body | 29 | 182 | 16% |
| code-explorer | code-explorer-body-hybrid | 25 | 182 | 14% |
| code-explorer | code-explorer-hybrid | 16 | 182 | 9% |
| code-explorer | zg | 46 | 182 | 25% |
| code-explorer | zg-full | 46 | 182 | 25% |
| code-explorer | zg-symbol | 52 | 182 | 29% |
| code-explorer-body | code-explorer | 51 | 204 | 25% |
| code-explorer-body | code-explorer-body-hybrid | 16 | 204 | 8% |
| code-explorer-body | code-explorer-hybrid | 40 | 204 | 20% |
| code-explorer-body | zg | 50 | 204 | 25% |
| code-explorer-body | zg-full | 50 | 204 | 25% |
| code-explorer-body | zg-symbol | 56 | 204 | 27% |
| code-explorer-body-hybrid | code-explorer | 61 | 218 | 28% |
| code-explorer-body-hybrid | code-explorer-body | 30 | 218 | 14% |
| code-explorer-body-hybrid | code-explorer-hybrid | 34 | 218 | 16% |
| code-explorer-body-hybrid | zg | 52 | 218 | 24% |
| code-explorer-body-hybrid | zg-full | 52 | 218 | 24% |
| code-explorer-body-hybrid | zg-symbol | 61 | 218 | 28% |
| code-explorer-hybrid | code-explorer | 42 | 208 | 20% |
| code-explorer-hybrid | code-explorer-body | 44 | 208 | 21% |
| code-explorer-hybrid | code-explorer-body-hybrid | 24 | 208 | 12% |
| code-explorer-hybrid | zg | 49 | 208 | 24% |
| code-explorer-hybrid | zg-full | 49 | 208 | 24% |
| code-explorer-hybrid | zg-symbol | 59 | 208 | 28% |
| zg | code-explorer | 84 | 220 | 38% |
| zg | code-explorer-body | 66 | 220 | 30% |
| zg | code-explorer-body-hybrid | 54 | 220 | 25% |
| zg | code-explorer-hybrid | 61 | 220 | 28% |
| zg | zg-full | 0 | 220 | 0% |
| zg | zg-symbol | 38 | 220 | 17% |
| zg-full | code-explorer | 84 | 220 | 38% |
| zg-full | code-explorer-body | 66 | 220 | 30% |
| zg-full | code-explorer-body-hybrid | 54 | 220 | 25% |
| zg-full | code-explorer-hybrid | 61 | 220 | 28% |
| zg-full | zg | 0 | 220 | 0% |
| zg-full | zg-symbol | 38 | 220 | 17% |
| zg-symbol | code-explorer | 67 | 197 | 34% |
| zg-symbol | code-explorer-body | 49 | 197 | 25% |
| zg-symbol | code-explorer-body-hybrid | 40 | 197 | 20% |
| zg-symbol | code-explorer-hybrid | 48 | 197 | 24% |
| zg-symbol | zg | 15 | 197 | 8% |
| zg-symbol | zg-full | 15 | 197 | 8% |

A high share-unique against a stronger tool means the two are complementary rather than ranked: the files behind that number are ones the other tool never returned at any rank.

## Cost

| tool | errors | median latency | mean tokens |
|---|---|---|---|
| code-explorer | 0 | 461 ms | 1840 |
| code-explorer-body | 0 | 471 ms | 2300 |
| code-explorer-body-hybrid | 0 | 727 ms | 2201 |
| code-explorer-hybrid | 0 | 718 ms | 1727 |
| zg | 0 | 1171 ms | 344 |
| zg-full | 0 | 1165 ms | 4056 |
| zg-symbol | 0 | 1172 ms | 325 |
## What actually ran

| tool | observed retrieval mode(s) | vector model | expansion step |
|---|---|---|---|
| code-explorer | BM25 | none | yes |
| code-explorer-body | BM25 | none | yes |
| code-explorer-body-hybrid | hybrid BM25+vector | ollama/nomic-embed-text | yes |
| code-explorer-hybrid | hybrid BM25+vector | none | yes |
| zg | fts+vector, fts,fts+vector, fts,fts+vector,vector, fts,vector | none | no |
| zg-full | fts+vector, fts,fts+vector, fts,fts+vector,vector, fts,vector | none | no |
| zg-symbol | fts+vector, fts,fts+vector, fts,fts+vector,vector, fts,vector | none | no |

Retrieval mode is read back from each tool per query, not assumed: it usually depends on which indexes were built rather than on a documented default. The vector model is recorded because a hybrid tool's quality is a property of its embedding as much as of its retrieval logic -- two tools compared under different models are partly a comparison of the models.

## Asymmetries

Declared by each adapter, stated and not corrected for -- silently normalising them would hide real differences in what each tool is for.

- **code-explorer** -- Indexes Python only, so a relevant non-Python file is unreachable for it by construction.
- **code-explorer** -- Full-text search (SQLite FTS5/BM25) with no vector component, because no vector index was built for this configuration.
- **code-explorer** -- Returns whole symbols, and has a second expansion step, so its `bundle` row differs from its `seed` row.
- **code-explorer-body** -- Indexes Python only.
- **code-explorer-body** -- FTS/BM25 over name + signature + docstring + callee names + the source body (capped at 2,000 chars). No vector component.
- **code-explorer-body** -- Returns whole symbols, and has a second expansion step.
- **code-explorer-body-hybrid** -- Indexes Python only.
- **code-explorer-body-hybrid** -- Hybrid: FTS/BM25 fused with a vector index, both built over the source body rather than the skeleton.
- **code-explorer-body-hybrid** -- Returns whole symbols, and has a second expansion step.
- **code-explorer-hybrid** -- Indexes Python only, so a relevant non-Python file is unreachable for it by construction.
- **code-explorer-hybrid** -- Hybrid: FTS/BM25 fused with a vector index (Ollama nomic-embed-text) by reciprocal rank fusion.
- **code-explorer-hybrid** -- Returns whole symbols, and has a second expansion step, so its `bundle` row differs from its `seed` row.
- **zg** -- Indexes every file type, so it can reach relevant files code-explorer never sees.
- **zg** -- Hybrid FTS+vector by default. Both tools have full-text search; the difference is whether a vector component is fused, which the observed-mode table above records per run.
- **zg** -- Returns text chunks, not whole symbols -- which is why scoring is at file level.
- **zg** -- Has no expansion step, so its `bundle` row repeats its `seed` row. That is its correct answer, not a missing measurement.
- **zg-full** -- Indexes every file type, so it can reach relevant files code-explorer never sees.
- **zg-full** -- Hybrid FTS+vector, returning full source previews -- the configuration whose token cost is comparable to an assembled context bundle.
- **zg-full** -- Returns text chunks, not whole symbols -- which is why scoring is at file level.
- **zg-full** -- Has no expansion step, so its `bundle` row repeats its `seed` row.
- **zg-symbol** -- Indexes every file type, so it can reach relevant files code-explorer never sees.
- **zg-symbol** -- Hybrid FTS+vector, biased toward exact indexed symbols (--prefer-symbol) -- the closest match to how code-explorer is meant to be queried.
- **zg-symbol** -- Returns text chunks, not whole symbols -- which is why scoring is at file level.
- **zg-symbol** -- Has no expansion step, so its `bundle` row repeats its `seed` row.


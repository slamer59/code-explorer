# home-assistant: cross-tool summary

200 queries mined from the corpus's own git history: the commit subject is the query, the files it touched are the relevant documents. Scored at **file level**, the only identifier every code search tool can produce.

Generated 2026-09-06T13:52:48+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `a0d3b948` (dirty), corpus at `932838840b3`.


## `delivered`, ground truth = code only

The 195 queries whose answer set contains non-test files (code = « où est-ce implémenté ? »).

```
#    Model               Recall@1    Recall@5    Recall@10    MRR@10    NDCG@10
---  ------------------  ----------  ----------  -----------  --------  ---------
a    code-explorer-body  0.550ᵇᶜ     0.779ᶜ      0.807ᶜ       0.673ᵇᶜ   0.704ᵇᶜ
b    ripwire             0.402ᶜ      0.749ᶜ      0.821ᶜ       0.573ᶜ    0.629ᶜ
c    zg                  0.188       0.463       0.552        0.328     0.374
```

## `delivered`, ground truth = test only

The 191 queries whose answer set contains non-test files (test = « qu'est-ce qui couvre ça ? »).

```
#    Model               Recall@1    Recall@5    Recall@10    MRR@10    NDCG@10
---  ------------------  ----------  ----------  -----------  --------  ---------
a    code-explorer-body  0.010       0.089ᵇ      0.152ᵇ       0.049ᵇ    0.074ᵇ
b    ripwire             0.000       0.000       0.000        0.000     0.000
c    zg                  0.168ᵃᵇ     0.421ᵃᵇ     0.522ᵃᵇ      0.294ᵃᵇ   0.344ᵃᵇ
```

## `delivered`

```
#    Model               Recall@1    Recall@5    Recall@10    MRR@10    NDCG@10
---  ------------------  ----------  ----------  -----------  --------  ---------
a    code-explorer-body  0.266ᵇᶜ     0.427ᵇ      0.470ᵇ       0.675ᵇᶜ   0.466ᵇ
b    ripwire             0.193       0.367       0.403        0.558     0.379
c    zg                  0.176       0.433ᵇ      0.527ᵃᵇ      0.500     0.434ᵇ
```

A superscript marks a win that is statistically significant over the lettered model (paired Fisher randomization, p < 0.05). A bare number is a gap the data does not support.

## `seed`

```
#    Model               Recall@1    Recall@5    Recall@10    MRR@10    NDCG@10
---  ------------------  ----------  ----------  -----------  --------  ---------
a    code-explorer-body  0.266ᵇᶜ     0.423ᵇ      0.460ᵇ       0.675ᵇᶜ   0.462ᵇ
b    ripwire             0.193       0.367       0.403        0.558     0.379
c    zg                  0.176       0.433ᵇ      0.527ᵃᵇ      0.500     0.434ᵇ
```

A superscript marks a win that is statistically significant over the lettered model (paired Fisher randomization, p < 0.05). A bare number is a gap the data does not support.

## `bundle`

```
#    Model               Recall@1    Recall@5    Recall@10    MRR@10    NDCG@10
---  ------------------  ----------  ----------  -----------  --------  ---------
a    code-explorer-body  0.266ᵇᶜ     0.285       0.288        0.584ᶜ    0.350
b    ripwire             0.193       0.367ᵃ      0.403ᵃ       0.558     0.379
c    zg                  0.176       0.433ᵃᵇ     0.527ᵃᵇ      0.500     0.434ᵃᵇ
```

A superscript marks a win that is statistically significant over the lettered model (paired Fisher randomization, p < 0.05). A bare number is a gap the data does not support.

## Complementarity

Recall says who retrieves more. It cannot say whether two tools retrieve the *same* things -- and that is the difference between a tool being redundant and a tool being worth running alongside another.

| tool | vs | relevant files it alone found | relevant files it found | share unique |
|---|---|---|---|---|
| code-explorer-body | ripwire | 48 | 211 | 23% |
| code-explorer-body | zg | 73 | 211 | 35% |
| ripwire | code-explorer-body | 18 | 181 | 10% |
| ripwire | zg | 68 | 181 | 38% |
| zg | code-explorer-body | 97 | 235 | 41% |
| zg | ripwire | 122 | 235 | 52% |

A high share-unique against a stronger tool means the two are complementary rather than ranked: the files behind that number are ones the other tool never returned at any rank.

## Cost

Query latency and tokens are paid on every question the agent asks. Index build is paid once per corpus, and is only reported for a run that actually rebuilt -- a tool whose index was reused shows `reused`, never a misleadingly small number.

| tool | errors | median latency | mean tokens | index build |
|---|---|---|---|---|
| code-explorer-body | 0 | 1083 ms | 1426 | 1.5 min |
| ripwire | 0 | 3941 ms | 3427 | reused |
| zg | 0 | 5838 ms | 387 | reused |
## What actually ran

| tool | observed retrieval mode(s) | vector model | expansion step |
|---|---|---|---|
| code-explorer-body | BM25 | none | yes |
| ripwire | routed: subtoken+body BM25 (--for's default) — no strong name hit, multi-word conceptual query, routed: subtoken+body BM25 — name-exact declined: anchor 'add' is a common name (1404 name-carriers, 8 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'authorize' is a common name (136 name-carriers, 5 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'calendar' is a common name (259 name-carriers, 22 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'charge' is a common name (334 name-carriers, 6 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'config' is a common name (10983 name-carriers, 1025 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'entity' is a common name (13569 name-carriers, 1154 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'expose' is a common name (132 name-carriers, 9 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'knx' is a common name (219 name-carriers, 9 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'motion' is a common name (473 name-carriers, 14 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'power' is a common name (1507 name-carriers, 73 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'remove' is a common name (1403 name-carriers, 28 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'send' is a common name (1008 name-carriers, 19 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'servers' is a common name (51 name-carriers, 4 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'services' is a common name (1249 name-carriers, 717 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'setup' is a common name (11364 name-carriers, 83 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'stop' is a common name (1062 name-carriers, 69 defs); conceptual ranker used, routed: subtoken+body BM25 — name-exact declined: anchor 'type' is a common name (4596 name-carriers, 486 defs); conceptual ranker used | none | no |
| zg | fts+vector, fts+vector,vector, fts,fts+vector, fts,fts+vector,vector, fts,vector | local/potion-retrieval-32m | no |

Retrieval mode is read back from each tool per query, not assumed: it usually depends on which indexes were built rather than on a documented default. The vector model is recorded because a hybrid tool's quality is a property of its embedding as much as of its retrieval logic -- two tools compared under different models are partly a comparison of the models.

## Asymmetries

Declared by each adapter, stated and not corrected for -- silently normalising them would hide real differences in what each tool is for.

- **code-explorer-body** -- Indexes Python only.
- **code-explorer-body** -- FTS/BM25 over name + signature + docstring + callee names + the source body (capped at 2,000 chars). No vector component.
- **code-explorer-body** -- Returns whole symbols, and has a second expansion step.
- **ripwire** -- Indexes every supported language (22+, tree-sitter based), so it can reach relevant non-Python files code-explorer never sees -- same asymmetry as zg.
- **ripwire** -- BM25 over a Personalized-PageRank-ranked symbol graph, name-exact or subtoken+body routed automatically per query; no vector component.
- **ripwire** -- Returns individual symbols (function/class granularity), scored at file level like code-explorer.
- **ripwire** -- --json never serves expanded bodies (bundle is always 'sigs' in that dialect), so it has no second expansion step -- its `bundle` row repeats its `seed` row, like zg.
- **ripwire** -- No explicit result-count flag for --for; it fills its own ~7.5KB signature budget and this adapter truncates client-side to k.
- **ripwire** -- No separate index-build step: each query cold-parses the corpus behind a warm-by-default per-root cache in the OS tmpdir, so the recorded wall_ms is steady-state per-query cost, not a build artifact.
- **zg** -- Indexes every file type, so it can reach relevant files code-explorer never sees.
- **zg** -- Hybrid FTS+vector by default. Both tools have full-text search; the difference is whether a vector component is fused, which the observed-mode table above records per run.
- **zg** -- Returns text chunks, not whole symbols -- which is why scoring is at file level.
- **zg** -- Has no expansion step, so its `bundle` row repeats its `seed` row. That is its correct answer, not a missing measurement.


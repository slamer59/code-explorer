# Gap analysis: what it would take to beat zvec-grep

Measured on django, 150 git-mined queries, file-level scoring. Every number
here comes from `bench/results/`; nothing is estimated.

## The gap is smaller than the headline, and it is all ranking

| | code-explorer-hybrid | zg | significant? |
|---|---|---|---|
| recall@1 | 0.196 | **0.257** | yes, p<0.05 |
| recall@10 | 0.592 | 0.629 | **no** |
| MRR@10 | 0.592 | **0.691** | yes, p<0.05 |
| median latency | **718 ms** | 1,171 ms | — |
| tokens for delivered code | **1,727** | 4,056 (`--preview full`) | — |

There is **no speed gap to close**: code-explorer is already 1.6× faster per
query and 2.3× cheaper in tokens once zg is made to deliver source rather than
paths. The gap is accuracy, and specifically accuracy *at the top of the list* —
recall@10 is already statistically indistinguishable.

That matters because the bundle is seeded from hit #1. A rank-4 answer is a
wrong neighbourhood, so recall@1 is worth more here than to a tool that just
returns a list.

## Two excuses that the data removes

**"zg indexes every file type."** Irrelevant on this corpus. The ground truth is
**100% Python** (204/204 files), so broader coverage buys zg nothing. All 61
relevant files zg finds and code-explorer never returns are `.py`.

This is a property of the *benchmark*, not of reality — the queryset miner
extracts `def`/`class` from diff hunks, so non-Python files can never enter the
answer set. Indexing all file types is still worth doing for real use; it will
not move this score, and the benchmark should stop claiming it as an asymmetry.

**"They are ranked just below the cutoff."** No. Of the 61 misses, **57 (93%)
are in the index** — and their median rank is **179 out of 200**. Raising the
limit from 10 to 50 recovers **3 of them**. These symbols are not narrowly
missed; the scoring function gives them almost no signal at all.

## Root cause: what gets embedded, not which model embeds it

`_derive_search_text` (`graph/ingest.py:98`) builds the text used for *both*
BM25 and the vector index. A representative entry, in full:

```
django/apps/registry.py::clear_cache
clear_cache
clear cache
clear cache
def clear_cache(self):
Clear all internal caches, for methods that alter the app registry.
calls: cache_clear, values, get_models, _expire_cache
```

**Median 177 characters — about 44 tokens.** Qualified name, the name again,
its split words twice, the signature, the first docstring line, and callee
names. **The body is never indexed.** So a prose query is matched against a
skeleton, and any symbol whose relevance lives in what it *does* rather than
what it is *called* scores near zero. That is the rank-179 population.

The decisive evidence that this is about the input and not the model: zg wins
using `potion-retrieval-32m`, a **Model2Vec static vector lookup** — no
transformer forward pass, so a token gets the same vector regardless of
surrounding code. It is the weakest architecture class zg offers. Code-explorer
loses to it while running `nomic-embed-text`, a real transformer with 8,192
tokens of context, because it feeds that transformer 44 tokens of skeleton.

## Does choosing the embedding model matter?

Yes, but it is the **second** lever, not the first.

- **First**: index the body. Doubling from 44 tokens of skeleton to real code is
  the change that can move rank 179, and it costs no model work.
- **Second**: the model. `nomic-embed-text` is general-purpose prose. zg's docs
  recommend `jina-embeddings-v2-base-code` for retrieval quality — code-trained,
  768 dims, 8,192 tokens. Code-explorer hard-codes whatever Ollama serves;
  making it selectable is cheap and makes the choice measurable.
- Note the ordering matters: a longer-context code model is wasted on a 44-token
  input. Swapping the model first would measure almost nothing.

## Outcome of priority 1 (implemented and measured)

Indexing the body was implemented as `settings.search_text_mode` — a setting,
not a replacement; `skeleton` remains available and the body is *appended*, so
the weighted-name prefix that keeps identifier matches above prose matches
survives intact.

Delivered run, django, 150 queries. Superscripts mark significance at p<0.05:

```
#    Model                      Recall@1    Recall@5    Recall@10    MRR@10    NDCG@10
a    code-explorer              0.153       0.382       0.518        0.501     0.405
b    code-explorer-hybrid       0.196ᵃ      0.480ᵃ      0.592ᵃ       0.592ᵃ    0.482ᵃ
c    code-explorer-body         0.235ᵃ      0.491ᵃ      0.586ᵃ       0.630ᵃ    0.499ᵃ
d    code-explorer-body-hybrid  0.252ᵃᵇ     0.536ᵃᵇᶜ    0.631ᵃᶜ      0.675ᵃᵇ   0.542ᵃᵇᶜ
e    zg                         0.257ᵃᵇ     0.599ᵃᵇᶜᵈ   0.629ᵃ       0.691ᵃᵇ   0.578ᵃᵇᶜ
```

The prediction held. Two results worth separating:

**Body-mode BM25 (c) beats skeleton-mode hybrid (b)** on recall@1, MRR and
NDCG — no embedding at all, +10 ms per query (461 → 471 ms). Indexing the body
did more than adding a transformer vector channel over a 44-token skeleton did.

**Body-mode hybrid (d) reaches parity with zvec-grep.** It edges ahead on
recall@10 (0.631 vs 0.629), and zg's leads on recall@1, recall@10, MRR and NDCG
are all **no longer statistically significant** — row `e` carries no `ᵈ` on any
of them. zg keeps exactly one significant win, **recall@5**. Code-explorer does
it at 727 ms against zg's 1,171 ms.

`body` is now the default. `skeleton` is kept rather than deprecated: it builds
and embeds a ~44-token field instead of a ~500-token one, which matters for
index size and for embedding cost on a large corpus.

## Remaining priorities

1. ~~**Index the body.**~~ Done, and it worked — see above. The *chunked* half
   is not done: a body over `search_text_body_chars` is truncated at a line
   boundary rather than split into several vectors, so a long function is still
   one diluted vector. That is the natural next increment, and recall@5 — zg's
   last significant win — is where it would show up.
2. **Make the embedding model configurable** and benchmark two or three,
   including a code-trained one. Only meaningful after (1).
3. **Re-tune fusion.** RRF at k=60 with equal weights was never fitted. Cheap to
   sweep once the channels are worth fusing.
4. **Index all file types.** Real-world coverage. Will not move this benchmark,
   and the report should say so rather than claim it as a handicap.

## What this analysis does not cover

One corpus, one language, file-level scoring, and single-call comparison. The
axis that would most favour code-explorer — one call against a multi-call grep
loop — is not measured yet, and needs a follow-up policy for the multi-call tool
before it can be.

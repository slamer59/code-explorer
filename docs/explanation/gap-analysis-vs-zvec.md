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

## Outcome of priority 2 (implemented and measured — it does not pay)

`settings.embedding_provider` now selects `ollama` (a transformer forward pass
per text, over HTTP) or `model2vec` (a static token→vector lookup, in-process),
with `--embedding PROVIDER/MODEL` on the CLI. The hypothesis was that zvec-grep's
indexing speed *is* this choice, and that adopting it would close the last gap.

The first half was right. Measured on 500 real body-mode `search_text` rows:

| provider | throughput | dims |
|---|---|---|
| `ollama/nomic-embed-text` | 76 texts/s | 768 |
| `model2vec/potion-retrieval-32m` | **24,211 texts/s** | 512 |

**319×**, and it holds end to end: the django vector build drops from 8.43 min to
0.62 min. zvec-grep's 24-second cold build is this, not a faster pipeline.

The second half was wrong, and the benchmark is why we know:

| configuration | build | query | recall@10 | MRR@10 |
|---|---|---|---|---|
| ollama transformer | 8.43 min | 727 ms | **0.631** | **0.675** |
| model2vec static | 0.62 min | 1,191 ms | 0.578 | 0.578 |
| **no vector index at all** | 0.29 min | **471 ms** | 0.586 | 0.630 |

The static model loses to the transformer on every metric at p<0.05 — and loses
to **using no vector index at all**, which is also cheaper and faster. So it is
not a speed-for-quality trade; it is worse on both axes that matter to a user.
Query latency is *higher* because each process pays ~0.5 s loading the static
model, a cost that amortises over a bulk index build and never over one query.

Why zvec-grep gets away with it: it embeds **code chunks**, we embed a ~500-token
synthetic `search_text`. Static embeddings have no context, so they depend
entirely on the input carrying the signal — and ours does not carry it the same
way. That is the same lesson as priority 1, pointing the other direction.

`ollama` therefore stays the default. `model2vec` stays available because the
conclusion is corpus- and input-specific, and the harness can re-answer it.

## Outcome of priority 3 (fusion depth) — and the limit of the benchmark

Offline, RRF kept improving to a fetch depth of ~100 while BM25 alone saturated
at ~40, suggesting `_RERANK_OVERFETCH = 4` was starving fusion. `--overfetch`
made it configurable and the prediction was tested end to end.

**It failed.** Depth 40 → 100 made retrieval *worse* in both channels: BM25
0.586 → 0.542, static hybrid 0.578 → 0.532. The offline model omitted one
stage, and that stage turned out to be the whole story.

`demote_tests` multiplies a test file's score by 0.4 before truncating to
`--limit`. On this benchmark:

- **56%** of ground-truth file slots are test files.
- **97%** of queries have a test file among their correct answers.

Because a commit that changes behaviour changes its tests too. So demotion
suppresses the majority of the right answers, and fetching deeper amplified it:
more non-test candidates got promoted over relevant tests.

Disabling it (`--test-demotion 1.0`) is dramatic — BM25 alone, no vectors:

```
#  Model                          R@1      R@5      R@10     MRR@10
a  code-explorer-body             0.235    0.491    0.586    0.630
b  code-explorer-body-notestdemo  0.328ᵃᶜᵈ 0.658ᵃᶜᵈ 0.692ᵃᶜᵈ 0.792ᵃᶜᵈ
c  code-explorer-body-hybrid      0.252    0.536ᵃ   0.631ᵃ   0.675
d  zg                             0.257    0.597ᵃ   0.629    0.691
```

That beats zvec-grep significantly on every metric, at 471 ms and a 0.29-minute
build. **The default was not changed.**

This is where the benchmark stops being able to answer the question. Its ground
truth *defines* test files as correct, so measuring test demotion against it is
circular — the metric was built from the same assumption the decision is about.
Demotion exists for a real failure (on gemseo, three `test_get_function_dimension*`
variants outranked the function they test, and the bundle was seeded from a
test), and which behaviour is right depends on whether the user asked "where is
X implemented" or "what covers X". Nothing in the pipeline knows that.

So `test_demotion_factor` is a setting with the trade documented, and this
number is recorded as a benchmark artifact rather than banked as a win. Deciding
it properly needs ground truth that separates "the code that changed" from "the
tests that changed with it" — which the miner could label, since it already
knows which files a commit touched.

## Où passe l'avantage restant de zvec-grep

Mesuré par `bench/analysis/gap_decomposition.py`, sur les deux corpus :

| corpus | fichiers pertinents que zg place devant nous | dont tests rétrogradés | dont code applicatif |
|---|---|---|---|
| django (top-5) | 75 | **68 (91 %)** | 7 |
| home-assistant (top-10) | 98 | **91 (93 %)** | 7 |

Sur 150 et 200 requêtes respectivement, l'écart de récupération sur le *code
applicatif* est de sept fichiers. Tout le reste est constitué de fichiers de
tests que `demote_tests` fait volontairement descendre.

Le constat est donc indépendant du corpus, et `ground_truth_composition.py`
montre pourquoi : la vérité terrain est à 56 % (django) et 50 %
(home-assistant) composée de fichiers de tests, présents dans 97 % et 96 % des
requêtes. Un commit qui change un comportement change ses tests.

Ce n'est pas un défaut de récupération, c'est un désaccord sur la question
posée — et la vérité terrain minée depuis les commits répond toujours « les
deux », donc elle ne peut pas trancher.

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

"""Centralized configuration via pydantic-settings.

Before this module, the values below were hardcoded module-level constants
scattered across embeddings.py, graph/backends/lattice_backend.py, and
graph/graph.py -- no single source of truth, no way to override any of them
without editing source. This module collects them into one Settings class,
overridable via CODE_EXPLORER_-prefixed env vars (or a
.code-explorer/.env file in the cwd) without changing any default behavior.

See docs/explanation/configuration.md for what each setting is for and when
you'd actually want to change it.
"""

import os
from typing import List, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CODE_EXPLORER_",
        env_file=".code-explorer/.env",
    )

    # Embedding generation (see embeddings.py).
    #
    # Two providers, because they are different *kinds* of computation and the
    # choice dominates index build time:
    #
    #   "ollama"    -- a transformer forward pass per text, over HTTP.
    #   "model2vec" -- a static vector lookup: token -> vector, mean-pooled.
    #                  No forward pass, no server, no context. In-process.
    #
    # Measured on 500 real body-mode search_text rows (median 503 chars):
    #   ollama/nomic-embed-text        76 texts/s
    #   model2vec/potion-retrieval-32m 24,211 texts/s   (+11.7s one-time load)
    # -- 319x, which is the difference between an 8-minute vector build on
    # django and a few seconds of it. zvec-grep's speed advantage at indexing
    # is this choice, not a faster pipeline.
    #
    # Static embeddings have no context: a token gets the same vector wherever
    # it appears. That was measured, and it costs more than it saves, which is
    # why "ollama" remains the default despite being 300x slower to index.
    # django, 150 git-mined queries, body-mode search_text:
    #
    #   provider                  build      query    R@10    MRR@10
    #   ollama/nomic-embed-text   8.43 min   727 ms   0.631   0.675
    #   model2vec/potion-32m      0.62 min  1191 ms   0.578   0.578
    #   (no vector index at all)  0.29 min   471 ms   0.586   0.630
    #
    # The static model loses to the transformer on every metric at p<0.05 --
    # and loses to using no vector index at all, so it is not a speed/quality
    # trade, it is worse on both axes that matter here. Query latency is
    # *higher* because each process pays ~0.5s loading the static model, which
    # amortises over a bulk index build and never over a single query.
    #
    # zvec-grep does well with the same model class because it embeds code
    # chunks; a ~500-token search_text is a different input. Kept configurable
    # because that conclusion is corpus- and input-specific, and re-measurable.
    embedding_provider: Literal["ollama", "model2vec"] = "ollama"
    ollama_endpoint: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"
    # Must match the provider's model. Changing either invalidates an existing
    # vector index, which is dimensioned at build time -- rebuild with
    # --semantic --reindex after a switch.
    embedding_dimensions: int = 768
    # Hugging Face id used when embedding_provider is "model2vec". Kept
    # separate from embedding_model so switching providers back and forth does
    # not lose either setting.
    model2vec_model: str = "minishlab/potion-retrieval-32m"
    model2vec_dimensions: int = 512
    embedding_timeout: float = 30.0
    embed_batch_size: int = 50

    # What goes into search_text, the single field both BM25 and the vector
    # index are built from (see graph/ingest.py's _derive_search_text).
    #
    # "skeleton" is the original: qualified name, the name and its split words,
    # the signature, the first docstring line, and callee names -- a median of
    # ~44 tokens, with the body never indexed. Measured against zvec-grep on
    # django (bench/results/reports/django/), that is where the losses come
    # from: 93% of the relevant symbols code-explorer failed to return were in
    # the index, at median rank 179 of 200. A prose query cannot match a
    # symbol whose relevance lives in what it does rather than what it is
    # called, because what it does is not indexed.
    #
    # "body" appends the source, capped at search_text_body_chars, and is the
    # default because it was measured to win, not because it sounds better.
    # On django (150 git-mined queries, bench/results/reports/django/):
    #
    #   configuration              R@1    R@5    R@10   MRR@10  NDCG@10
    #   skeleton, BM25             0.153  0.382  0.518  0.501   0.405
    #   skeleton, hybrid           0.196  0.480  0.592  0.592   0.482
    #   body, BM25                 0.235  0.491  0.586  0.630   0.499
    #   body, hybrid               0.252  0.536  0.631  0.675   0.542
    #   zvec-grep (for reference)  0.257  0.599  0.629  0.691   0.578
    #
    # Body-mode BM25 alone beats skeleton-mode *hybrid* on R@1, MRR and NDCG
    # for +10ms and no embedding; body-mode hybrid reaches parity with
    # zvec-grep everywhere except recall@5, at 1.6x its speed.
    #
    # "skeleton" is kept, not deprecated: it builds and embeds a ~44-token
    # field instead of a ~500-token one, which matters for index size and for
    # embedding cost on a large corpus.
    search_text_mode: Literal["skeleton", "body"] = "body"
    # Cap on appended body text. A long function embedded whole becomes one
    # diluted vector, and an uncapped field also inflates the index; this
    # bounds both. Chunking long bodies into several vectors is the better
    # answer and is not implemented yet.
    search_text_body_chars: int = 2000

    # Results pulled from each retrieval channel before re-ranking
    # (demote_tests) and truncating to the user's --limit. It was 4, chosen to
    # cover a function with four near-identical tests out-scoring it; that is
    # a re-ranking argument, and it silently also set the *fusion* depth.
    #
    # Fusion wants more. Measured offline on django (one protocol, only depth
    # varying; not comparable to end-to-end numbers):
    #
    #   fetch depth   BM25    vectors   RRF fused
    #            10   0.622   0.493     0.682
    #            40   0.696   0.573     0.707   <- overfetch 4 at --limit 10
    #           100   0.699   0.575     0.726
    #           300   0.699   0.578     0.721
    #
    # BM25 saturates around 100; fusion keeps improving to it, because the
    # extra depth only pays when there is a second channel to fuse against.
    rerank_overfetch: int = 4

    # Multiplier applied to a test file's score before truncating to --limit
    # (see hybrid_search.demote_tests). 1.0 disables the demotion.
    #
    # It exists for a real failure: on gemseo, `search "function dimension"`
    # put three test_get_function_dimension* variants above the function they
    # test, so the context bundle was seeded from the test.
    #
    # But it is a genuine trade, not a free fix. On the django benchmark 56%
    # of ground-truth file slots are test files and 97% of queries have a test
    # among their correct answers -- because a commit that changes behaviour
    # changes its tests too. There, demotion suppresses the majority of the
    # right answers, and it is why fetching deeper made retrieval *worse*
    # rather than better: more non-test candidates got promoted over relevant
    # tests.
    #
    # Which of those two situations a user is in depends on the question they
    # asked ("where is X implemented" vs "what covers X"), and nothing here
    # knows that. Hence a setting rather than a chosen answer -- and see
    # docs/explanation/gap-analysis-vs-zvec.md before tuning it to a benchmark
    # whose ground truth is mined from commits.
    test_demotion_factor: float = 0.4

    # LatticeDB write-transaction chunking (see graph/backends/lattice_backend.py).
    # Operations accumulated per streaming ingest batch before the writer
    # commits. Measured, not guessed: perfo/benchmark_batch_size_sweep.py on
    # the 2,103-file gemseo corpus (2 runs per point, agreeing to within 0.3s)
    # traces a shallow bowl with its floor at 200-350 --
    #   target    50    100    200    350    500  1,000  2,000  4,000  8,000
    #   commit  12.3s  11.2s  10.7s  11.1s  11.2s  12.2s  12.7s  13.7s  13.3s
    #   wall    25.6s  24.4s  23.9s  24.1s  24.4s  25.2s  25.8s  26.9s  27.0s
    # Below ~100 per-batch fixed overhead takes over (999 batches); above
    # ~1,000 the consumer starves more (0.44s at 500 vs 1.4s at 16,000) and
    # the per-batch resolve step works over longer reference lists. 250 sits
    # in the middle of the flat floor. Hypothesis for why the curve is this
    # shape at all: commit cost is dominated by per-row index maintenance,
    # which grouping cannot amortise, so the only thing batch size buys or
    # costs is pipeline overlap -- confirmed by the write-transaction-width
    # sweep in the same script being flat across a 64x range.
    upsert_batch_size: int = 250
    # Rows per db.write() transaction inside upsert_nodes/upsert_edges. This
    # used to be upsert_batch_size itself, which silently coupled two
    # independent knobs: raising the streaming ingest target from 1,000 to
    # 8,000 also widened every write transaction, so neither effect could be
    # attributed. Split out so perfo/benchmark_batch_size_sweep.py can vary one
    # axis at a time. 0 means "no chunking" -- commit the whole batch in one
    # transaction.
    ingest_write_chunk_size: int = 1000
    ingest_batch_bytes: int = 8 * 1024 * 1024
    # Batch-size sweep (perfo/benchmark_batch_size_sweep.py) put the wall-clock
    # floor at 200-350 operations per batch: below ~100 per-batch overhead takes
    # over, above ~1,000 the consumer starves. AdaptiveBatchController used to
    # search for this value at runtime and was deleted (see 1ccd459) -- its
    # candidate set started at upsert_batch_size and doubled, so it sat entirely
    # above the knee and could only pick something worse than its own default,
    # while paying 12 calibration batches to read noise (it chose 1,000, then
    # 2,000, then 8,000 on three runs of the identical corpus). A fixed constant
    # beats every size it could reach.
    lattice_cache_size_mb: int = 100

    # Search indexing uses CPU-bound parser processes. Saturate all logical CPUs
    # by default; the environment setting remains available when headroom is
    # preferred.
    analysis_workers: int = os.cpu_count() or 1

    # Minimum number of parsed files kept in flight ahead of the consumer.
    # Must exceed the files-per-batch the consumer swallows, or the worker pool
    # drains during batch assembly and idles through the whole commit (a
    # flat/100%/flat CPU sawtooth). Measured on gemseo: ~66 files per batch at
    # the 2,000-op batch size the adaptive controller picked, against an
    # in-flight window of only 32 (2 x 16 workers). At ~63 KB per pending
    # FileAnalysis this is cheap -- 256 in flight is ~16 MB.
    analysis_queue_depth: int = 256

    # LLM context bundle token budget (see context.py). Nodes are emitted in
    # hop order with full bodies while this budget lasts, then degrade to
    # signature + docstring. 4,000 is a deliberate default: it covers a seed
    # and its direct neighbours with room to spare, without drowning the
    # agent in the whole transitive closure.
    context_token_budget: int = 4000

    # Directories skipped by ingest_incremental's file walk (see graph/graph.py).
    # Third-party trees matter more than build artefacts here: a single
    # unexcluded site-packages or conda env pulls an entire dependency tree
    # into the graph, which is both the dominant ingestion cost and noise in
    # every search result. ".venv"/"venv" alone don't cover the common
    # alternatives -- "env" (conda/virtualenv default), a "site-packages"
    # living outside any recognised env dir, or ".tox"/".eggs" -- so those are
    # listed explicitly rather than assumed to be caught by Git ignore rules.
    default_exclude_patterns: List[str] = [
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        "dist",
        "build",
        ".git",
        ".worktrees",
        ".venv",
        "venv",
        "env",
        ".tox",
        ".eggs",
        "site-packages",
        "node_modules",
    ]


settings = Settings()

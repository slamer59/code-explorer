# code-retrieval-bench

Grades code-search CLIs against ground truth mined from a repository's own
git history. It knows nothing about any tool's internals: every tool is a
subprocess described in `adapters.toml`, and every tool's output is reduced
to TREC-style `(query_id, doc_id, rank, score)` rows before it is scored.

Scoring is `ranx`. Timing is `hyperfine`. Neither is reimplemented here.

See `docs/explanation/benchmarking.md` in the parent repo for the design
rationale, and `results/reports/` for generated output.

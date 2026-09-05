"""Merge multiple ranked search-result lists into one (hybrid retrieval,
Phase 6 of docs/explanation/latticedb-migration.md).

Uses Reciprocal Rank Fusion (RRF) rather than trying to normalize and blend
raw scores directly: BM25's score (higher = more relevant) and vector
search's score (a distance -- lower = more similar) are not on comparable
scales, and even within BM25 alone, scores aren't calibrated to a fixed
range. RRF sidesteps that entirely by fusing on rank position only --
standard, well-established technique (Cormack et al., 2009), and used here
because it's the option that works without picking scale/normalization
choices we have no principled basis for.
"""

from typing import Dict, List

from code_explorer.graph.records import SearchResult

DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    result_lists: List[List[SearchResult]],
    limit: int = 10,
    k: int = DEFAULT_RRF_K,
) -> List[SearchResult]:
    """Fuse several ranked SearchResult lists (e.g. BM25 hits, vector hits)
    into one ranked list, deduped by node_id.

    Each list contributes 1/(k + rank) to a node's fused score, rank being
    its 1-based position within that list; a node appearing in multiple
    lists sums its contributions, so results found by more than one
    retrieval mode are pushed up even if neither mode alone ranked them
    first. k=60 is the standard RRF constant from the original paper --
    dampens the impact of any single list's exact rank ordering, so this
    isn't overly sensitive to one retriever's noise.

    The returned SearchResult.score is the fused RRF score (higher =
    better, like BM25's convention) -- NOT comparable to either input
    list's own score, only to other fused scores from this same call.

    Returns:
        Up to `limit` results, sorted by fused score descending. Empty
        input (no lists, or all lists empty) returns [].
    """
    fused: Dict[str, float] = {}
    best_result: Dict[str, SearchResult] = {}

    for result_list in result_lists:
        for rank, result in enumerate(result_list, start=1):
            fused[result.node_id] = fused.get(result.node_id, 0.0) + 1.0 / (k + rank)
            if result.node_id not in best_result:
                best_result[result.node_id] = result

    ranked_ids = sorted(fused, key=lambda node_id: fused[node_id], reverse=True)

    return [
        SearchResult(
            node_id=node_id,
            node_type=best_result[node_id].node_type,
            name=best_result[node_id].name,
            file=best_result[node_id].file,
            score=fused[node_id],
        )
        for node_id in ranked_ids[:limit]
    ]


# Path fragments that mark a file as test code. Deliberately conservative --
# only unambiguous conventions, so a module legitimately named e.g.
# `contest.py` or `latest.py` is not demoted.
_TEST_PATH_MARKERS = ("/tests/", "/test/", "tests/", "test/")


def _is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or any(marker in path for marker in _TEST_PATH_MARKERS)
    )


def demote_tests(
    results: List[SearchResult], factor: float = 0.4
) -> List[SearchResult]:
    """Re-rank so an implementation outranks its own tests.

    BM25 scores term density, and a test is short: `test_get_function_dimension`
    is a two-line assert whose name and body are almost entirely the query
    terms, while the function it tests carries a long docstring and body that
    dilute them. Measured on gemseo, `search "function dimension"` returned
    three `test_get_function_dimension*` variants (13.742, 13.447, 13.368)
    above `get_function_dimension` itself (13.081) -- so the context bundle was
    seeded from the test file and expanded from there.

    Tests are kept, not dropped: "where is this tested" is a real question, and
    a test is sometimes the only caller that documents usage. They are just no
    longer allowed to displace the implementation.

    HYPOTHESIS: a flat multiplier is enough because the gap is small (~5% here)
    -- tests win by a nose, not by a mile. If a corpus turns up where tests
    outrank implementations by more than `factor`, this needs to become a
    signal in a proper ranking function rather than a post-hoc nudge.
    """
    if not results:
        return results
    adjusted = [
        SearchResult(
            node_id=r.node_id,
            node_type=r.node_type,
            name=r.name,
            file=r.file,
            score=r.score * factor if _is_test_file(r.file) else r.score,
        )
        for r in results
    ]
    return sorted(adjusted, key=lambda r: r.score, reverse=True)

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

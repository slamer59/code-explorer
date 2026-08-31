"""Tests for reciprocal_rank_fusion (Phase 6, hybrid retrieval merge).

Pure function, no backend needed. Kept small (3 tests): a node found by
both retrieval modes outranks one found by only one, a single input list's
order is preserved (no-op case), empty input returns empty output.
"""

from code_explorer.graph.records import SearchResult
from code_explorer.hybrid_search import reciprocal_rank_fusion


def _hit(node_id: str, score: float = 1.0) -> SearchResult:
    return SearchResult(node_id=node_id, node_type="Function", name=node_id, file="a.py", score=score)


def test_node_found_by_both_lists_outranks_single_list_top_hit():
    # bm25 ranks "shared" 2nd, vector ranks it 1st; "bm25_only" is bm25's
    # top hit but never appears in vector results at all.
    bm25 = [_hit("bm25_only"), _hit("shared")]
    vector = [_hit("shared"), _hit("vector_only")]

    fused = reciprocal_rank_fusion([bm25, vector])

    assert fused[0].node_id == "shared", "found by both modes should win over either mode's solo top hit"


def test_single_list_preserves_order():
    results = [_hit("a"), _hit("b"), _hit("c")]

    fused = reciprocal_rank_fusion([results])

    assert [r.node_id for r in fused] == ["a", "b", "c"]


def test_empty_input_returns_empty():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_limit_truncates_results():
    results = [_hit(str(i)) for i in range(20)]

    fused = reciprocal_rank_fusion([results], limit=5)

    assert len(fused) == 5

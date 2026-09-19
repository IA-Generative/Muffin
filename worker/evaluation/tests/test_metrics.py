from app import metrics


def test_precision_at_k_counts_relevant_fraction_of_what_was_retrieved():
    assert metrics.precision_at_k([True, False, True, False]) == 0.5


def test_precision_at_k_empty_retrieval_is_zero():
    assert metrics.precision_at_k([]) == 0.0


def test_recall_at_k_counts_relevant_fraction_of_what_exists():
    assert metrics.recall_at_k([True, False], total_relevant=4) == 0.25


def test_recall_at_k_with_no_relevant_documents_is_zero():
    assert metrics.recall_at_k([True, True], total_relevant=0) == 0.0


def test_recall_at_k_never_exceeds_one():
    # total_relevant is a document-level proxy (see app/metrics.py) - it can undercount the
    # chunks actually matched, so the ratio must be capped rather than reported >1.0.
    assert metrics.recall_at_k([True, True, True], total_relevant=2) == 1.0


def test_reciprocal_rank_of_first_relevant_result():
    assert metrics.reciprocal_rank([False, False, True, True]) == 1 / 3


def test_reciprocal_rank_with_no_relevant_result_is_zero():
    assert metrics.reciprocal_rank([False, False]) == 0.0


def test_ndcg_perfect_ranking_is_one():
    assert metrics.ndcg([True, True, False]) == 1.0


def test_ndcg_no_relevant_result_is_zero():
    assert metrics.ndcg([False, False, False]) == 0.0


def test_ndcg_rewards_relevant_results_appearing_earlier():
    early = metrics.ndcg([True, False, False])
    late = metrics.ndcg([False, False, True])
    assert early > late

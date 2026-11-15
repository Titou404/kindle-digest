"""Tests for the ranking quality measures (eval/rank_quality.py)."""

from rank_quality import auc, quality


def test_auc_is_one_for_a_perfect_order_and_one_half_for_ties():
    assert auc([9, 8], [3, 1]) == 1.0
    assert auc([5], [5]) == 0.5
    assert auc([2], [7]) == 0.0


def test_precision_counts_the_selected_articles_i_would_keep():
    labels = {"a": 1, "b": 0, "c": 1, "d": 0}
    items = [
        {"url": "a", "score": 9, "selected": True},
        {"url": "b", "score": 8, "selected": True},
        {"url": "c", "score": 2, "selected": False},
        {"url": "d", "score": None, "selected": False},  # not scored counts as 0
    ]
    assert quality(items, labels) == {"precision": 0.5, "selected": 2, "auc": 0.75}

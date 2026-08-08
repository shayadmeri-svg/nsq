"""Render-level tests for ``scientific_count_bar_chart``.

Guards the categorical count-distribution chart (tier distribution, modality
mix) against regressing back to the concentric-ring encoding, where arc
lengths at different radii are not comparable and the hover reduces to a
meaningless fraction.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from intelligence.ui_components import scientific_count_bar_chart  # noqa: E402


def test_inline_count_and_share():
    fig = scientific_count_bar_chart(
        {"Core": 5, "Adjacent": 8}, title="Tier distribution", source="s", sort="none",
    )
    t = fig.data[0]
    text = dict(zip(t.y, t.text))
    assert text["Core"] == "5  ·  38%"
    assert text["Adjacent"] == "8  ·  62%"


def test_hover_shows_unit_and_total():
    fig = scientific_count_bar_chart(
        {"Core": 5, "Adjacent": 8}, title="t", source="s", unit="candidates", sort="none",
    )
    hover = fig.data[0].hovertemplate
    assert "candidates" in hover
    assert "of 13" in hover  # total in hover
    assert "%{customdata:.0%}" in hover  # share


def test_sort_descending_puts_largest_on_top():
    fig = scientific_count_bar_chart(
        {"Small molecule": 12, "Biologics": 4}, title="t", source="s", sort="descending",
    )
    # categoryarray lists bottom->top, so the largest is last -> rendered on top.
    assert tuple(fig.layout.yaxis.categoryarray) == ("Biologics", "Small molecule")


def test_sort_none_preserves_caller_order():
    # Tiers are ordinal; magnitude sort must not reshuffle them.
    tiers = {"Strategic": 2, "Core": 5, "Adjacent": 8, "Stretch": 3}
    fig = scientific_count_bar_chart(tiers, title="t", source="s", sort="none")
    assert tuple(fig.layout.yaxis.categoryarray) == ("Stretch", "Adjacent", "Core", "Strategic")


def test_zero_count_category_still_listed():
    fig = scientific_count_bar_chart(
        {"Strategic": 0, "Core": 5}, title="t", source="s", sort="none",
    )
    labels = set(fig.data[0].y)
    assert "Strategic" in labels
    text = dict(zip(fig.data[0].y, fig.data[0].text))
    assert text["Strategic"].startswith("0  ·  0%")


def test_shares_sum_to_one():
    fig = scientific_count_bar_chart(
        {"A": 1, "B": 2, "C": 3}, title="t", source="s", sort="none",
    )
    shares = fig.data[0].customdata
    assert abs(sum(shares) - 1.0) < 1e-9


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
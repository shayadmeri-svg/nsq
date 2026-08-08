"""Render-level tests for ``scientific_status_dot_chart``.

Locks in the boolean monograph availability chart so it does not regress back
to the uninformative concentric-ring encoding: filled dot = on, hollow dot =
off, status word shown inline, detail surfaced on hover, deterministic row
order, and a meaningless x-axis hidden.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from intelligence.ui_components import scientific_status_dot_chart  # noqa: E402


def test_filled_vs_hollow_markers_by_state():
    fig = scientific_status_dot_chart(
        {"IP 2026": True, "Ph. Eur.": False, "USP": True},
        title="Monograph availability", source="regulatory passport",
    )
    by_label = {t.y[0]: t for t in fig.data}
    assert by_label["IP 2026"].marker.symbol == "circle"
    assert by_label["Ph. Eur."].marker.symbol == "circle-open"
    assert by_label["USP"].marker.symbol == "circle"


def test_inline_status_words():
    fig = scientific_status_dot_chart(
        {"IP 2026": True, "Ph. Eur.": False, "USP": True},
        title="t", source="s",
    )
    words = {t.y[0]: t.text[0] for t in fig.data}
    assert words["IP 2026"] == "Available"
    assert words["Ph. Eur."] == "Not available"
    assert words["USP"] == "Available"


def test_custom_on_off_labels():
    fig = scientific_status_dot_chart(
        {"A": True, "B": False}, on_label="Yes", off_label="No", title="t", source="s",
    )
    words = {t.y[0]: t.text[0] for t in fig.data}
    assert words == {"A": "Yes", "B": "No"}


def test_hover_surfaces_detail_when_provided():
    fig = scientific_status_dot_chart(
        {"IP 2026": True, "Ph. Eur.": False, "USP": True},
        title="t", source="s",
        detail={"IP 2026": "USP <129>, Ph. Eur. 2031", "Ph. Eur.": "", "USP": "USP <129>"},
    )
    hovers = {t.y[0]: t.hovertemplate for t in fig.data}
    # On item with detail surfaces it on hover.
    assert "USP <129>, Ph. Eur. 2031" in hovers["IP 2026"]
    # Off item without detail does not append an empty block.
    assert "<br><br>" not in hovers["Ph. Eur."]


def test_hover_detail_is_truncated():
    long_text = "x" * 500
    fig = scientific_status_dot_chart(
        {"A": True}, title="t", source="s", detail={"A": long_text},
    )
    hover = fig.data[0].hovertemplate
    assert "…" in hover
    assert len(hover) < 300


def test_x_axis_hidden_and_order_deterministic():
    fig = scientific_status_dot_chart(
        {"IP 2026": True, "Ph. Eur.": False, "USP": True},
        title="t", source="s",
    )
    assert fig.layout.xaxis.visible is False
    # categoryarray lists bottom->top, so first category ends at the top.
    assert tuple(fig.layout.yaxis.categoryarray) == ("USP", "Ph. Eur.", "IP 2026")


def test_subtitle_counts_on_items():
    fig = scientific_status_dot_chart(
        {"A": True, "B": True, "C": False}, title="t", source="s",
    )
    assert "2 of 3" in fig.layout.title.text


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
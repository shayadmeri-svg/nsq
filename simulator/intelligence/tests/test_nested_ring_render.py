"""Render-level tests for ``scientific_nested_ring`` hover/legend semantics.

Guards against the regression where the monograph-availability donut showed
meaningless numeric hover/legend ("IP 2026: 1.0/1") because the helper
hardcoded numeric formatting for a binary/categorical encoding.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from intelligence.ui_components import scientific_nested_ring  # noqa: E402


def _legend_entries(fig) -> dict:
    return {t.name: t.hovertemplate for t in fig.data if t.showlegend}


def test_numeric_mode_unchanged():
    fig = scientific_nested_ring(
        {"Patent": 87, "Regulatory": 62, "Demand": 71, "Plant Fit": 54},
        max_value=100, title="Pillar score profile", source="engine",
    )
    entries = _legend_entries(fig)
    assert entries["Patent: 87"] == "Patent: 87.0/100<extra></extra>"
    assert "Patent: 87.0/100" in entries["Patent: 87"]
    # No categorical labels leak into numeric mode.
    assert "Available" not in str(entries)


def test_categorical_mode_shows_status_labels():
    fig = scientific_nested_ring(
        {"IP 2026": 1, "Ph. Eur.": 0, "USP": 1},
        max_value=1, title="Monograph availability", source="regulatory passport",
        value_labels={"IP 2026": "Available", "Ph. Eur.": "Not available", "USP": "Available"},
    )
    entries = _legend_entries(fig)
    assert "IP 2026: Available" in entries
    assert "Ph. Eur.: Not available" in entries
    assert "USP: Available" in entries
    # Hover must carry the status, not a raw fraction.
    assert entries["IP 2026: Available"] == "IP 2026: Available<extra></extra>"
    assert entries["Ph. Eur.: Not available"] == "Ph. Eur.: Not available<extra></extra>"


def test_categorical_mode_never_emits_raw_fraction():
    fig = scientific_nested_ring(
        {"IP 2026": 1, "Ph. Eur.": 0, "USP": 0},
        max_value=1, title="t", source="s",
        value_labels={"IP 2026": "Available", "Ph. Eur.": "Not available", "USP": "Not available"},
    )
    rendered = str([(t.name, t.hovertemplate) for t in fig.data])
    assert "1.0/1" not in rendered and "0.0/1" not in rendered
    assert "/1" not in rendered


def test_zero_value_category_still_in_legend():
    # An empty monograph must still appear in the legend (carried by its track).
    fig = scientific_nested_ring(
        {"IP 2026": 0, "Ph. Eur.": 0, "USP": 0},
        max_value=1, title="t", source="s",
        value_labels={"IP 2026": "Not available", "Ph. Eur.": "Not available", "USP": "Not available"},
    )
    names = {t.name for t in fig.data if t.showlegend}
    assert "IP 2026: Not available" in names
    assert len(names) == 3


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
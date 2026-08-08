"""Render-level tests for ``render_gmp_pillars``.

These guard the GMP pillar card against the class of regressions that kept
re-appearing when its HTML was hand-written inline styles: stray emoji glyphs,
empty flex wrappers, missing chips, or status badges losing their colour.

Run directly (``python test_gmp_pillars_render.py``) or via pytest. The test
imports only the pure render function, so it does not need a Streamlit
script context — only the ``streamlit`` package importable (a simulator dep).
"""
from __future__ import annotations

import os
import re
import sys

# Make ``intelligence`` importable when run as a standalone script.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from intelligence.ui_components import render_gmp_pillars  # noqa: E402

# -- fixtures ---------------------------------------------------------------
_PILLARS = [
    {
        "pillar_id": "aseptic", "title": "Aseptic Processing", "applies": True,
        "rationale": "Sterile fill-finish.", "key_controls": ["closed systems"],
        "required_capabilities": ["sterile_fill", "isolator_technology"],
    },
    {
        "pillar_id": "hpapi", "title": "HPAPI Containment", "applies": True,
        "rationale": "Potent containment.", "key_controls": ["OEB 5"],
        "required_capabilities": ["dedicated_equipment", "dust_extraction",
                                  "isolator_technology", "potent_containment"],
    },
    {
        "pillar_id": "cleaning", "title": "Cleaning Validation", "applies": True,
        "rationale": "Cleaning.", "key_controls": ["MACO"],
        "required_capabilities": ["analytical_qc", "dedicated_equipment", "validated_cleaning"],
    },
    {
        "pillar_id": "lifecycle", "title": "Lifecycle Validation", "applies": True,
        "rationale": "Lifecycle.", "key_controls": ["CPV"],
        "required_capabilities": ["analytical_development", "method_validation",
                                  "process_validation", "stability_testing"],
    },
    {
        "pillar_id": "packaging", "title": "Packaging Integrity", "applies": True,
        "rationale": "Packaging.", "key_controls": ["serialization"],
        "required_capabilities": ["serialisation", "cold_chain"],
    },
]

_EMOJI = re.compile(r"[⚠✓]")  # ⚠ U+26A0, ✓ U+2713 — must never appear
_INLINE_STYLE = re.compile(r' style="')   # GMP cards are class-based; no inline styles
_EMPTY_HEADING = re.compile(r'gmp-card-heading">\s*</div>')
_BADGE = re.compile(r'gmp-badge--(\w+)')


def _caps(*items: str) -> set[str]:
    return set(items)


# -- invariants that hold for every render ----------------------------------
def _assert_common_invariants(html: str) -> None:
    assert not _EMOJI.search(html), "emoji warning/check glyph leaked into GMP render"
    # The only allowed inline style is the section eyebrow's margin-bottom; the
    # GMP card markup itself must be class-based.
    gmp_html = html.split("Core GMP Methodological Pillars", 1)[-1] if "Core GMP" in html else html
    assert not _INLINE_STYLE.search(gmp_html), "GMP card markup uses inline styles"
    assert not _EMPTY_HEADING.search(html), "empty gmp-card-heading wrapper (icon removed but gap left)"


def test_empty_input_returns_empty():
    assert render_gmp_pillars([]) == ""
    assert render_gmp_pillars([{"pillar_id": "x", "applies": False, "required_capabilities": []}]) == ""


def test_all_ready_when_no_plant_capabilities():
    # No plant comparison -> every pillar is 100% ready.
    html = render_gmp_pillars(_PILLARS, plant_capabilities=None)
    _assert_common_invariants(html)
    assert "Core GMP Methodological Pillars" in html
    # Five ready detail cards, each with a success badge.
    assert html.count("gmp-card") >= 5
    assert sorted(set(_BADGE.findall(html))) == ["success"]
    assert "missing:" not in html


def test_gap_predominant():
    # Pilot plant: only packaging is satisfied; the other three pillars gap.
    caps = _caps("serialisation", "cold_chain")
    html = render_gmp_pillars(_PILLARS, plant_capabilities=caps)
    _assert_common_invariants(html)
    assert "GMP readiness gaps" in html
    assert "gmp-badge--danger" in html
    assert "missing: dedicated_equipment" in html
    assert "missing: potent_containment" in html
    # Each missing chip is prefixed with the literal label, no glyph.
    for chip in re.findall(r'gmp-missing-chip">([^<]+)<', html):
        assert chip.startswith("missing: "), chip


def test_mixed_gap_and_partial():
    # Satisfy half of aseptic -> partial; leave the rest as gaps/partial.
    caps = _caps("sterile_fill", "serialisation", "cold_chain")
    html = render_gmp_pillars(_PILLARS, plant_capabilities=caps)
    _assert_common_invariants(html)
    assert "GMP readiness gaps" in html
    assert "gmp-badge--warning" in html
    assert "Mixed" in html
    assert "<strong>Unsupported:</strong>" in html
    assert "<strong>Partial:</strong>" in html


def test_partial_only():
    # Every pillar half-matched -> partial summary, no gap card.
    caps = _caps("sterile_fill", "dedicated_equipment", "analytical_qc",
                 "analytical_development", "serialisation")
    html = render_gmp_pillars(_PILLARS, plant_capabilities=caps)
    _assert_common_invariants(html)
    assert "GMP readiness gaps" in html
    assert "gmp-badge--warning" in html
    assert "partially matched" in html
    assert "gmp-badge--danger" not in html


def test_show_title_false_omits_eyebrow():
    html = render_gmp_pillars(_PILLARS, plant_capabilities=None, show_title=False)
    assert "Core GMP Methodological Pillars" not in html
    # Still renders the pillar cards.
    assert html.count("gmp-card") >= 5


def test_detail_pillar_cards_have_geometric_icon():
    html = render_gmp_pillars(_PILLARS, plant_capabilities=None)
    icons = re.findall(r'gmp-pillar-icon">([^<]+)<', html)
    # One per pillar; geometric markers, never emoji.
    assert len(icons) == 5
    assert set(icons) <= {"◆", "▲", "■", "●", "□"}


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
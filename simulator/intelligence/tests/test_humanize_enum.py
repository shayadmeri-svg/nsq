"""Tests for ``humanize_enum`` and ``attribute_strip``.

Guards against raw snake_case enum tokens (``small_molecule``, ``iv``,
``prefilled_pen``) leaking into the UI on the ranked-candidate cards and the
plant-readiness complexity tiles, and against the attribute strip regressing to
hand-inlined styles (which produced an oversized/faint separator and drifted
from the design system).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from intelligence.ui_components import attribute_strip, humanize_enum  # noqa: E402


# -- humanize_enum ---------------------------------------------------------
def test_snake_case_to_sentence_case():
    # Scientific convention: only the first word is capitalised.
    assert humanize_enum("small_molecule") == "Small molecule"
    assert humanize_enum("monoclonal_antibody") == "Monoclonal antibody"
    assert humanize_enum("prefilled_pen") == "Prefilled pen"
    assert humanize_enum("tablet") == "Tablet"


def test_abbreviation_overrides():
    assert humanize_enum("iv") == "IV"
    assert humanize_enum("im") == "IM"
    assert humanize_enum("sc") == "SC"
    assert humanize_enum("mab") == "Monoclonal antibody"


def test_empty_returns_dash():
    assert humanize_enum(None) == "—"
    assert humanize_enum("") == "—"
    assert humanize_enum("   ") == "—"


def test_no_underscore_leak_in_output():
    # Whatever the input, the rendered label must never contain an underscore.
    for t in ["small_molecule", "monoclonal_antibody", "prefilled_pen", "iv", "x_y_z"]:
        assert "_" not in humanize_enum(t)


# -- attribute_strip -------------------------------------------------------
def test_strip_uses_design_system_classes_not_inline_styles():
    html = attribute_strip([("Modality", "Small molecule"), ("Form", "Tablet"), ("Sterility", "No")])
    # Structure is carried by classes, not inline styles (single source of truth).
    assert 'class="cdmo-attr-strip"' in html
    assert 'class="cdmo-attr-pair"' in html
    assert 'class="cdmo-attr-label"' in html
    assert 'class="cdmo-attr-value"' in html
    assert 'class="cdmo-attr-sep"' in html
    assert "style=" not in html


def test_strip_has_pair_separators_and_labels():
    html = attribute_strip([("Modality", "Small molecule"), ("Form", "Tablet"), ("Sterility", "No")])
    # Three pairs => two middot separators.
    assert html.count("·") == 2
    assert "Modality" in html and "Small molecule" in html
    assert "Form" in html and "Tablet" in html
    assert "Sterility" in html and "No" in html


def test_strip_no_raw_pipe_separator():
    # The old card joined attributes with " | "; the strip must not.
    html = attribute_strip([("A", "1"), ("B", "2")])
    assert " | " not in html


def test_strip_separator_carries_class_not_inline_color():
    # The separator must not re-introduce an inline colour (which produced the
    # faint #d9d9d9 dot); it is styled via .cdmo-attr-sep in CSS.
    html = attribute_strip([("Modality", "Small molecule"), ("Form", "Tablet")])
    assert '<span class="cdmo-attr-sep">·</span>' in html
    assert "#d9d9d9" not in html


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
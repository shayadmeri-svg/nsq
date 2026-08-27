"""Monochrome scientific bioicons for the manufacturer app.

Vendored from ``simulator/intelligence/ui_components.py``'s ``_BIOICONS``
set (icon *data* only — SVG path strings, low drift risk). All icons use
``stroke="currentColor"`` so they inherit text color and stay
monochrome, per the UI/UX tone rule (no emoji, no colored Figma icons).

Plus two small affordance icons built inline (chevron, Q-engine mark)
rather than pulled from Figma as raster — see palette.py docstring.
"""

from __future__ import annotations

BIOICONS: dict[str, str] = {
    "dna": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M2 15c6.667-6 13.333 0 20-6"/>
      <path d="M9 22c1.798-4.103 5.102-7.497 10-9"/>
      <path d="M15 2c-1.798 4.103-5.102 7.497-10 9"/>
      <path d="M22 9c-6.667 6-13.333 0-20 6"/>
    </svg>
    """,
    "pill": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="m10.5 20.5 10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7Z"/>
      <path d="m8.5 8.5 7 7"/>
    </svg>
    """,
    "factory": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M2 22h20"/>
      <path d="M8 21V10l6-3v14"/>
      <path d="M18 21V10l-4-2"/>
      <path d="M22 7a2 2 0 0 0-2-2h-6V3a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v1"/>
    </svg>
    """,
    "microscope": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M6 18h12"/>
      <path d="M3 22h18"/>
      <path d="M14 12a3 3 0 1 0-4 0 3 3 0 0 0 4 0Z"/>
      <path d="M12 15v5"/>
      <path d="M8 9l-2 5"/>
      <path d="M16 9l2 5"/>
      <path d="M10 6h4"/>
    </svg>
    """,
    "chart": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 3v18h18"/>
      <path d="m19 9-5 5-4-4-3 3"/>
    </svg>
    """,
    "beaker": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4.5 3h15"/>
      <path d="M6 3v16a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V3"/>
      <path d="M6 14h12"/>
    </svg>
    """,
    "flask": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M10 2v7.31"/>
      <path d="M14 2v7.31"/>
      <path d="M8.5 2h7"/>
      <path d="m14 9-5.27 8.17a2.5 2.5 0 0 0 2.1 3.83h3.34a2.5 2.5 0 0 0 2.1-3.83L10 9"/>
    </svg>
    """,
    "molecule": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <circle cx="5" cy="5" r="2"/>
      <circle cx="19" cy="5" r="2"/>
      <circle cx="19" cy="19" r="2"/>
      <circle cx="5" cy="19" r="2"/>
      <path d="M10 10 7 7"/>
      <path d="m14 10 3-3"/>
      <path d="m10 14-3 3"/>
      <path d="m14 14 3 3"/>
    </svg>
    """,
    "calendar": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <rect width="18" height="18" x="3" y="4" rx="2" ry="2"/>
      <path d="M16 2v4"/>
      <path d="M8 2v4"/>
      <path d="M3 10h18"/>
    </svg>
    """,
    "document": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <path d="M14 2v6h6"/>
      <path d="M16 13H8"/>
      <path d="M16 17H8"/>
      <path d="M10 9H8"/>
    </svg>
    """,
    "warning": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
      <path d="M12 9v4"/>
      <path d="M12 17h.01"/>
    </svg>
    """,
    "rocket": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09Z"/>
      <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.3 22.3 0 0 1-4 2Z"/>
      <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/>
      <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>
    </svg>
    """,
    "search": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="11" cy="11" r="8"/>
      <path d="m21 21-4.3-4.3"/>
    </svg>
    """,
    "filter": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>
    </svg>
    """,
    "download": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <path d="M7 10 12 15 17 10"/>
      <path d="M12 15V3"/>
    </svg>
    """,
    "info": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="10"/>
      <path d="M12 16v-4"/>
      <path d="M12 8h.01"/>
    </svg>
    """,
    "check": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M20 6 9 17l-5-5"/>
    </svg>
    """,
    # Affordance icons built inline (not in the simulator set).
    "chevron-down": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="m6 9 6 6 6-6"/>
    </svg>
    """,
    "chevron-right": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="m9 18 6-6-6-6"/>
    </svg>
    """,
    # Q-engine mark — a stylized "Q" as a monochrome molecule-ish glyph.
    "qmark": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="11" cy="11" r="7"/>
      <path d="m16 16 4 4"/>
    </svg>
    """,
}


def bioicon(name: str, size: int = 20, color: str = "currentColor") -> str:
    """Return a bioicon as a raw HTML string sized to ``size`` px.

    ``color`` defaults to ``currentColor`` so the icon inherits the
    surrounding text color (monochrome). Pass an explicit hex to override.
    Unknown names fall back to the molecule icon.
    """
    svg = BIOICONS.get(name, BIOICONS["molecule"])
    return f'<span style="display:inline-flex;width:{size}px;height:{size}px;color:{color};vertical-align:middle;">{svg}</span>'


def wordmark() -> str:
    """Q-engine wordmark: bioicon mark + wordmark text (no raster logo)."""
    mark = bioicon("qmark", 22, "var(--mq-primary)")
    return f'<div class="mq-wordmark">{mark}<span>Q-engine</span></div>'
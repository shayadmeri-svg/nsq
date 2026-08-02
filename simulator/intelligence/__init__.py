"""CDMO off-patent drug intelligence client package.

This package mirrors the engine/shared modules so the Streamlit app can fall
back to in-process scoring when the FastAPI engine is unreachable.
"""

from __future__ import annotations

import os
import sys

# Allow bare imports between intelligence_*.py modules copied from engine/shared.
sys.path.insert(0, os.path.dirname(__file__))

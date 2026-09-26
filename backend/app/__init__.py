"""NSQ platform backend.

The domain code lives in the repo's core/ directory as flat modules
(data_loader, intelligence_scorer, ...); put it on sys.path once here so
every app module can import it the same way the loaders and tests do.
"""

import sys

from .config import settings

_core = str(settings.core_dir)
if _core not in sys.path:
    sys.path.insert(0, _core)

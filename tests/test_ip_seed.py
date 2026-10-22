"""data/ip_seed.json loads cleanly, and the entry checks catch the usual misreads (data/IP_SEED_GUIDE.md)."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "redis-loader"))
sys.path.insert(0, str(ROOT / "core"))

from sources import ip  # noqa: E402

SEED = json.loads((ROOT / "data" / "ip_seed.json").read_text(encoding="utf-8"))


def test_seed_has_no_errors():
    for key, entry in SEED["molecules"].items():
        for mon in entry["monographs"]:
            errors, _ = ip.check(key, mon)
            assert errors == [], (key, errors)


def test_checks_catch_misreads():
    mon = json.loads(json.dumps(SEED["molecules"]["telmisartan"]["monographs"][0]))
    mon["assay"] = {"lo": 90.0, "hi": 10.0}           # "1 ¡0.0" read as 10.0
    mon["dissolution"]["q_pct"] = "75 per cent"         # text, not a number
    mon["dissolution"]["rpm"] = 750                     # a slipped digit
    errors, _ = ip.check("Telmisartan", mon)            # not a lowercase INN key
    joined = " | ".join(errors)
    assert "assay 90.0–10.0" in joined and "q_pct must be a number" in joined and "rpm = 750" in joined and "key 'Telmisartan'" in joined

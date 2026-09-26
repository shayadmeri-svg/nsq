"""Active-ingredient extraction from CDSCO product names, and matching to the
tracked molecule set (the 26 molecules with patent/regulatory profiles).

    "Telmisartan 40 mg and Amlodipine 5 mg Tablets IP (Telma-AM)"
        -> ["telmisartan", "amlodipine"]

Deliberately rule-based and conservative: it strips brand names in
brackets, dose/strength text, dosage-form and pharmacopoeia words, and
salt/hydrate suffixes. Output keys are lowercase base names; they are good
enough to group NSQ alerts by ingredient and to match the tracked set, not
to serve as an ontology.
"""

from __future__ import annotations

import re

_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_DOSE = re.compile(r"\b\d[\d.,/]*\s*(mg|mcg|µg|g|gm|ml|iu|i\.u\.|%|w/w|w/v|v/v|lakh|million)?\b", re.I)
_SPLIT = re.compile(r"\s*(?:&|\+|,|/|\band\b|\bwith\b|\bplus\b)\s*", re.I)

_STOP = {
    # forms / release
    "tablet", "tablets", "tab", "tabs", "capsule", "capsules", "cap", "caps", "injection", "injections", "inj",
    "syrup", "suspension", "oral", "solution", "drops", "drop", "cream", "ointment", "gel", "lotion", "powder",
    "granules", "sachet", "sachets", "spray", "inhaler", "infusion", "emulsion", "elixir", "linctus",
    "dispersible", "film", "coated", "uncoated", "chewable", "effervescent", "gastro", "resistant", "enteric",
    "delayed", "prolonged", "sustained", "extended", "modified", "controlled", "release", "sr", "er", "xr",
    "dr", "cr", "mr", "od", "ds", "forte", "plus", "kid", "kids", "paediatric", "pediatric", "for", "use",
    "only", "the", "of", "in", "sterile", "vial", "vials", "ampoule", "ampoules", "dry", "bp", "ip", "usp",
    "i.p", "i.p.", "b.p", "u.s.p", "ph", "eur", "nf", "each", "contains", "containing", "per", "strip",
    "bottle", "bottles", "pack", "unit", "units", "dose", "doses", "mouth", "wash", "eye", "ear", "nasal",
    "topical", "vaginal", "rectal", "suppository", "suppositories", "pessary", "shampoo", "soap", "paste",
    "tooth", "dental", "liquid", "concentrate", "reconstitution", "freeze", "dried", "lyophilized",
    "lyophilised", "intravenous", "iv", "im", "sc", "sugar", "free", "flavoured", "flavour", "orange",
    "mint", "mango", "vet", "veterinary", "bolus", "feed", "supplement", "premix", "hydrochloride",
    "hcl", "hydrobromide", "sodium", "potassium", "calcium", "magnesium", "zinc", "besylate", "besilate",
    "maleate", "citrate", "phosphate", "sulphate", "sulfate", "succinate", "tartrate", "mesylate",
    "fumarate", "acetate", "trihydrate", "monohydrate", "dihydrate", "hemihydrate", "anhydrous",
    "bromide", "dipropionate", "propionate", "valerate", "nitrate", "lactate", "gluconate", "carbonate",
    "oxide", "hyclate", "disodium", "dimaleate", "bitartrate", "palmitate", "stearate", "benzoate",
    "salt", "base", "dihydrochloride", "compound", "combination", "kit", "equivalent", "eq", "to", "as", "ip2022", "ip2018",
}

# The API name of each tracked molecule reduces to one of these keys.
def ingredient_key(text: str) -> str:
    raw = re.findall(r"[a-z]+", text.lower())
    words: list[str] = []
    for w in raw:
        if w == "vit":
            w = "vitamin"
        if w in _STOP:
            continue
        # single letters are pharmacopoeia initials ("I.P.") except vitamin letters
        if len(w) == 1 and not (words and words[-1] == "vitamin"):
            continue
        words.append(w)
    return " ".join(words[:3]).strip()


def extract_ingredients(product_name: str) -> list[str]:
    """Distinct ingredient keys in a product name, in order of appearance."""
    if not product_name:
        return []
    s = _BRACKETS.sub(" ", str(product_name))
    s = _DOSE.sub(" ", s)
    out: list[str] = []
    for part in _SPLIT.split(s):
        key = ingredient_key(part)
        if len(key) >= 4 and key not in out:
            out.append(key)
    return out[:6]


def tracked_index(patents: dict) -> dict[str, str]:
    """ingredient key -> molecule_key for the tracked set.

    Indexed by the API name's first significant word too, so
    'Amlodipine Besylate' is found as 'amlodipine'."""
    idx: dict[str, str] = {}
    for mkey, p in patents.items():
        k = ingredient_key(p.api_name)
        if k:
            idx[k] = mkey
            idx.setdefault(k.split()[0], mkey)
    return idx


def match_tracked(ingredient: str, index: dict[str, str]) -> str | None:
    if not ingredient:
        return None
    if ingredient in index:
        return index[ingredient]
    first = ingredient.split()[0]
    if first in index:
        return index[first]
    # Misspellings are common in CDSCO data ("paracetmol", "telmisarten").
    if len(first) >= 6:
        try:
            from rapidfuzz import fuzz, process
        except ImportError:  # pragma: no cover
            return None
        pool = [k for k in index if k[:2] == first[:2] and abs(len(k) - len(first)) <= 3]
        hit = process.extractOne(first, pool, scorer=fuzz.ratio, score_cutoff=88) if pool else None
        if hit:
            return index[hit[0]]
    return None

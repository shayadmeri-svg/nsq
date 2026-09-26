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
    # Other spellings (INN/BAN/USAN, NSQ misspellings) recorded by the universe builder.
    for mkey, p in patents.items():
        for a in getattr(p, "aliases", None) or []:
            ak = ingredient_key(a)
            if ak:
                idx.setdefault(ak, mkey)
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


# --- cross-source name resolution ----------------------------------------------
# CDSCO uses Indian/British names (INN/BAN); the Orange Book and Purple Book use
# US names (USAN). Keys are ingredient_key() outputs.
USAN_SYNONYMS: dict[str, str] = {
    "paracetamol": "acetaminophen",
    "salbutamol": "albuterol",
    "levosalbutamol": "levalbuterol",
    "amoxycillin": "amoxicillin",
    "guaiphenesin": "guaifenesin",
    "frusemide": "furosemide",
    "glibenclamide": "glyburide",
    "adrenaline": "epinephrine",
    "noradrenaline": "norepinephrine",
    "lignocaine": "lidocaine",
    "rifampicin": "rifampin",
    "pethidine": "meperidine",
    "thyroxine": "levothyroxine",
    "chlorphenamine": "chlorpheniramine",
    "isoprenaline": "isoproterenol",
    "oestradiol": "estradiol",
    "cyclosporin": "cyclosporine",
    "ciclosporin": "cyclosporine",
    "aciclovir": "acyclovir",
    "valaciclovir": "valacyclovir",
    "benzylpenicillin": "penicillin g",
    "phenoxymethylpenicillin": "penicillin v",
    "hyoscine": "scopolamine",
    "hyoscine butylbromide": "scopolamine",
    "dicycloverine": "dicyclomine",
    "cephalexin": "cephalexin",
    "cefalexin": "cephalexin",
    "cefuroxime axetil": "cefuroxime",
    "sulphamethoxazole": "sulfamethoxazole",
    "sulfamethoxazole": "sulfamethoxazole",
    "sulphasalazine": "sulfasalazine",
    "sulphadiazine": "sulfadiazine",
    "chlorthalidone": "chlorthalidone",
    "mesalazine": "mesalamine",
    "ondansetron": "ondansetron",
    "glyceryl trinitrate": "nitroglycerin",
    "colecalciferol": "cholecalciferol",
    "vitamin d": "cholecalciferol",
    "ergocalciferol": "ergocalciferol",
    "tretinoin": "tretinoin",
    "trimethoprim": "trimethoprim",
    "metformin": "metformin",
    "nifedipine": "nifedipine",
    "dexchlorpheniramine": "dexchlorpheniramine",
    "gentamycin": "gentamicin",
    "amikacin": "amikacin",
    "clavulanate": "clavulanate",
    "clavulanic acid": "clavulanate",
    "potassium clavulanate": "clavulanate",
    "domperidone": "domperidone",
    "esomeprazole magnesium": "esomeprazole",
    "rosuvastatin": "rosuvastatin",
    "atorvastatin": "atorvastatin",
    "dextromethorphan": "dextromethorphan",
    "povidone iodine": "povidone iodine",
    "iron sucrose": "iron sucrose",
    "ferrous sulphate": "ferrous sulfate",
    "magnesium sulphate": "magnesium sulfate",
    "zinc sulphate": "zinc sulfate",
    "methylprednisolone": "methylprednisolone",
    "beclomethasone": "beclomethasone",
    "cotrimoxazole": "sulfamethoxazole",
}


def us_name(key: str) -> str:
    """ingredient key -> the US (USAN) spelling used by FDA sources."""
    if not key:
        return key
    if key in USAN_SYNONYMS:
        return USAN_SYNONYMS[key]
    first = key.split()[0]
    if first in USAN_SYNONYMS:
        return USAN_SYNONYMS[first]
    # BAN 'ph' spellings of sulfur compounds: sulphate -> sulfate
    return re.sub(r"sulph", "sulf", key)


def molecule_key_for(name: str) -> str:
    """Stable snake_case molecule key from an ingredient name."""
    return re.sub(r"[^a-z0-9]+", "_", ingredient_key(name) or name.lower()).strip("_")


def fold_variants(counts: dict[str, int], min_len: int = 6, cutoff: int = 90) -> dict[str, str]:
    """Map misspelled ingredient keys to the most frequent close spelling.

    counts: key -> frequency. Returns variant -> canonical for every key that
    folds into another (canonical keys map to themselves implicitly)."""
    try:
        from rapidfuzz import fuzz
    except ImportError:  # pragma: no cover
        return {}
    ordered = sorted(counts, key=lambda k: (-counts[k], k))
    canon: list[str] = []
    out: dict[str, str] = {}
    for k in ordered:
        hit = None
        if len(k) >= min_len:
            for c in canon:
                if c[:2] == k[:2] and abs(len(c) - len(k)) <= 3 and fuzz.ratio(k, c) >= cutoff:
                    hit = c
                    break
        if hit:
            out[k] = hit
        else:
            canon.append(k)
    return out

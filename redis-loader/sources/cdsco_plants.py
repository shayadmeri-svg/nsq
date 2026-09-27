"""Indian manufacturing plants and what each one is licensed to make, from CDSCO's official records.

Two official sources, merged into one registry keyed by plant:

1. CDSCO SUGAM "Approved Manufacturing Sites by State FDA"
   (cdscoonline.gov.in/CDSCO/manuf_site): about 900 premises with licence number,
   own vs loan licence, loan licensee, address, licence form, issue and expiry dates.
   The licence form is itself a capability: Form 25 covers drugs outside Schedules
   C, C(1) and X; Form 28 covers Schedule C / C(1) products (biologicals, sera,
   parenterals, ophthalmics); the "A" forms are loan licences.

2. CDSCO "WHO-GMP certified manufacturing units for COPP" (a PDF of ~180 pages, one
   row per unit): name and address, plus the free-text "category of drugs permitted
   to manufacture under WHO-GMP" — dosage forms, segregated blocks (beta-lactam,
   cephalosporin, hormone, cytotoxic...), APIs, and certificate dates.

Capabilities are parsed into a fixed vocabulary (CAPABILITY_TERMS) and every
capability keeps the sentence it came from, the source and the certificate dates,
so the registry can always show why a plant is said to make something.

Outputs:
    data/sources/cdsco_plants.json   normalised registry (the universe / API read this)
    data/sources/cdsco_plants.csv    one row per plant, for eyeballing in a spreadsheet
    data/raw/cdsco_plants/           the untouched HTML pages and PDF

CDSCO's servers refuse many cloud and data-centre networks: run this from a
machine in India or your own laptop, then copy the JSON to the server.

    python redis-loader/fetch_source.py cdsco_plants
    python redis-loader/fetch_source.py cdsco_plants --from-file ~/Downloads/who_gmp.pdf   # PDF already downloaded
"""

from __future__ import annotations

import csv
import html
import json
import re
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlencode

from .common import Ctx, Unreachable, http_get, write_normalized

SUGAM_URL = "https://cdscoonline.gov.in/CDSCO/app_srv/cdsco/global/jsp/Approved_Manuf_Site.jsp"
WHO_GMP_URLS = [
    # newest first; the first one that downloads is used
    "https://cdsco.gov.in/opencms/resources/UploadCDSCOWeb/2018/UploadIndustryCommon/Final%20WHO%20GMP%20data%20for%20website%2011.09.2025.pdf",
    "https://cdsco.gov.in/opencms/resources/UploadCDSCOWeb/2018/UploadIndustryCommon/WHO%20GMP%20CoPP%20list24.pdf",
    "https://cdsco.gov.in/opencms/resources/UploadCDSCOWeb/2018/UploadIndustryCommon/listwhogmp.pdf",
]
META = {
    "title": "CDSCO manufacturing plants and capabilities",
    "publisher": "Central Drugs Standard Control Organisation (India)",
    "url": SUGAM_URL,
    "page": "https://cdscoonline.gov.in/CDSCO/manuf_site",
    "cadence": "monthly (CDSCO updates both lists a few times a year)",
    "feeds": ["Plant registry", "Plant capabilities", "Site directory"],
}

# --------------------------------------------------------------------------- vocabulary

# canonical capability -> patterns (lower-case text). Order matters only for display.
DOSAGE_FORMS: dict[str, list[str]] = {
    "tablet": [r"\btab(let|lets|s)?\b", r"\btabkes\b", r"\bcaplets?\b"],
    "capsule_hard": [r"(?<!gelatin )(?<!gelatine )(?<!geletin )(?<!soft )\bca[po]s?\s?u?les?\b", r"\bcaps\b", r"hard gelatin"],
    "capsule_soft": [r"soft\s*ge[lt]", r"\bsgc\b"],
    "lozenge": [r"lozenges?", r"pastilles?"],
    "oral_liquid": [r"oral\s*liquid", r"liquid\s*orals?", r"(?<!dry )\bsyrups?\b", r"(?<!dry )(?<!oral )\bsuspensions?\b", r"\belixirs?\b",
                    r"oral solution", r"oral jelly", r"(?<!eye )(?<!ear )(?<!nasal )(?<!cough )\bdrops\b",
                    r"(?<!svp )(?<!svp,)(?<!svp ,)\bliquids?\b(?!\s*\(?\s*(inj|amp|vial|&\s*dry|and\s*dry|&\s*lyo))"],
    "dry_syrup": [r"dry\s*syrups?", r"dry suspension", r"powder for (oral )?suspension"],
    "oral_powder": [r"oral\s*p\s?owders?", r"\bsc?h?a?chets?\b", r"\bgranules?\b"],
    "svp_liquid": [r"small volume parenteral", r"\bs\.?v\.?p\b", r"\bampoules?\b", r"\bamp\b", r"\bvials?\b", r"liquid\s*inj",
                   r"\binjectables?\b", r"\binj(ections?)?\b\.?", r"parent?e?ral|parentral|paretenral|parenter al", r"\bffs\b"],
    "svp_dry_powder": [r"dry\s*powder\s*(inj|vial|fill)", r"powder for inject", r"parenteral\s*\(dry\)", r"injections?\s*\(liquid and dry\)",
                       r"\(\s*dry\s*\)", r"dry\s*powder", r"dry\s*inj"],
    "lyophilised": [r"lyoph?il+i?[sz]", r"lyohili[sz]", r"freeze[- ]dried"],
    "lvp": [r"large volume parenteral", r"\blvp\b", r"i\.?v\.? fluids?", r"infusions?\b"],
    "prefilled_syringe": [r"pre-?filled", r"\bpfs\b", r"cartridges?"],
    "ophthalmic": [r"ophthal", r"opthal", r"\beye\b"],
    "otic_nasal": [r"\bear\b", r"\bnasal\b", r"\botic\b"],
    "topical": [r"ointments?", r"creams?", r"\bgels?\b", r"lotions?", r"external\s*prep", r"topical", r"\bpastes?\b", r"dusting powder",
                r"liniments?", r"shampoos?", r"disinfectants?", r"mouth ?wash", r"\bemulsions?\b"],
    "transdermal": [r"transdermal", r"\bpatch(es)?\b"],
    "suppository": [r"suppositor", r"pessar", r"vaginal"],
    "inhalation": [r"inhal", r"aerosol", r"\bmdi\b", r"meter(ed)? dose", r"rotacap", r"respule", r"nebuli[sz]"],
    "api": [r"\bapi'?s?\b", r"bulk\s*drugs?", r"active pharmaceutical ingredient", r"drug substance", r"intermediates?"],
    "finished_unspecified": [r"^\s*formulations?\s*$"],
    "biological": [r"vaccines?", r"\bsera\b", r"biologic", r"monoclonal", r"recombinant", r"insulin", r"blood product", r"r-?dna", r"toxoid",
                   r"immunoglobulin"],
    "medical_device": [r"medical devices?", r"sutures?", r"\bstents?\b", r"catheters?"],
}

# Products that Schedule M requires in dedicated, segregated facilities. A plant with a
# "beta_lactam: [tablet, dry_syrup]" capability runs a separate penicillin block for those forms.
SEGREGATED: dict[str, list[str]] = {
    "beta_lactam": [r"beta\s*-?\s*lact[ua]m", r"β[- ]?lactam", r"\bbeta\b(?!\s*-?\s*(blocker|carotene))", r"penicillin", r"amoxy?cillin",
                    r"ampicillin", r"cloxacillin"],
    "cephalosporin": [r"cephal\w*", r"\bcepha\b", r"\bcef[a-z]{3,}"],
    "carbapenem": [r"carbapenem", r"\bpenems?\b", r"meropenem", r"imipenem", r"ertapenem"],
    "hormone": [r"hormon", r"contracepti", r"oestrogen|estrogen", r"progest", r"testosterone"],
    "steroid": [r"steroid", r"cortico"],
    "cytotoxic": [r"cytotoxic", r"\bonco\w*", r"anti\s*-?\s*cancer", r"anti\s*-?\s*neoplastic", r"chemotherap"],
    "immunosuppressant": [r"immuno\s*-?\s*suppress", r"tacrolimus", r"cyclosporin", r"mycophenol"],
    "potent_other": [r"high(ly)? potent", r"\bhpapi\b"],
}
_NEGATED = re.compile(r"\bnon\s*-?\s*(beta\s*-?\s*lact[ua]m|beta|penicillin|cephalosporins?|hormon\w*|steroid\w*|cytotoxic|onco\w*)\b", re.I)
# a parenthesis that scopes the forms before it: "(General)", "(Betalactam)", "(General & Beta)", "(Cepha)", "(Non beta lactum)"
_MARKER = re.compile(r"general|beta|lact[ua]m|ceph|penem|penicillin|hormon|steroid|cytotoxic|onco|anti\s*-?\s*cancer|non\s*-?\s*beta|category", re.I)
# a heading that scopes everything after it: "General - ...", "Beta Lactum Category ...", "Hormone - Tablets"
_HEADING = re.compile(r"\s(?=(?:general|non\s*-?\s*beta\s*-?\s*lact[ua]m|beta\s*-?\s*lact[ua]m|cephalosporins?|hormon\w*|cytotoxic|oncology|"
                      r"steroid\w*|penems?|carbapenems?)\s*(?:category|section|block|group)?\s*[-:–]|(?:general|beta\s*-?\s*lact[ua]m|"
                      r"cephalosporins?|hormon\w*|cytotoxic|oncology)\s+(?:category|section|block)\b)", re.I)

THERAPEUTIC: dict[str, list[str]] = {
    "antiviral": [r"anti[- ]?viral", r"antiretroviral", r"\barv\b"],
    "antibacterial": [r"anti[- ]?bacterial", r"antibiotic", r"anti[- ]?infective"],
    "antifungal": [r"anti[- ]?fungal"],
    "antimalarial": [r"anti[- ]?malarial"],
    "anti_tb": [r"anti[- ]?tb", r"anti[- ]?tubercul"],
    "antidiabetic": [r"anti[- ]?diabet"],
    "cardiovascular": [r"cardio", r"anti[- ]?hypertens", r"anti[- ]?coagul"],
    "cns": [r"\bcns\b", r"psychotrop", r"anti[- ]?epilep", r"anti[- ]?depress", r"narcotic", r"schedule x"],
    "vitamins_nutrition": [r"vitamin", r"nutraceutical", r"food supplement", r"minerals?"],
    "ayush": [r"ayurved", r"homoeopath", r"unani", r"siddha", r"herbal"],
    "veterinary": [r"veterinary", r"\bvet\b"],
    "cosmetic": [r"cosmetic"],
}

STERILE = {"svp_liquid", "svp_dry_powder", "lyophilised", "lvp", "prefilled_syringe", "ophthalmic"}

# Drugs and Cosmetics Rules, 1945 licence forms (as printed in SUGAM).
LICENCE_FORMS = {
    "25": ("manufacture", "Drugs other than Schedule C, C(1) and X"),
    "25A": ("loan_licence", "Loan licence: drugs other than Schedule C, C(1) and X"),
    "25B": ("repacking", "Repacking of drugs"),
    "25C": ("homoeopathic", "Homoeopathic medicines"),
    "25D": ("ayush", "Ayurvedic / Siddha / Unani drugs"),
    "25F": ("schedule_x", "Schedule X drugs"),
    "28": ("schedule_c", "Schedule C and C(1) drugs: biologicals, sera, parenterals, ophthalmics"),
    "28A": ("loan_licence_schedule_c", "Loan licence: Schedule C and C(1) drugs"),
    "28B": ("schedule_x_loan", "Loan licence: Schedule X drugs"),
    "28C": ("blood_products", "Blood products"),
    "28D": ("lvp_sera_vaccines", "Large volume parenterals, sera and vaccines"),
    "29": ("test_analysis", "Manufacture for examination, test or analysis"),
    "32": ("cosmetics", "Cosmetics"),
}

STATES = ["Andaman & Nicobar Island", "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
          "Chandigarh", "Chhattisgarh", "Dadra & Nagar Haveli", "Dadra and Nagar Haveli", "Daman & Diu", "Daman and Diu", "Delhi",
          "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jammu & Kashmir", "Jammu and Kashmir", "Jharkhand", "Karnataka",
          "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
          "Odisha", "Orissa", "Pondicherry", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
          "Uttar Pradesh", "Uttarakhand", "Uttaranchal", "West Bengal"]
_STATE_CANON = {"orissa": "Odisha", "pondicherry": "Puducherry", "uttaranchal": "Uttarakhand",
                "andaman & nicobar island": "Andaman and Nicobar Islands", "dadra & nagar haveli": "Dadra and Nagar Haveli",
                "daman & diu": "Daman and Diu", "jammu & kashmir": "Jammu and Kashmir"}
_STATE_RE = re.compile(r"\b(" + "|".join(re.escape(s) for s in sorted(STATES, key=len, reverse=True)) + r")\b", re.I)


def canon_state(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    low = s.lower()
    if low in _STATE_CANON:
        return _STATE_CANON[low]
    for st in STATES:
        if st.lower() == low:
            return _STATE_CANON.get(low, st)
    return None


# --------------------------------------------------------------------------- text helpers

_PIN = re.compile(r"(?<!\d)(?<!\d-)([1-8]\d{2})\s?-?\s?(\d{3})(?![\d-])")
_DATE = r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})"
_ISSUE = re.compile(r"(?:date of issue|issued on|issue date|doi)\s*[:\-]?\s*" + _DATE, re.I)
_VALID = re.compile(r"(?:valid\s*(?:up\s*to|upto|till|until)|validity|expiry|expires on)\s*[:\-]?\s*" + _DATE, re.I)
_SUFFIX = re.compile(r"\b(private|pvt|limited|ltd|llp|inc|corporation|corp|co|company|india|m/s|messrs)\b\.?", re.I)
_UNIT = re.compile(r"\bunit\s*[-–:]?\s*([ivx]+|\d+|[a-z])\b", re.I)
_COMPANY_WORD = re.compile(r"\b(?:limited|ltd|llp|pvt|private|inc|corporation|laborator(?:y|ies)|labs?|pharmaceuticals?|pharma|healthcare|"
                           r"lifesciences?|life sciences|remedies|formulations|drugs|biotech?|biologicals?|organics|chemicals?|"
                           r"industries|parenterals|therapeutics)\b\.?(?:\s*\((?:unit[^)]*)\))?", re.I)


def clean(s: Any) -> str:
    s = html.unescape(str(s or "")).replace(" ", " ")
    s = re.sub(r"\s*-\s*\n\s*", "-", s)          # "Unit\n-\nII" -> "Unit-II"
    s = re.sub(r"\s+", " ", s).strip()
    return s.replace("Soild", "Solid").replace("Preprations", "Preparations").replace("Preparatoin", "Preparation")


def find_pin(text: str) -> Optional[str]:
    """Last 6-digit Indian PIN in an address ('781 125', '380-060' and '380060' all count)."""
    hits = [a + b for a, b in _PIN.findall(text or "")]
    # phone numbers are longer runs of digits and are excluded by the look-arounds
    return hits[-1] if hits else None


def unit_of(name: str) -> Optional[str]:
    m = _UNIT.search(name or "")
    if not m:
        return None
    u = m.group(1).upper()
    roman = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12}
    return str(roman.get(u, u))


def name_key(name: str) -> str:
    """Company identity for matching: lower-case, no M/s / Ltd / Pvt / punctuation, unit number kept."""
    n = (name or "").lower()
    n = re.sub(r"\(.*?\)", " ", n)
    n = _UNIT.sub(" ", n)
    n = _SUFFIX.sub(" ", n)
    n = re.sub(r"[^a-z0-9]+", " ", n).strip()
    n = re.sub(r"\b(the|and|&)\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    u = unit_of(name)
    return f"{n}#u{u}" if u else n


def split_name_address(text: str) -> tuple[str, str]:
    """'M/s X Pharma Ltd (Unit-II) Plot 4, GIDC...' -> ('X Pharma Ltd (Unit-II)', 'Plot 4, GIDC...').

    The name ends at the last company word (Ltd, Pharma, Laboratories...) before the first comma;
    a 'Unit-N' right after the name stays with the name (it identifies the plant).
    """
    t = re.sub(r"^\s*(m/s\.?|messrs\.?)\s*", "", clean(text), flags=re.I)
    head = t.split(",", 1)[0]
    ends = [m.end() for m in _COMPANY_WORD.finditer(head)]
    cut = ends[-1] if ends and ends[-1] <= 120 else len(head)
    name, rest = t[:cut].strip(" ,.-"), t[cut:].strip(" ,.-")
    m = re.match(r"^[,\s-]*(\(?unit\s*[-–:]?\s*(?:[ivx]+|\d+)\)?)[,\s]*", rest, flags=re.I)
    if m:
        name, rest = f"{name} {m.group(1)}", rest[m.end():]
    return name, rest.strip(" ,.-")


def _hits(text: str, vocab: dict[str, list[str]]) -> list[str]:
    return [k for k, pats in vocab.items() if any(re.search(p, text) for p in pats)]


def parse_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    m = re.match(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})$", s.strip())
    if m:
        d, mo, y = (int(x) for x in m.groups())
        y += 2000 if y < 100 else 0
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})$", s.strip())
    if m:
        mons = "jan feb mar apr may jun jul aug sep oct nov dec".split()
        mo = m.group(2).lower()
        if mo in mons:
            return f"{int(m.group(3)):04d}-{mons.index(mo) + 1:02d}-{int(m.group(1)):02d}"
    return None


def _blocks(text: str) -> list[str]:
    """Split a category cell into certificates / blocks: '1. ... 2. ...' and 'General - ... Beta lactam - ...'."""
    t = clean(text)
    parts = re.split(r"(?:^|\s)(?=\(?\d{1,2}[.)]\s+[A-Za-z(])", t)
    out: list[str] = []
    for p in parts:
        out.extend(x for x in _HEADING.split(p) if x and x.strip())
    return [re.sub(r"^\(?\d{1,2}[.)]\s*", "", b).strip(" ,;&") for b in out if b.strip(" ,;&")] or ([t] if t else [])


def _segments(block: str) -> list[tuple[str, Optional[str]]]:
    """Pieces of a block, each with the parenthesised marker that scopes it (if any).

    'Tablets (General, Betalactam & Oncology), Oral Sachet, Capsules (Hard Gelatin)'
      -> [('Tablets', 'General, Betalactam & Oncology'), (', Oral Sachet, Capsules (Hard Gelatin)', None)]
    """
    segs: list[tuple[str, Optional[str]]] = []
    pos = 0
    for m in re.finditer(r"\(([^()]*)\)", block):
        if _MARKER.search(m.group(1)):
            segs.append((block[pos:m.start()], m.group(1)))
            pos = m.end()
    segs.append((block[pos:], None))
    segs = [(t, mk) for t, mk in segs if t.strip(" ,;&/-") or mk]
    # Item-by-item style ("Tablets (General & Ceph), Capsules (General & Ceph), Dry Syrups (...)"): each
    # marker covers only the item right before it, so the first one must not swallow the whole list.
    marked = [t for t, mk in segs if mk is not None]
    if len(marked) >= 3 and all(len(_hits(t.lower(), DOSAGE_FORMS)) == 1 for t in marked[1:4]) and len(_hits(marked[0].lower(), DOSAGE_FORMS)) > 1:
        t0, mk0 = segs[0]
        cut = max(t0.rfind(","), t0.rfind("&"), t0.rfind(" and "))
        if cut > 0:
            segs = [(t0[:cut], None), (t0[cut + 1:], mk0)] + segs[1:]
    return segs


def _seg_classes(text: str) -> list[str]:
    return _hits(_NEGATED.sub(" general ", text.lower()), SEGREGATED)


def _forms(text: str) -> list[str]:
    low = text.lower()
    forms = _hits(low, DOSAGE_FORMS)
    # what is inside "External Preparation (Liquid & Powder)" or "Inhalation (Solution & Suspension)" is not an oral form
    stripped = re.sub(r"(external\s*prep\w*|inhal\w*(\s+formulations?)?|ophthal\w*|opthal\w*|nasal\w*|parent?e?ral\w*|svp)\s*[(\[][^)\]]*[)\]]",
                      r"\1", low)
    for k in ("oral_liquid", "oral_powder", "dry_syrup"):
        if k in forms and not _hits(stripped, {k: DOSAGE_FORMS[k]}):
            forms.remove(k)
    if "oral_liquid" in forms and "dry_syrup" in forms:
        rest = re.sub(r"dry\s*syrups?|dry suspension|powder for (oral )?suspension", " ", stripped)
        if not _hits(rest, {"oral_liquid": DOSAGE_FORMS["oral_liquid"]}):
            forms.remove("oral_liquid")
    dry_or_lyo = {"svp_dry_powder", "lyophilised", "lvp", "prefilled_syringe"} & set(forms)
    if "svp_liquid" in forms and dry_or_lyo and not re.search(r"liquid|ampoule|\bamp\b|injectables?\b|\bs\.?v\.?p\b(?!\s*\(\s*(dry|lyo))|"
                                                             r"small volume parenteral(?!\s*\(\s*(dry|lyo))|parenteral\s*\[", low):
        forms.remove("svp_liquid")
    if "svp_dry_powder" in forms and not re.search(r"inj|parent|paretenral|\bs\.?v\.?p\b|vial|ampoule|steril", low):
        forms.remove("svp_dry_powder")  # "Dry powder" with no injectable context is an oral / topical powder
        if not ({"inhalation", "topical"} & set(forms)):
            forms.append("oral_powder")
    return forms


def parse_capabilities(text: str, *, source: str, ref: Optional[str] = None) -> dict[str, Any]:
    """Free-text category -> structured capabilities, each with the text it came from.

    Segregated classes are scoped: a heading ('Beta lactam - Tablets, Dry Syrup') covers the
    forms after it, a parenthesis ('Tablets (Cephalosporin)') covers the forms before it, and
    'Non beta lactam' / '(General)' mean the general block.
    """
    dosage: set[str] = set()
    segregated: dict[str, set[str]] = defaultdict(set)
    therapeutic: set[str] = set()
    evidence: list[dict[str, Any]] = []
    for block in _blocks(text):
        low = block.lower()
        first_form = min((m.start() for pats in DOSAGE_FORMS.values() for p in pats for m in [re.search(p, low)] if m), default=len(low))
        heading = low[:first_form]
        heading_seg = _seg_classes(heading)
        issued = _ISSUE.search(block)
        valid = _VALID.search(block)
        for seg_text, marker in _segments(block):
            forms = _forms(seg_text)
            if marker is not None:
                seg = _seg_classes(marker)
            elif heading_seg:
                seg = heading_seg
            else:
                seg = _seg_classes(seg_text)
            if not forms and not seg and not marker:
                continue
            dosage.update(forms)
            for s in seg:
                segregated[s].update(forms or ["unspecified"])
            ther = _hits(seg_text.lower() + " " + (marker or "").lower(), THERAPEUTIC)
            therapeutic.update(ther)
            evidence.append({"source": source, "ref": ref, "text": (seg_text.strip(" ,;&") + (f" ({marker})" if marker else ""))[:400],
                             "block": block[:400] if block != seg_text else None, "forms": forms, "segregated": seg,
                             "therapeutic": ther, "issued": parse_date(issued.group(1)) if issued else None,
                             "valid_until": parse_date(valid.group(1)) if valid else None})
        # therapeutic classes listed without any dosage form ("Anti-Viral, Anti-Diabetic...")
        therapeutic.update(_hits(low, THERAPEUTIC))
        if not any(e.get("block") == block[:400] or e["text"] and e["text"] in block for e in evidence):
            evidence.append({"source": source, "ref": ref, "text": block[:400], "block": None, "forms": [], "segregated": heading_seg,
                             "therapeutic": _hits(low, THERAPEUTIC), "issued": None, "valid_until": None})
            for s in heading_seg or _seg_classes(low):
                segregated[s].add("unspecified")
    for k, v in segregated.items():
        if len(v) > 1:
            v.discard("unspecified")
    return {
        "dosage_forms": sorted(dosage),
        "segregated": {k: sorted(v) for k, v in sorted(segregated.items())},
        "therapeutic": sorted(therapeutic),
        "sterile": bool(dosage & STERILE),
        "api": "api" in dosage,
        "finished_dose": bool(dosage - {"api", "medical_device"}),
        "evidence": evidence,
        "raw": clean(text),
    }


# --------------------------------------------------------------------------- SUGAM

class _Table(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.hidden: dict[str, str] = {}
        self._row: Optional[list[str]] = None
        self._cell: Optional[list[str]] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        a = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "input" and (a.get("type") or "").lower() == "hidden" and a.get("name"):
            self.hidden[a["name"]] = a.get("value") or ""
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(clean("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


SUGAM_COLS = ["sr", "licence_no", "premise_name", "loan_premise_name", "address", "site_type", "form", "issue_date", "expiry_date"]


def parse_sugam_page(page_html: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    p = _Table()
    p.feed(page_html)
    out = []
    for r in p.rows:
        if len(r) != 9 or not r[0].strip().isdigit():
            continue
        out.append(dict(zip(SUGAM_COLS, r)))
    return out, p.hidden


def parse_sugam_address(addr: str) -> dict[str, Any]:
    """'<street>,<district>,<state>,India,<phone>,<fax>' -> parts (SUGAM's fixed layout)."""
    parts = [x.strip() for x in (addr or "").split(",")]
    out: dict[str, Any] = {"address": clean(addr), "district": None, "state": None, "pin": None}
    try:
        i = max(i for i, x in enumerate(parts) if x.lower() == "india")
    except ValueError:
        m = _STATE_RE.search(addr or "")
        out["state"] = canon_state(m.group(1)) if m else None
        out["pin"] = find_pin(addr)
        return out
    out["state"] = canon_state(parts[i - 1]) if i >= 1 else None
    out["district"] = re.sub(r"\(.*?\)", "", parts[i - 2]).strip() or None if i >= 2 else None
    out["address"] = clean(", ".join(x for x in parts[:i] if x))
    phones = [re.sub(r"\D", "", x) for x in parts[i + 1:]]
    # the PIN is often glued onto the town ("Rudrapur ? 263145"); never take it from the phone fields
    out["pin"] = find_pin(", ".join(parts[:i]))
    out["phones"] = sorted({p for p in phones if len(p) >= 8})
    return out


def sugam_record(r: dict[str, Any]) -> dict[str, Any]:
    form = re.sub(r"(?i)form\s*", "", r.get("form") or "").replace(" ", "").upper()
    kind, desc = LICENCE_FORMS.get(form, ("other", f"Form {form}" if form else "unknown"))
    loan = (r.get("loan_premise_name") or "").strip()
    return {
        "name": clean(r["premise_name"]),
        "loan_licensee": None if loan in ("", "-") else clean(loan),
        "licence": {"number": r["licence_no"], "form": f"Form {form}" if form else None, "kind": kind, "covers": desc,
                    "site_type": (r.get("site_type") or "").strip().title() or None,
                    "issued": parse_date(r.get("issue_date")), "expires": parse_date(r.get("expiry_date"))},
        **parse_sugam_address(r.get("address") or ""),
    }


def crawl_sugam(ctx: Ctx, *, sleep: float = 1.0) -> list[dict[str, Any]]:
    import time

    rows: list[dict[str, Any]] = []
    page, pages = 1, 1
    while page <= pages:
        q = {"srch_pattrn": "", "page_no": page}
        body = http_get(f"{SUGAM_URL}?{urlencode(q)}", timeout=90).decode("utf-8", errors="replace")
        (ctx.raw_dir / f"sugam_p{page:03d}.html").write_text(body, encoding="utf-8")
        got, hidden = parse_sugam_page(body)
        pages = int(hidden.get("num_pages") or pages)
        ctx.log(f"  SUGAM page {page}/{pages}: {len(got)} sites (total on server {hidden.get('num_total_records', '?')})")
        if not got:
            break
        rows.extend(got)
        page += 1
        if ctx.limit and len(rows) >= ctx.limit:
            break
        time.sleep(sleep)
    return rows


# --------------------------------------------------------------------------- WHO-GMP PDF

def _state_heading(row: list[str]) -> Optional[str]:
    vals = [c for c in row if c]
    if len(vals) == 1 and len(vals[0]) < 45:
        return canon_state(vals[0])
    return None


def parse_who_gmp_rows(rows: Iterable[list[Optional[str]]]) -> list[dict[str, Any]]:
    """Table rows (any page order, header rows included) -> one entry per certified unit.

    Expected columns: S.No | Sub Sr. No | Name and address | Category of drugs.
    A row with no serial number and no name continues the previous unit (page breaks).
    """
    units: list[dict[str, Any]] = []
    state: Optional[str] = None
    for raw in rows:
        row = [clean(c) for c in raw if c is not None]
        row = row + [""] * (4 - len(row)) if len(row) < 4 else row
        joined = " ".join(row).lower()
        if not joined.strip() or "name and address" in joined or "category of drugs" in joined or "total no" in joined:
            continue
        st = _state_heading(row)
        if st:
            state = st
            continue
        if len(row) > 4:  # merged / split columns: serials first, category last, the rest is name+address
            row = [row[0], row[1], " ".join(row[2:-1]), row[-1]]
        sno, sub, name_addr, cat = row[:4]
        if not re.match(r"^\d+\.?$", sno or "") and not name_addr and units:
            units[-1]["category"] = clean(units[-1]["category"] + " " + cat)
            continue
        if not re.match(r"^\d+\.?$", sno or "") and units and not re.match(r"^\d+\.?$", sub or ""):
            # continuation that carries both name and category fragments
            units[-1]["name_address"] = clean(units[-1]["name_address"] + " " + name_addr)
            units[-1]["category"] = clean(units[-1]["category"] + " " + cat)
            continue
        units.append({"serial": sno.rstrip("."), "state_serial": (sub or "").rstrip("."), "state": state,
                      "name_address": name_addr, "category": cat})
    return units


def extract_pdf_rows(pdf_path: Path, log=print) -> list[list[Optional[str]]]:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pip install pdfplumber (needed to read CDSCO's WHO-GMP PDF)") from exc
    rows: list[list[Optional[str]]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            items: list[tuple[float, list[list[Optional[str]]]]] = []
            boxes = []
            for tb in page.find_tables({"vertical_strategy": "lines", "horizontal_strategy": "lines"}):
                t = tb.extract()
                boxes.append(tb.bbox)
                # skip the per-state summary table on page 1 (S.No, State, Total)
                if t and t[0] and any("total no" in (c or "").lower() for c in t[0]):
                    continue
                items.append((tb.bbox[1], t))
            # state headings sometimes sit between tables as plain paragraphs
            for line in page.extract_text_lines() if hasattr(page, "extract_text_lines") else []:
                inside = any(b[0] - 1 <= line["x0"] and line["x1"] <= b[2] + 1 and b[1] - 1 <= line["top"] <= b[3] + 1 for b in boxes)
                if not inside and canon_state(line["text"]):
                    items.append((line["top"], [[line["text"]]]))
            for _, t in sorted(items, key=lambda x: x[0]):
                rows.extend(t)
            if i % 25 == 0:
                log(f"  WHO-GMP PDF: page {i}/{len(pdf.pages)}")
        if len(pdf.pages) > 20 and len(rows) < 3 * len(pdf.pages):
            log(f"  WARNING: only {len(rows)} table rows in {len(pdf.pages)} pages — CDSCO may have changed the PDF layout")
    return rows


def who_record(u: dict[str, Any], ref: str) -> dict[str, Any]:
    name, address = split_name_address(u["name_address"])
    st = u.get("state")
    m = _STATE_RE.search(address)
    return {
        "name": name,
        "address": address,
        "state": st or (canon_state(m.group(1)) if m else None),
        "pin": find_pin(address),
        "who_gmp": {"serial": u["serial"], "state_serial": u["state_serial"], "category": u["category"], "list": ref},
        "capabilities": parse_capabilities(u["category"], source="cdsco_who_gmp", ref=ref),
    }


# --------------------------------------------------------------------------- merge

def plant_id(name: str, state: Optional[str], pin: Optional[str], district: Optional[str]) -> str:
    loc = pin or re.sub(r"[^a-z0-9]+", "-", (district or state or "in").lower()).strip("-")
    return f"{re.sub(r'[^a-z0-9]+', '-', name_key(name)).strip('-')}--{loc}"


def _empty_caps() -> dict[str, Any]:
    return {"dosage_forms": [], "segregated": {}, "therapeutic": [], "sterile": False, "api": False,
            "finished_dose": False, "evidence": [], "raw": ""}


def _merge_caps(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    seg = {k: sorted(set(a["segregated"].get(k, [])) | set(b["segregated"].get(k, []))) for k in set(a["segregated"]) | set(b["segregated"])}
    forms = sorted(set(a["dosage_forms"]) | set(b["dosage_forms"]))
    return {"dosage_forms": forms, "segregated": dict(sorted(seg.items())),
            "therapeutic": sorted(set(a["therapeutic"]) | set(b["therapeutic"])),
            "sterile": a["sterile"] or b["sterile"], "api": a["api"] or b["api"],
            "finished_dose": a["finished_dose"] or b["finished_dose"],
            "evidence": a["evidence"] + b["evidence"], "raw": " | ".join(x for x in (a["raw"], b["raw"]) if x)}


def licence_capabilities(lic: dict[str, Any]) -> dict[str, Any]:
    c = _empty_caps()
    kind = lic.get("kind")
    forms = {"schedule_c": ["svp_liquid"], "loan_licence_schedule_c": ["svp_liquid"], "lvp_sera_vaccines": ["lvp", "biological"],
             "blood_products": ["biological"]}.get(kind, [])
    # A Schedule C licence says "may make parenterals / biologicals / ophthalmics"; it does not say which.
    c["licence_classes"] = [kind] if kind else []
    c["schedule_c"] = kind in ("schedule_c", "loan_licence_schedule_c", "lvp_sera_vaccines", "blood_products")
    c["sterile"] = c["schedule_c"]
    c["evidence"] = [{"source": "cdsco_sugam", "ref": lic.get("number"), "text": f"{lic.get('form')}: {lic.get('covers')}",
                      "forms": forms, "segregated": [], "therapeutic": [], "issued": lic.get("issued"), "valid_until": lic.get("expires")}]
    return c


def build_registry(sugam: list[dict[str, Any]], who: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    plants: dict[str, dict[str, Any]] = {}

    def upsert(rec: dict[str, Any], src: str) -> str:
        pid = plant_id(rec["name"], rec.get("state"), rec.get("pin"), rec.get("district"))
        p = plants.get(pid)
        if p is None:
            p = plants[pid] = {"id": pid, "name": rec["name"], "name_key": name_key(rec["name"]), "unit": unit_of(rec["name"]),
                               "aliases": [], "address": rec.get("address"), "district": rec.get("district"),
                               "state": rec.get("state"), "pin": rec.get("pin"), "phones": [], "sources": [],
                               "licences": [], "loan_licensees": [], "who_gmp": [], "capabilities": _empty_caps()}
        if rec["name"] != p["name"] and rec["name"] not in p["aliases"]:
            p["aliases"].append(rec["name"])
        for k in ("address", "district", "state", "pin"):
            if not p.get(k) and rec.get(k):
                p[k] = rec[k]
        p["phones"] = sorted(set(p["phones"]) | set(rec.get("phones") or []))
        if src not in p["sources"]:
            p["sources"].append(src)
        return pid

    for w in who:
        pid = upsert(w, "cdsco_who_gmp")
        plants[pid]["who_gmp"].append(w["who_gmp"])
        plants[pid]["capabilities"] = _merge_caps(plants[pid]["capabilities"], w["capabilities"])

    # SUGAM rows mostly lack a PIN: attach them to a WHO-GMP plant with the same company
    # identity in the same state when that is unambiguous, otherwise keep them as their own plant.
    by_name_state: dict[tuple[str, Optional[str]], list[str]] = defaultdict(list)
    for pid, p in plants.items():
        by_name_state[(p["name_key"], p["state"])].append(pid)
    matched = 0
    for s in sugam:
        cands = by_name_state.get((name_key(s["name"]), s.get("state")), [])
        if s.get("pin"):
            cands = [c for c in cands if plants[c]["pin"] in (None, s["pin"])]
        if len(cands) == 1:
            pid = cands[0]
            matched += 1
            p = plants[pid]
            if "cdsco_sugam" not in p["sources"]:
                p["sources"].append("cdsco_sugam")
            for k in ("district", "pin"):
                p[k] = p.get(k) or s.get(k)
            p["phones"] = sorted(set(p["phones"]) | set(s.get("phones") or []))
        else:
            pid = upsert(s, "cdsco_sugam")
            by_name_state[(plants[pid]["name_key"], plants[pid]["state"])].append(pid)
        p = plants[pid]
        if (s["licence"]["number"], s["licence"]["form"]) not in {(x["number"], x["form"]) for x in p["licences"]}:
            p["licences"].append(s["licence"])
            lc = licence_capabilities(s["licence"])
            caps = _merge_caps(p["capabilities"], lc)
            caps["licence_classes"] = sorted(set(p["capabilities"].get("licence_classes", [])) | set(lc["licence_classes"]))
            caps["schedule_c"] = p["capabilities"].get("schedule_c", False) or lc["schedule_c"]
            p["capabilities"] = caps
        if s.get("loan_licensee") and s["loan_licensee"] not in p["loan_licensees"]:
            p["loan_licensees"].append(s["loan_licensee"])

    for p in plants.values():
        c = p["capabilities"]
        c.setdefault("licence_classes", [])
        c.setdefault("schedule_c", False)
        p["who_gmp_certified"] = bool(p["who_gmp"])
        valid = [e["valid_until"] for e in c["evidence"] if e.get("valid_until")]
        p["who_gmp_valid_until"] = max(valid) if valid else None
        p["tags"] = sorted(set(c["dosage_forms"]) | {f"segregated:{k}" for k in c["segregated"]}
                           | ({"sterile"} if c["sterile"] else set()) | ({"who_gmp"} if p["who_gmp_certified"] else set())
                           | ({"schedule_c"} if c["schedule_c"] else set()) | ({"loan_licence_host"} if p["loan_licensees"] else set()))

    stats = {
        "plants": len(plants),
        "who_gmp_units": len(who),
        "sugam_sites": len(sugam),
        "sugam_matched_to_who_gmp": matched,
        "with_pin": sum(1 for p in plants.values() if p["pin"]),
        "with_capabilities": sum(1 for p in plants.values() if p["capabilities"]["dosage_forms"]),
        "no_capability_parsed": sorted(p["id"] for p in plants.values() if p["who_gmp"] and not p["capabilities"]["dosage_forms"])[:50],
        "by_state": dict(Counter(p["state"] or "unknown" for p in plants.values()).most_common()),
        "by_capability": dict(Counter(t for p in plants.values() for t in p["tags"]).most_common()),
    }
    return plants, stats


def write_csv(path: Path, plants: dict[str, dict[str, Any]]) -> None:
    cols = ["id", "name", "state", "district", "pin", "who_gmp_certified", "who_gmp_valid_until", "sterile", "api",
            "dosage_forms", "segregated", "therapeutic", "licence_forms", "loan_licensees", "sources", "address", "category_raw"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in sorted(plants.values(), key=lambda x: (x["state"] or "", x["name"])):
            c = p["capabilities"]
            w.writerow([p["id"], p["name"], p["state"], p["district"], p["pin"], p["who_gmp_certified"], p["who_gmp_valid_until"],
                        c["sterile"], c["api"], "; ".join(c["dosage_forms"]),
                        "; ".join(f"{k}: {', '.join(v)}" for k, v in c["segregated"].items()), "; ".join(c["therapeutic"]),
                        "; ".join(sorted({l["form"] or "" for l in p["licences"]})), "; ".join(p["loan_licensees"]),
                        "; ".join(p["sources"]), p["address"], c["raw"][:1000]])


# --------------------------------------------------------------------------- run

def _download_pdf(ctx: Ctx) -> tuple[Path, str]:
    urls = [u for u in ([ctx.options.get("who_url")] + WHO_GMP_URLS) if u]
    errors = []
    for u in urls:
        try:
            body = http_get(u, timeout=300, accept="application/pdf")
        except Exception as exc:
            errors.append(f"{u}: {exc}")
            ctx.log(f"  WHO-GMP list not downloaded from {u}: {exc}")
            continue
        if not body.startswith(b"%PDF"):
            errors.append(f"{u}: not a PDF ({len(body)} bytes)")
            continue
        p = ctx.raw_dir / "who_gmp.pdf"
        p.write_bytes(body)
        return p, u
    raise Unreachable("WHO-GMP list: " + "; ".join(errors[-2:]))


def run(ctx: Ctx) -> int:
    # 1. SUGAM approved sites
    sugam_raw: list[dict[str, Any]] = []
    if not ctx.options.get("skip_sugam"):
        try:
            sugam_raw = crawl_sugam(ctx, sleep=float(ctx.options.get("sleep", 1.0)))
        except Unreachable as exc:
            ctx.log(f"  SUGAM unreachable ({exc}); continuing with the WHO-GMP list only")
    sugam = [sugam_record(r) for r in sugam_raw]

    # 2. WHO-GMP certified units (PDF)
    if ctx.from_file:
        pdf, ref = ctx.from_file, ctx.from_file.name
    else:
        try:
            pdf, ref = _download_pdf(ctx)
        except Unreachable:
            if not sugam:
                raise
            pdf, ref = None, None
    who: list[dict[str, Any]] = []
    if pdf:
        units = parse_who_gmp_rows(extract_pdf_rows(pdf, ctx.log))
        who = [who_record(u, ref) for u in units if u["name_address"]]
        ctx.log(f"  WHO-GMP list: {len(who)} certified units")

    plants, stats = build_registry(sugam, who)
    ctx.log(f"  registry: {stats['plants']} plants, {stats['with_capabilities']} with parsed capabilities, "
            f"{stats['with_pin']} with a PIN, {stats['sugam_matched_to_who_gmp']} SUGAM sites matched to WHO-GMP units")
    ctx.log("  capabilities: " + ", ".join(f"{k} {v}" for k, v in list(stats["by_capability"].items())[:18]))
    write_csv(ctx.out_path.with_suffix(".csv"), plants)
    write_normalized(ctx, META, plants, len(plants),
                     extra={"inputs": {"sugam": SUGAM_URL if sugam else None, "who_gmp": ref}, "stats": stats, "vocabulary": {"dosage_forms": list(DOSAGE_FORMS), "segregated": list(SEGREGATED),
                                                           "therapeutic": list(THERAPEUTIC),
                                                           "licence_forms": {f"Form {k}": v[1] for k, v in LICENCE_FORMS.items()}}})
    return len(plants)


def main() -> None:  # standalone: python -m sources.cdsco_plants [pdf]
    import sys

    ctx = Ctx(name="cdsco_plants", from_file=Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print(json.dumps({"plants": run(ctx)}))


if __name__ == "__main__":
    main()

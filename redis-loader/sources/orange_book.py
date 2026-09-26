"""FDA Orange Book (Approved Drug Products with Therapeutic Equivalence Evaluations).

Download: the monthly data-files zip (products.txt, patent.txt, exclusivity.txt,
tilde-delimited). Normalised per active ingredient (single-ingredient products
only for patents/exclusivity, combinations counted separately):

  key -> {names, rld{trade_name, applicant, dosage_form, route, strength, appl_no, approval},
          nda_count, anda_count, anda_active, anda_holders, indian_anda_holders,
          te_codes{code: n}, patents[{no, expires, substance, product, use_code}],
          exclusivity[{code, expires}], first_generic_approval, last_patent_expiry,
          last_exclusivity_expiry, combo_products, dosage_forms}
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import Ctx, download, write_normalized

META = {
    "title": "FDA Orange Book",
    "publisher": "U.S. Food and Drug Administration",
    "url": "https://www.fda.gov/media/76860/download",
    "page": "https://www.fda.gov/drugs/drug-approvals-and-databases/orange-book-data-files",
    "cadence": "monthly (FDA updates the data files monthly; patents daily in the web app)",
    "feeds": ["US LOE (patents + exclusivity)", "RLD / TE code", "ANDA competitors", "FTO risk"],
}

# Indian generic companies, matched as substrings of the Orange Book applicant
# full name (lower-case). Used only for the "Indian ANDA holders" count.
INDIAN_GENERICS = (
    "sun pharma", "dr reddys", "dr. reddy", "cipla", "lupin", "aurobindo", "zydus", "cadila", "glenmark",
    "torrent", "alembic", "alkem", "ajanta", "macleods", "unichem", "granules", "strides", "msn lab",
    "hetero", "natco", "biocon", "jubilant", "wockhardt", "ipca", "indoco", "micro labs", "intas",
    "accord healthcare", "emcure", "mankind", "gland pharma", "shilpa", "laurus", "divis", "piramal",
    "caplin", "marksans", "indchemie", "annora", "umedica", "novadoz", "senores", "biological e",
    "bharat serums", "cadista", "jubilant", "aurolife", "eugia", "camber", "ascend", "solco",
)


def _date(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if s.lower().startswith("approved prior to"):
        return "1982-01-01"
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d,%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _rows(zf: zipfile.ZipFile, stem: str) -> list[dict[str, str]]:
    name = next((n for n in zf.namelist() if Path(n).stem.lower() == stem), None)
    if not name:
        raise ValueError(f"{stem}.txt not in Orange Book zip ({zf.namelist()})")
    text = zf.read(name).decode("latin-1")
    reader = csv.DictReader(io.StringIO(text), delimiter="~")
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in reader]


def _col(row: dict[str, str], *names: str) -> str:
    for n in names:
        if n in row:
            return row[n]
    low = {k.lower().replace(" ", "_"): v for k, v in row.items()}
    for n in names:
        v = low.get(n.lower().replace(" ", "_"))
        if v is not None:
            return v
    return ""


def parse_zip(path: Path) -> dict[str, dict[str, Any]]:
    import ingredients as ing  # core/

    with zipfile.ZipFile(path) as zf:
        products = _rows(zf, "products")
        patents = _rows(zf, "patent")
        excl = _rows(zf, "exclusivity")

    by_key: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "names": set(), "nda": [], "anda": {}, "te": Counter(), "patents": {}, "exclusivity": {},
        "combo_products": 0, "forms": Counter(), "prod_keys": set(),
    })
    prod_to_key: dict[tuple[str, str, str], str] = {}

    for r in products:
        ingr = _col(r, "Ingredient")
        parts = [p.strip() for p in ingr.split(";") if p.strip()]
        appl_type = _col(r, "Appl_Type")
        appl_no = _col(r, "Appl_No")
        prod_no = _col(r, "Product_No")
        typ = _col(r, "Type").upper()  # RX | OTC | DISCN
        df_route = _col(r, "DF;Route", "DF_Route")
        form = df_route.split(";")[0].strip().lower()
        applicant_full = _col(r, "Applicant_Full_Name") or _col(r, "Applicant")
        if len(parts) > 1:
            for p in parts:
                k = ing.ingredient_key(p)
                if k:
                    by_key[k]["combo_products"] += 1
                    by_key[k]["names"].add(p)
            continue
        k = ing.ingredient_key(parts[0]) if parts else ""
        if not k:
            continue
        e = by_key[k]
        e["names"].add(parts[0])
        if typ != "DISCN":
            e["forms"][form] += 1
        if appl_type == "N":
            prod_to_key[(appl_type, appl_no, prod_no)] = k
            e["nda"].append({
                "appl_no": appl_no, "product_no": prod_no, "trade_name": _col(r, "Trade_Name"),
                "applicant": applicant_full, "dosage_form": form, "route": df_route.split(";")[-1].strip().lower(),
                "strength": _col(r, "Strength"), "approval": _date(_col(r, "Approval_Date")),
                "rld": _col(r, "RLD").lower() == "yes", "rs": _col(r, "RS").lower() == "yes", "type": typ,
                "te_code": _col(r, "TE_Code"),
            })
        elif appl_type == "A":
            a = e["anda"].setdefault(appl_no, {"applicant": applicant_full, "active": False, "approval": ""})
            a["active"] = a["active"] or typ != "DISCN"
            appr = _date(_col(r, "Approval_Date"))
            if appr and (not a["approval"] or appr < a["approval"]):
                a["approval"] = appr
            te = _col(r, "TE_Code")
            if te and typ != "DISCN":
                e["te"][te] += 1

    for r in patents:
        key = prod_to_key.get((_col(r, "Appl_Type"), _col(r, "Appl_No"), _col(r, "Product_No")))
        if not key:
            continue
        no = _col(r, "Patent_No")
        if not no or _col(r, "Delist_Flag").upper() == "Y":
            continue
        p = by_key[key]["patents"].setdefault(no, {"no": no, "expires": "", "substance": False, "product": False, "use_codes": set()})
        exp = _date(_col(r, "Patent_Expire_Date_Text", "Patent_Expire_Date"))
        if exp > p["expires"]:
            p["expires"] = exp
        p["substance"] |= _col(r, "Drug_Substance_Flag").upper() == "Y"
        p["product"] |= _col(r, "Drug_Product_Flag").upper() == "Y"
        uc = _col(r, "Patent_Use_Code")
        if uc:
            p["use_codes"].add(uc)

    for r in excl:
        key = prod_to_key.get((_col(r, "Appl_Type"), _col(r, "Appl_No"), _col(r, "Product_No")))
        if not key:
            continue
        code = _col(r, "Exclusivity_Code")
        exp = _date(_col(r, "Exclusivity_Date"))
        if code and exp:
            cur = by_key[key]["exclusivity"].get(code, "")
            if exp > cur:
                by_key[key]["exclusivity"][code] = exp

    out: dict[str, dict[str, Any]] = {}
    for k, e in by_key.items():
        ndas = e["nda"]
        if not ndas and not e["anda"]:
            # combination-only ingredient
            out[k] = {"names": sorted(e["names"]), "combo_products": e["combo_products"], "combination_only": True}
            continue
        rld = next((n for n in ndas if n["rld"] and n["type"] != "DISCN"), None) or next((n for n in ndas if n["rld"]), None) \
            or (ndas[0] if ndas else None)
        andas = e["anda"]
        active = {no: a for no, a in andas.items() if a["active"]}
        holders = sorted({a["applicant"] for a in active.values() if a["applicant"]})
        indian = sorted({h for h in holders if any(s in h.lower() for s in INDIAN_GENERICS)})
        first_generic = min((a["approval"] for a in andas.values() if a["approval"]), default="")
        pats = sorted(
            ({**p, "use_codes": sorted(p["use_codes"])} for p in e["patents"].values()),
            key=lambda p: p["expires"],
        )
        excls = sorted(({"code": c, "expires": d} for c, d in e["exclusivity"].items()), key=lambda x: x["expires"])
        out[k] = {
            "names": sorted(e["names"]),
            "rld": {kk: rld[kk] for kk in ("trade_name", "applicant", "dosage_form", "route", "strength", "appl_no", "approval")} if rld else None,
            "brands": sorted({n["trade_name"] for n in ndas if n["trade_name"]})[:8],
            "nda_count": len({n["appl_no"] for n in ndas}),
            "nda_active": len({n["appl_no"] for n in ndas if n["type"] != "DISCN"}),
            "anda_count": len(andas),
            "anda_active": len(active),
            "anda_holders": holders[:40],
            "indian_anda_holders": indian,
            "te_codes": dict(e["te"].most_common(6)),
            "patents": pats,
            "exclusivity": excls,
            "first_generic_approval": first_generic,
            "last_patent_expiry": max((p["expires"] for p in pats), default=""),
            "last_substance_patent_expiry": max((p["expires"] for p in pats if p["substance"]), default=""),
            "last_exclusivity_expiry": max((x["expires"] for x in excls), default=""),
            "combo_products": e["combo_products"],
            "dosage_forms": [f for f, _ in e["forms"].most_common(6)],
        }
    return out


def run(ctx: Ctx) -> int:
    path = ctx.from_file or download(ctx, META["url"], "orange_book.zip")
    data = parse_zip(path)
    single = sum(1 for v in data.values() if not v.get("combination_only"))
    write_normalized(ctx, META, data, len(data), extra={"single_ingredient": single})
    return len(data)

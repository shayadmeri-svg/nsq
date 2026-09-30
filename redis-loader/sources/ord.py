"""Open Reaction Database — how tracked molecules are made.

Scans every ORD dataset (Parquet, from the Hugging Face mirror of github.com/open-reaction-database/ord-data;
~1.3 GB, of which USPTO granted-patent reactions are 1.8 M) for reactions whose product is a tracked molecule
(matched on the RDKit canonical SMILES of the largest fragment, stereo ignored, so salts and racemates meet).
For each molecule it keeps the conditions and what they demand of an API plant:

  hydrogenation (H2, Pd/C, Raney Ni…), cryogenic (≤ −20 °C), high temperature (≥ 150 °C), pressure (> 2 bar),
  organometallics (BuLi, LDA, Grignard), hazardous reagents (azide, cyanide, phosgene, hydrazine, hydrides,
  peroxides, diazomethane), palladium coupling, chlorinated solvents

plus solvents, catalysts, temperatures, yields and the patents / papers the reactions come from.

Targets: data/structures_seed.json, data/sources/pubchem.json, data/generated/structures_live.json.
Licence: ORD data CC BY-SA 4.0 (attribution: the Open Reaction Database and each dataset's authors).
"""

from __future__ import annotations

import json
import re
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional

from .common import Ctx, NotFound, Unreachable, data_dir, download, http_get, write_normalized

HF = "https://huggingface.co/datasets/open-reaction-database/ord-data"
META = {
    "title": "Open Reaction Database",
    "publisher": "Open Reaction Database project (CC BY-SA 4.0)",
    "url": HF,
    "page": "https://open-reaction-database.org",
    "cadence": "datasets added a few times a year; refreshed monthly here",
    "feeds": ["Molecule workbench · How it's made", "API process needs (hydrogenation, cryogenic…)"],
}

NEEDS = {
    "hydrogenation": "Hydrogenation (H₂ under pressure, Pd/C, Raney Ni)",
    "cryogenic": "Cryogenic reaction (≤ −20 °C)",
    "high_temperature": "High temperature (≥ 150 °C)",
    "pressure": "Pressure vessel (> 2 bar)",
    "organometallic": "Organometallics (BuLi, LDA, Grignard) — dry, inert",
    "hazardous": "Hazardous reagents (azide, cyanide, phosgene, hydrazine, hydrides…)",
    "pd_coupling": "Palladium coupling (metal residue control)",
    "chlorinated_solvent": "Chlorinated solvents (DCM, chloroform)",
}

SOLVENTS = {
    "C1CCOC1": "THF", "CN(C)C=O": "DMF", "ClCCl": "Dichloromethane", "CO": "Methanol", "CCO": "Ethanol", "Cc1ccccc1": "Toluene",
    "CCOC(C)=O": "Ethyl acetate", "CC#N": "Acetonitrile", "CS(C)=O": "DMSO", "O": "Water", "CC(C)=O": "Acetone", "CC(C)O": "Isopropanol",
    "C1COCCO1": "1,4-Dioxane", "CN1CCCC1=O": "NMP", "CC(=O)N(C)C": "DMAc", "CCCCCC": "Hexane", "ClC(Cl)Cl": "Chloroform",
    "CCOCC": "Diethyl ether", "COCCOC": "DME", "c1ccccc1": "Benzene", "CC(=O)O": "Acetic acid", "ClCCCl": "1,2-Dichloroethane",
    "CCCCO": "n-Butanol", "Cc1ccccc1C": "Xylene", "C1CCCCC1": "Cyclohexane", "CC(C)(C)OC": "MTBE", "c1ccncc1": "Pyridine",
    "CCN(CC)CC": "Triethylamine", "CC1CCCO1": "2-MeTHF",
}
# (label, SMILES pattern — case-sensitive, on reagent SMILES only, name / text pattern — case-insensitive, whole words)
_HAZ = [("azide", r"N=\[N\+\]=\[N-\]|\[N-\]=\[N\+\]=N", r"\bazide\b"),
        ("cyanide", r"\[C-\]#N|C#N\.\[(Na|K)\+\]|\[(Na|K)\+\]\.\[C-\]#N", r"\b(sodium|potassium|zinc|copper\(?i?\)?|trimethylsilyl) cyanide\b|\bhcn\b"),
        ("phosgene", r"^ClC\(=O\)Cl$|ClC\(Cl\)\(Cl\)OC\(=O\)OC\(Cl\)\(Cl\)Cl", r"\b(tri|di)?phosgene\b"),
        ("hydrazine", r"^NN$|^NN\.O$", r"\bhydrazine( hydrate)?\b"),
        ("LiAlH4", r"\[AlH4-\]|\[AlH4\]", r"\blithium alumin(i)?um hydride\b|\blialh4\b"),
        ("NaH", r"^\[NaH\]$|^\[H-\]\.\[Na\+\]$", r"\bsodium hydride\b"),
        ("peroxide", r"^OO$|C\(=O\)OO|OOC\(C\)\(C\)C", r"\bhydrogen peroxide\b|\bperoxide\b|\bm-?cpba\b|\bperacetic\b"),
        ("diazomethane", r"^C=\[N\+\]=\[N-\]$", r"\bdiazomethane\b")]
_ORGANOMET = re.compile(r"\[Li\]C|C\[Li\]|\[Li\+\]\.\[CH2-\]|butyllithium|lithium diisopropylamide|\bLDA\b|\[Mg\]|magnesium bromide|magnesium chloride|grignard", re.I)
_ATOM = re.compile(r"Cl|Br|\[[^\]]+\]|[BCNOSPFI]|[cnosp]")


def heavy_atoms(smiles: str) -> int:
    return max((len(_ATOM.findall(f)) for f in (smiles or "").split(".")), default=0)


def signature(smiles: str) -> tuple:
    """Cheap element signature of the largest fragment (heavy atoms, N, O, S, halogens) — filters before RDKit."""
    frag = max((smiles or "").split("."), key=lambda f: len(_ATOM.findall(f)), default="")
    atoms = [re.sub(r"[\[\]@+\-\dH:]", "", a).lower() or a for a in _ATOM.findall(frag)]
    c = Counter(atoms)
    return (len(atoms), c["n"], c["o"], c["s"], c["cl"] + c["br"] + c["f"] + c["i"])


def _canon(smiles: str) -> Optional[str]:
    """Canonical SMILES of the largest fragment, without stereo."""
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")
    m = Chem.MolFromSmiles(smiles or "")
    if m is None:
        return None
    frags = Chem.GetMolFrags(m, asMols=True, sanitizeFrags=False)
    big = max(frags, key=lambda f: f.GetNumHeavyAtoms()) if frags else m
    try:
        from rdkit.Chem.MolStandardize import rdMolStandardize

        big = rdMolStandardize.Uncharger().uncharge(big)  # sodium phenolate / hydrochloride forms meet the neutral molecule
        return Chem.MolToSmiles(big, isomericSmiles=False)
    except Exception:
        return None


def load_targets() -> dict[str, dict[str, Any]]:
    """canonical SMILES -> {key, name, atoms} for every tracked molecule with a structure."""
    d = data_dir()
    seen: dict[str, dict[str, Any]] = {}
    seed = d / "structures_seed.json"
    if seed.exists():
        for k, v in json.loads(seed.read_text(encoding="utf-8")).get("molecules", {}).items():
            seen[k] = {"name": v.get("name") or k, "smiles": v.get("smiles")}
    pc = d / "sources" / "pubchem.json"
    if pc.exists():
        for k, v in (json.loads(pc.read_text(encoding="utf-8")).get("data") or {}).items():
            if v.get("found") and v.get("smiles"):
                seen[k] = {"name": (seen.get(k) or {}).get("name") or (v.get("query") or k).title(), "smiles": v["smiles"]}
    live = d / "generated" / "structures_live.json"
    if live.exists():
        for k, v in json.loads(live.read_text(encoding="utf-8")).items():
            if v.get("smiles") and k not in seen:
                seen[k] = {"name": v.get("name") or k, "smiles": v["smiles"]}
    out: dict[str, dict[str, Any]] = {}
    for k, v in seen.items():
        c = _canon(v["smiles"])
        if c and heavy_atoms(c) >= 5:  # tiny molecules (e.g. salts, gases) would match half the database
            out.setdefault(c, {"keys": [], "name": v["name"], "atoms": heavy_atoms(c), "sig": signature(c)})["keys"].append(k)
    return out


# ------------------------------------------------------------------------------------ one reaction

def _c(t: Any) -> Optional[float]:
    if t is None or not t.HasField("value"):
        return None
    unit = t.DESCRIPTOR.fields_by_name["units"].enum_type.values_by_number[t.units].name
    v = t.value
    return round((v - 32) * 5 / 9, 1) if unit == "FAHRENHEIT" else round(v - 273.15, 1) if unit == "KELVIN" else round(v, 1)


def _bar(p: Any) -> Optional[float]:
    if p is None or not p.HasField("value"):
        return None
    unit = p.DESCRIPTOR.fields_by_name["units"].enum_type.values_by_number[p.units].name
    f = {"BAR": 1, "ATMOSPHERE": 1.01325, "PSI": 0.0689476, "KPSI": 68.9476, "PASCAL": 1e-5, "KILOPASCAL": 0.01, "TORR": 0.00133322,
         "MM_HG": 0.00133322, "MEGAPASCAL": 10}.get(unit)
    return round(p.value * f, 2) if f else None


def _hours(t: Any) -> Optional[float]:
    if t is None or not t.HasField("value"):
        return None
    unit = t.DESCRIPTOR.fields_by_name["units"].enum_type.values_by_number[t.units].name
    return round(t.value * {"DAY": 24, "HOUR": 1, "MINUTE": 1 / 60, "SECOND": 1 / 3600}.get(unit, 1), 2)


def _ident(compound: Any) -> tuple[Optional[str], Optional[str]]:
    smi = name = None
    for i in compound.identifiers:
        t = i.DESCRIPTOR.fields_by_name["type"].enum_type.values_by_number[i.type].name
        if t in ("SMILES", "CXSMILES") and not smi:
            smi = i.value.split(" |")[0]
        elif t == "NAME" and not name:
            name = i.value
    return smi, name


_MOL = {"MOLE": 1.0, "MILLIMOLE": 1e-3, "MICROMOLE": 1e-6, "NANOMOLE": 1e-9}
_ML = {"LITER": 1000.0, "MILLILITER": 1.0, "MICROLITER": 1e-3, "NANOLITER": 1e-6}
_G = {"GRAM": 1.0, "MILLIGRAM": 1e-3, "MICROGRAM": 1e-6, "KILOGRAM": 1e3}


def _amount(c: Any) -> dict[str, float]:
    """The component's recorded amount: mol, g and/or mL (ORD Amount oneof)."""
    out: dict[str, float] = {}
    try:
        kind = c.amount.WhichOneof("kind")
    except Exception:
        return out
    if kind in ("moles", "mass", "volume"):
        q = getattr(c.amount, kind)
        unit = q.DESCRIPTOR.fields_by_name["units"].enum_type.values_by_number[q.units].name
        table, key = {"moles": (_MOL, "mol"), "mass": (_G, "g"), "volume": (_ML, "ml")}[kind]
        if unit in table and q.value > 0:
            out[key] = q.value * table[unit]
    return out


def concentrations(comps: dict[str, list[dict[str, Any]]]) -> Optional[dict[str, Any]]:
    """Starting concentrations (mol/L) of the reactants from the recorded amounts: moles over the total recorded
    liquid volume (solvents and liquid inputs). None when either is missing."""
    vol_ml = sum(x.get("ml", 0.0) for role in comps.values() for x in role)
    if vol_ml <= 0:
        return None
    c = {x["smiles"]: round(x["mol"] / (vol_ml / 1000), 4) for x in comps.get("reactant", []) if x.get("smiles") and x.get("mol")}
    return {"mol_l": c, "volume_ml": round(vol_ml, 3)} if c else None


def product_smiles(rxn: Any) -> list[str]:
    out = []
    for o in rxn.outcomes:
        for p in o.products:
            # high-throughput screens list their internal standard (often caffeine) among the products
            role = p.DESCRIPTOR.fields_by_name["reaction_role"].enum_type.values_by_number[p.reaction_role].name
            if role not in ("PRODUCT", "UNSPECIFIED"):
                continue
            s, _n = _ident(p)
            if s:
                out.append(s)
    if not out:  # some datasets only carry a reaction SMILES
        for i in rxn.identifiers:
            if ">" in i.value:
                out += [x for x in i.value.split(" |")[0].split(">")[-1].split(".") if x]
    return out


def describe(rxn: Any, dataset: str) -> dict[str, Any]:
    """Conditions, components by role and the plant needs of one reaction."""
    comps: dict[str, list[dict[str, Optional[str]]]] = defaultdict(list)
    for key in rxn.inputs:
        for c in rxn.inputs[key].components:
            role = c.DESCRIPTOR.fields_by_name["reaction_role"].enum_type.values_by_number[c.reaction_role].name.lower()
            smi, name = _ident(c)
            comps[role].append({"smiles": smi, "name": name, **_amount(c)})
    cond = rxn.conditions
    temp = _c(cond.temperature.setpoint) if cond.HasField("temperature") and cond.temperature.HasField("setpoint") else None
    tcontrol = cond.temperature.control.DESCRIPTOR.fields_by_name["type"].enum_type.values_by_number[cond.temperature.control.type].name \
        if cond.HasField("temperature") and cond.temperature.HasField("control") else None
    press = _bar(cond.pressure.setpoint) if cond.HasField("pressure") and cond.pressure.HasField("setpoint") else None
    atmos = cond.pressure.atmosphere.DESCRIPTOR.fields_by_name["type"].enum_type.values_by_number[cond.pressure.atmosphere.type].name \
        if cond.HasField("pressure") and cond.pressure.HasField("atmosphere") else None
    hours = next((_hours(o.reaction_time) for o in rxn.outcomes if o.HasField("reaction_time")), None)
    yld = None
    for o in rxn.outcomes:
        for p in o.products:
            for m in p.measurements:
                if m.DESCRIPTOR.fields_by_name["type"].enum_type.values_by_number[m.type].name == "YIELD" and m.HasField("percentage"):
                    yld = round(m.percentage.value, 1)
    text = " ".join(filter(None, [cond.details, rxn.notes.procedure_details if rxn.HasField("notes") else ""])).lower()
    agents = [x for r in ("reagent", "catalyst", "reactant", "solvent", "unspecified") for x in comps.get(r, [])]
    blob = " ".join(f"{x['smiles'] or ''} {x['name'] or ''}" for x in agents).lower() + " " + text
    smis = [x["smiles"] or "" for x in agents]
    needs = set()
    names = " ".join((x["name"] or "") for x in agents).lower() + " " + text
    if atmos == "HYDROGEN" or "[H][H]" in smis or re.search(
            r"\bhydrogenat|\bhydrogen (gas|atmosphere|pressure|balloon)\b|under (an? )?(atmosphere of )?hydrogen\b|^hydrogen$|(?<![a-z] )\bhydrogen\b(?! (chloride|bromide|iodide|fluoride|sulfate|sulphate|carbonate|phosphate|peroxide|cyanide|sulfide))"
            r"|raney|pd/c|palladium on (carbon|charcoal)|\bpto2\b|platinum oxide", names):
        needs.add("hydrogenation")
    if (temp is not None and temp <= -20) or tcontrol in ("DRY_ICE_BATH", "LIQUID_NITROGEN"):
        needs.add("cryogenic")
    if temp is not None and temp >= 150:
        needs.add("high_temperature")
    if press is not None and press > 2:
        needs.add("pressure")
    if _ORGANOMET.search(" ".join(smis)) or _ORGANOMET.search(names):
        needs.add("organometallic")
    hz = sorted({lab for lab, srx, nrx in _HAZ if any(re.search(srx, s) for s in smis if s) or re.search(nrx, names)})
    if hz:
        needs.add("hazardous")
    if "hydrogenation" not in needs and ("[Pd]" in " ".join(smis) or "Pd" in " ".join(smis) or re.search(r"\bpd\(|palladium|pd2\(dba\)|pd\(pph3\)", names)):
        needs.add("pd_coupling")
    solvents = [SOLVENTS.get(_canon(x["smiles"]) or "", x["name"] or x["smiles"]) for x in comps.get("solvent", []) if x["smiles"] or x["name"]]
    if any(s in ("Dichloromethane", "Chloroform", "1,2-Dichloroethane") for s in solvents):
        needs.add("chlorinated_solvent")
    rs = next((i.value for i in rxn.identifiers if ">" in i.value), None)
    prov = rxn.provenance
    return {"id": rxn.reaction_id, "dataset": dataset, "smiles": rs.split(" |")[0] if rs else None,
            "patent": prov.patent or None, "doi": prov.doi or None, "temp_c": temp, "temp_control": tcontrol, "pressure_bar": press,
            "atmosphere": atmos, "hours": hours, "yield": yld, "needs": sorted(needs), "hazards": hz, "solvents": solvents,
            "reagents": [x["name"] or x["smiles"] for x in comps.get("reagent", [])][:8],
            "catalysts": [x["name"] or x["smiles"] for x in comps.get("catalyst", [])][:4],
            "reactants": [x["name"] or x["smiles"] for x in comps.get("reactant", [])][:6],
            # names ↔ structures ↔ recorded amounts, so a partner found by atom mapping can be named and dosed
            "components": [{"role": r, "name": x["name"], "smiles": x["smiles"], **{k: round(x[k], 6) for k in ("mol", "g", "ml") if k in x}}
                           for r in ("reactant", "reagent", "catalyst", "solvent") for x in comps.get(r, [])][:14],
            "c0": concentrations(comps)}


# ------------------------------------------------------------------------------------ scan

def scan(files: Iterable[Path], targets: dict[str, dict[str, Any]], log=print) -> dict[str, list[dict[str, Any]]]:
    """reactions per target canonical SMILES."""
    import pyarrow.parquet as pq
    from ord_schema.proto import reaction_pb2

    sigs = {v.get("sig") or signature(c) for c, v in targets.items()}
    hits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in files:
        pf = pq.ParquetFile(f)
        name = (pf.metadata.metadata or {}).get(b"ord.name", f.stem.encode()).decode("utf-8", "replace")
        n = found = 0
        t0 = time.time()
        # small batches, not whole row groups: a USPTO row group is hundreds of MB, and the server has 1 GB of RAM
        for batch in pf.iter_batches(batch_size=2000, columns=["reaction"]):
            for raw in batch.column(0).to_pylist():
                n += 1
                rxn = reaction_pb2.Reaction.FromString(raw)
                for smi in product_smiles(rxn):
                    if signature(smi) not in sigs:  # cheap filter before RDKit
                        continue
                    c = _canon(smi)
                    if c in targets:
                        hits[c].append(describe(rxn, name))
                        found += 1
                        break
        log(f"  {f.name}: {n:,} reactions, {found} for tracked molecules ({time.time() - t0:.0f}s) — {name[:60]}")
    return hits


def summarise(rows: list[dict[str, Any]], keep: int = 40) -> dict[str, Any]:
    temps = [r["temp_c"] for r in rows if r["temp_c"] is not None]
    yields = [r["yield"] for r in rows if r["yield"] is not None]
    needs = Counter(n for r in rows for n in r["needs"])
    rank = sorted(rows, key=lambda r: (-(len(r["needs"])), -(r["yield"] or 0), -(1 if r["temp_c"] is not None else 0)))
    examples, seen = [], set()
    for r in rank:
        # the same reaction run at other conditions is kept: points at several temperatures are what fit an Ea
        k = (r["smiles"] or r["id"], r["temp_c"], r["hours"], r["yield"])
        if k not in seen:
            seen.add(k)
            examples.append(r)
        if len(examples) >= keep:
            break
    return {"reactions": len(rows), "sources": len({r["patent"] or r["doi"] or r["dataset"] for r in rows}),
            "patents": sorted({r["patent"] for r in rows if r["patent"]})[:40], "dois": sorted({r["doi"] for r in rows if r["doi"]})[:20],
            "needs": {k: {"reactions": v, "share_pct": round(100 * v / len(rows), 1)} for k, v in needs.most_common()},
            "hazards": dict(Counter(h for r in rows for h in r["hazards"]).most_common(8)),
            "temp_c": {"min": min(temps), "median": statistics.median(temps), "max": max(temps), "n": len(temps)} if temps else None,
            "yield_median": statistics.median(yields) if yields else None,
            "solvents": dict(Counter(s for r in rows for s in r["solvents"]).most_common(10)),
            "catalysts": dict(Counter(c for r in rows for c in r["catalysts"]).most_common(8)),
            "reagents": dict(Counter(c for r in rows for c in r["reagents"]).most_common(10)),
            "examples": examples}


def _file_list() -> list[tuple[str, int]]:
    raw = http_get(f"https://huggingface.co/api/datasets/open-reaction-database/ord-data/tree/main/data", params={"recursive": "true"},
                   accept="application/json", timeout=60)
    items = json.loads(raw.decode("utf-8"))
    return sorted(((x["path"], int(x.get("size") or (x.get("lfs") or {}).get("size") or 0)) for x in items
                   if x.get("type") == "file" and x["path"].endswith(".parquet")), key=lambda t: t[1])


def run(ctx: Ctx) -> int:
    targets = load_targets()
    if not targets:
        raise NotFound("no molecule structures found (structures_seed.json / sources/pubchem.json)")
    ctx.log(f"  {sum(len(v['keys']) for v in targets.values())} tracked molecules with a structure")
    if ctx.from_file:
        files = [ctx.from_file] if ctx.from_file.is_file() else sorted(ctx.from_file.rglob("*.parquet"))
    else:
        try:
            listing = _file_list()
        except Exception as exc:
            raise Unreachable(f"Hugging Face listing: {exc}") from exc
        ctx.log(f"  {len(listing)} ORD datasets, {sum(s for _p, s in listing) / 1e9:.2f} GB (downloaded once, then only when changed)")
        files = []
        for path, _size in listing:
            dest = ctx.raw_dir / path.replace("/", "_")
            try:
                files.append(download(ctx, f"{HF}/resolve/main/{path}", dest.name, timeout=1800))
            except Exception as exc:
                if dest.exists():
                    files.append(dest)
                else:
                    ctx.log(f"  skipped {path}: {exc}")
    hits = scan(files, targets, ctx.log)
    data = {}
    for canon, rows in hits.items():
        s = summarise(rows)
        for k in targets[canon]["keys"]:
            data[k] = {"name": targets[canon]["name"], "smiles": canon, **s}
    ctx.log(f"  reactions found for {len(data)} of {sum(len(v['keys']) for v in targets.values())} molecules")
    write_normalized(ctx, META, data, len(data), extra={"needs": NEEDS, "datasets_scanned": len(files),
                                                          "licence": "CC BY-SA 4.0 — Open Reaction Database"})
    return len(data)

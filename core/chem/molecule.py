"""Descriptors and solubility estimates computed from a molecule's structure (RDKit)."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Optional

from rdkit import Chem, RDLogger
from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors
try:  # needs X11 libraries (libXrender etc.); if they're missing we draw with our own SVG writer
    from rdkit.Chem.Draw import rdMolDraw2D
    DRAW_ERROR = None
except ImportError as _exc:  # pragma: no cover
    rdMolDraw2D = None
    DRAW_ERROR = str(_exc)
from rdkit.Chem import rdDepictor

RDLogger.DisableLog("rdApp.*")

# Abraham / McGowan characteristic atomic volumes (cm3/mol); 6.56 is subtracted per bond.
_MCGOWAN = {"C": 16.35, "H": 8.71, "N": 14.39, "O": 12.43, "F": 10.48, "Cl": 20.95, "Br": 26.21, "I": 34.53,
            "S": 22.91, "P": 24.87, "Si": 26.83, "B": 18.32, "Se": 27.81, "As": 29.42}

# Metoprolol's log P (1.72) is the usual cut-off for "high permeability" in
# computational BCS assignment (Kasim et al., Mol Pharm 2004).
METOPROLOL_LOGP = 1.72
BCS_VOLUME_ML = 250.0


def parse(smiles: str) -> Optional[Chem.Mol]:
    """Parse SMILES and keep the largest fragment (drops counter-ions and waters)."""
    if not smiles:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    frags = Chem.GetMolFrags(mol, asMols=True)
    if len(frags) > 1:
        mol = max(frags, key=lambda m: m.GetNumHeavyAtoms())
    return mol


def parent_smiles(smiles: str) -> Optional[str]:
    mol = parse(smiles)
    return Chem.MolToSmiles(mol) if mol is not None else None


# Le Bas atomic volumes at the normal boiling point (cm3/mol), as used by Hayduk-Laudie
# (Poling, Prausnitz & O'Connell, The Properties of Gases and Liquids, 5th ed., Table 11-5).
_LEBAS = {"C": 14.8, "H": 3.7, "O": 7.4, "N": 15.6, "F": 8.7, "Cl": 24.6, "Br": 27.0, "I": 37.0, "S": 25.6, "P": 27.0}
_LEBAS_RING = {3: -6.0, 4: -8.5, 5: -11.5, 6: -15.0}

# Ionisable groups (a flag only: with no pKa, pH-dependent solubility is not modelled).
# `gi` = typically ionised somewhere in pH 1.2-6.8 (so it changes dissolution in buffers);
# phenols and sulfonamide NH (pKa ~9-10) are listed but are not.
_IONISABLE = {
    "carboxylic acid": ("acid", True, "[CX3](=O)[OX2H1,OX1-]"),
    "tetrazole": ("acid", True, "c1nn[nH]n1"),
    "acyl sulfonamide / imide": ("acid", True, "[#6,#16](=O)[NH][#6,#16](=O)"),
    "phenol": ("acid", False, "c[OX2H1]"),
    "sulfonamide NH": ("acid", False, "[#16X4](=O)(=O)[NX3;H1,H2]"),
    "aliphatic amine": ("base", True, "[NX3;H2,H1,H0;!$(N-[#6,#16]=[O,S,N]);!$(N-a);!$(N#*);!$(N=*);!$(N-N);!$(N-O);!$(N-S(=O))]([#6])"),
    "amidine / guanidine": ("base", True, "[NX3;!$(N-C=O)][CX3;!$(C=O)]=[NX2;!$(N-O)]"),
    "pyridine-like N": ("base", True, "[nX2;r6;!$(n:c=O);!$(n:n)]"),
    "imidazole": ("base", True, "[nX2]1:[cR1]:[nX3]:[cR1]:[cR1]:1"),
    "benzimidazole": ("base", True, "[nX2]1:c:[nX3]:c2:c:c:c:c:c:1:2"),
}
_IONISABLE_PAT = {k: (kind, gi, Chem.MolFromSmarts(sm)) for k, (kind, gi, sm) in _IONISABLE.items()}


def ionisable_groups(mol: Chem.Mol) -> list[dict[str, Any]]:
    """Ionisable functional groups found by SMARTS: name, acid/base, and whether it is
    usually ionised within pH 1.2-6.8 (`gi`)."""
    return [{"group": k, "kind": kind, "gi": gi} for k, (kind, gi, pat) in _IONISABLE_PAT.items()
            if pat is not None and mol.HasSubstructMatch(pat)]


def le_bas_volume(mol: Chem.Mol) -> float:
    """Le Bas molar volume at the normal boiling point, cm3/mol (atomic increments + ring corrections)."""
    molh = Chem.AddHs(mol)
    v = sum(_LEBAS.get(a.GetSymbol(), 20.0) for a in molh.GetAtoms())
    v += sum(_LEBAS_RING.get(len(r), -15.0) for r in mol.GetRingInfo().AtomRings())
    return v


def mcgowan_volume(mol: Chem.Mol) -> float:
    """McGowan characteristic volume, cm3/mol (Abraham & McGowan 1987)."""
    molh = Chem.AddHs(mol)
    total = sum(_MCGOWAN.get(a.GetSymbol(), 20.0) for a in molh.GetAtoms())
    return total - 6.56 * molh.GetNumBonds()


def aromatic_proportion(mol: Chem.Mol) -> float:
    heavy = mol.GetNumHeavyAtoms()
    return sum(1 for a in mol.GetAtoms() if a.GetIsAromatic()) / heavy if heavy else 0.0


def esol_logs(mol: Chem.Mol) -> float:
    """ESOL aqueous solubility, log10 mol/L (Delaney, J Chem Inf Comput Sci 2004)."""
    return (0.16 - 0.63 * Crippen.MolLogP(mol) - 0.0062 * Descriptors.MolWt(mol)
            + 0.066 * rdMolDescriptors.CalcNumRotatableBonds(mol) - 0.74 * aromatic_proportion(mol))


def gse_logs(logp: float, mp_c: float) -> float:
    """General Solubility Equation, log10 mol/L (Jain & Yalkowsky, J Pharm Sci 2001)."""
    return 0.5 - 0.01 * max(mp_c - 25.0, 0.0) - logp


def descriptors(mol: Chem.Mol, logp: Optional[float] = None) -> dict[str, Any]:
    """RDKit descriptors. `logp` (e.g. PubChem XLogP3) is used for the Lipinski count when given,
    so the page uses one log P throughout; Crippen cLogP otherwise."""
    mw = Descriptors.MolWt(mol)
    crippen = Crippen.MolLogP(mol)
    logp = crippen if logp is None else logp
    hbd, hba = Lipinski.NumHDonors(mol), Lipinski.NumHAcceptors(mol)
    tpsa = rdMolDescriptors.CalcTPSA(mol)
    rot = rdMolDescriptors.CalcNumRotatableBonds(mol)
    violations = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
    return {
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "mw": round(mw, 2),
        "exact_mass": round(Descriptors.ExactMolWt(mol), 4),
        "clogp": round(crippen, 2),
        "tpsa": round(tpsa, 1),
        "hbd": hbd, "hba": hba,
        "rotatable_bonds": rot,
        "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(mol),
        "heavy_atoms": mol.GetNumHeavyAtoms(),
        "fraction_csp3": round(rdMolDescriptors.CalcFractionCSP3(mol), 2),
        "mcgowan_volume": round(mcgowan_volume(mol), 1),
        "le_bas_volume": round(le_bas_volume(mol), 1),
        "lipinski_violations": violations,
        "veber_ok": rot <= 10 and tpsa <= 140,
    }


_COLORS = {"O": "#e11d48", "N": "#2563eb", "S": "#a16207", "F": "#16a34a", "Cl": "#16a34a", "Br": "#9a3412", "I": "#7c3aed", "P": "#ea580c"}


def svg_basic(mol: Chem.Mol, width: int = 320, height: int = 220) -> str:
    """Plain SVG depiction from RDKit 2D coordinates (no drawing libraries needed)."""
    m = Chem.Mol(mol)
    try:
        Chem.Kekulize(m, clearAromaticFlags=True)
    except Exception:
        pass
    rdDepictor.Compute2DCoords(m)
    conf = m.GetConformer()
    xs = [conf.GetAtomPosition(i).x for i in range(m.GetNumAtoms())]
    ys = [conf.GetAtomPosition(i).y for i in range(m.GetNumAtoms())]
    if not xs:
        return ""
    pad = 18
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    k = min((width - 2 * pad) / max(max(xs) - min(xs), 1e-6), (height - 2 * pad) / max(max(ys) - min(ys), 1e-6), 40.0)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    P = [(width / 2 + (x - cx) * k, height / 2 - (y - cy) * k) for x, y in zip(xs, ys)]
    labels = {}
    for a in m.GetAtoms():
        sym = a.GetSymbol()
        if sym != "C" or a.GetDegree() == 0 or a.GetFormalCharge():
            h = a.GetTotalNumHs()
            lab = sym + ("H" if h == 1 else f"H{h}" if h > 1 else "")
            ch = a.GetFormalCharge()
            lab += ("+" if ch == 1 else "−" if ch == -1 else (f"{ch:+d}" if ch else ""))
            labels[a.GetIdx()] = lab
    parts = []
    fs = max(9.0, min(14.0, k * 0.42))
    for b in m.GetBonds():
        i, j = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        (x1, y1), (x2, y2) = P[i], P[j]
        dx, dy = x2 - x1, y2 - y1
        ln = (dx * dx + dy * dy) ** 0.5 or 1
        ux, uy = dx / ln, dy / ln
        s1 = fs * 0.62 if i in labels else 0
        s2 = fs * 0.62 if j in labels else 0
        x1, y1, x2, y2 = x1 + ux * s1, y1 + uy * s1, x2 - ux * s2, y2 - uy * s2
        order = int(b.GetBondTypeAsDouble()) if b.GetBondTypeAsDouble() >= 1 else 1
        off = 2.6
        nx, ny = -uy * off, ux * off
        shifts = [0] if order == 1 else [-1, 1] if order == 2 else [-2, 0, 2]
        for sft in shifts:
            parts.append(f'<line x1="{x1 + nx * sft / (1 if order != 3 else 2):.1f}" y1="{y1 + ny * sft / (1 if order != 3 else 2):.1f}" '
                         f'x2="{x2 + nx * sft / (1 if order != 3 else 2):.1f}" y2="{y2 + ny * sft / (1 if order != 3 else 2):.1f}" '
                         f'stroke="#1e293b" stroke-width="1.5" stroke-linecap="round"/>')
    for idx, lab in labels.items():
        x, y = P[idx]
        col = _COLORS.get(m.GetAtomWithIdx(idx).GetSymbol(), "#0f172a")
        parts.append(f'<text x="{x:.1f}" y="{y + fs * 0.36:.1f}" font-size="{fs:.1f}" font-family="Helvetica,Arial,sans-serif" '
                     f'text-anchor="middle" fill="{col}" font-weight="600">{lab}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            + "".join(parts) + "</svg>")


def svg(mol: Chem.Mol, width: int = 320, height: int = 220) -> str:
    if rdMolDraw2D is None:
        return svg_basic(mol, width, height)
    d = rdMolDraw2D.MolDraw2DSVG(width, height)
    opts = d.drawOptions()
    opts.clearBackground = False
    opts.bondLineWidth = 1.6
    d.DrawMolecule(Chem.Mol(mol))
    d.FinishDrawing()
    return d.GetDrawingText().replace("<?xml version='1.0' encoding='iso-8859-1'?>\n", "")


ESTIMATE_MAX_MG_ML = 1000.0  # above this a structure-based estimate is outside any plausible range


def solubility(mol: Chem.Mol, mp_c: Optional[float], logp: Optional[float] = None, logp_source: str = "RDKit Crippen cLogP") -> dict[str, Any]:
    """Aqueous solubility ESTIMATE at 25 C from structure (neutral form): GSE when a measured melting
    point is known, else ESOL. Both have a typical error of about ±1 log unit on drugs, more for
    zwitterions and ionisable molecules (pH is not modelled)."""
    mw = Descriptors.MolWt(mol)
    if logp is None:
        logp, logp_source = Crippen.MolLogP(mol), "RDKit Crippen cLogP"
    esol = esol_logs(mol)
    gse = gse_logs(logp, mp_c) if mp_c is not None else None
    chosen, model = (gse, f"GSE, Jain & Yalkowsky 2001 (melting point + {logp_source})") if gse is not None else (esol, "ESOL, Delaney 2004 (structure only)")
    mg_ml = (10 ** chosen) * mw  # mol/L * g/mol = g/L = mg/mL
    groups = ionisable_groups(mol)
    kinds = {g["kind"] for g in groups if g["gi"]}
    flags = []
    if mg_ml > ESTIMATE_MAX_MG_ML:
        flags.append(f"outside model domain: estimate {mg_ml:.2g} mg/mL is above {ESTIMATE_MAX_MG_ML:g} mg/mL")
    if kinds == {"acid", "base"}:
        flags.append("zwitterion / amphoteric (" + ", ".join(g["group"] for g in groups if g["gi"]) + "): neutral-form estimate can be off by orders of magnitude")
    elif kinds:
        flags.append("ionisable (" + ", ".join(g["group"] for g in groups if g["gi"]) + "), pKa unknown: pH-dependent solubility not modelled")
    return {"kind": "estimate", "model": model, "log_s": round(chosen, 2), "mg_per_ml": mg_ml,
            "display_mg_ml": float(f"{mg_ml:.1g}"), "uncertainty": "±1 log unit (×10 either way)",
            "in_domain": mg_ml <= ESTIMATE_MAX_MG_ML, "flags": flags, "ionisable": groups,
            "ionisable_gi": sorted(kinds),
            "logp": round(logp, 2), "logp_source": logp_source,
            "esol_log_s": round(esol, 2), "gse_log_s": round(gse, 2) if gse is not None else None}


def bcs(mg_per_ml: float, logp: float, dose_mg: Optional[float], solubility_kind: str = "estimate") -> dict[str, Any]:
    """PROVISIONAL BCS class: dose number from the given solubility and the highest oral-solid
    strength, permeability from log P vs metoprolol (Kasim et al. 2004). A structure-only guess,
    not a regulatory classification; the log P proxy misses transporter-absorbed and small polar
    drugs (metoprolol itself sits on the cut-off)."""
    if not dose_mg:
        return {"class": None, "reason": "No oral solid strength known, so the dose number can't be computed."}
    d0 = (dose_mg / BCS_VOLUME_ML) / max(mg_per_ml, 1e-12)
    high_sol = d0 <= 1.0
    high_perm = logp >= METOPROLOL_LOGP
    cls = {(True, True): "I", (False, True): "II", (True, False): "III", (False, False): "IV"}[(high_sol, high_perm)]
    sol_note = "measured solubility" if solubility_kind == "measured" else "estimated solubility (±1 log unit)"
    return {"class": cls, "dose_number": round(d0, 3), "high_solubility": high_sol, "high_permeability": high_perm,
            "basis": f"provisional, structure-only guess; uses {sol_note}; permeability from log P only",
            "reason": f"Dose number {d0:.2g} ({'≤' if high_sol else '>'} 1) for {dose_mg:g} mg in 250 mL, from {sol_note}; "
                      f"log P {logp:.2f} {'≥' if high_perm else '<'} metoprolol ({METOPROLOL_LOGP}). "
                      "Not a regulatory classification: BCS needs solubility over pH 1.2–6.8 at 37 °C and measured permeability."}


@lru_cache(maxsize=512)
def profile(smiles: str, mp_c: Optional[float] = None, dose_mg: Optional[float] = None,
            logp: Optional[float] = None, logp_source: str = "PubChem XLogP3") -> Optional[dict[str, Any]]:
    mol = parse(smiles)
    if mol is None:
        return None
    sol = solubility(mol, mp_c, logp, logp_source) if logp is not None else solubility(mol, mp_c)
    desc = descriptors(mol, sol["logp"])
    return {"smiles": Chem.MolToSmiles(mol), "descriptors": desc, "solubility": sol,
            "bcs": bcs(sol["mg_per_ml"], sol["logp"], dose_mg), "svg": svg(mol)}


def hayduk_laudie_diffusivity(molar_volume_cm3: float, temp_c: float = 37.0) -> float:
    """Diffusion coefficient in water, cm2/s (Hayduk & Laudie 1974); `molar_volume_cm3` is the Le Bas
    volume at the normal boiling point. Typical error about ±20-30%."""
    t = temp_c + 273.15
    visc_cp = 2.414e-2 * 10 ** (247.8 / (t - 140.0))  # Vogel-type fit for water, mPa.s
    return 13.26e-5 / (visc_cp ** 1.14 * molar_volume_cm3 ** 0.589)


def logs_to_mg_ml(log_s: float, mw: float) -> float:
    return (10 ** log_s) * mw


def mg_ml_at(temp_c: float, mg_ml_25: float, dh_j_mol: float) -> float:
    """van 't Hoff temperature correction of solubility (ideal: enthalpy of solution ~ enthalpy of fusion)."""
    r = 8.314
    return mg_ml_25 * math.exp(-dh_j_mol / r * (1 / (temp_c + 273.15) - 1 / 298.15))

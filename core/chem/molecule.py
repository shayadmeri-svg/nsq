"""Descriptors and solubility estimates computed from a molecule's structure (RDKit)."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Optional

from rdkit import Chem, RDLogger
from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D

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


def descriptors(mol: Chem.Mol) -> dict[str, Any]:
    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    hbd, hba = Lipinski.NumHDonors(mol), Lipinski.NumHAcceptors(mol)
    tpsa = rdMolDescriptors.CalcTPSA(mol)
    rot = rdMolDescriptors.CalcNumRotatableBonds(mol)
    violations = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
    return {
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "mw": round(mw, 2),
        "exact_mass": round(Descriptors.ExactMolWt(mol), 4),
        "clogp": round(logp, 2),
        "tpsa": round(tpsa, 1),
        "hbd": hbd, "hba": hba,
        "rotatable_bonds": rot,
        "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(mol),
        "heavy_atoms": mol.GetNumHeavyAtoms(),
        "fraction_csp3": round(rdMolDescriptors.CalcFractionCSP3(mol), 2),
        "mcgowan_volume": round(mcgowan_volume(mol), 1),
        "lipinski_violations": violations,
        "veber_ok": rot <= 10 and tpsa <= 140,
    }


def svg(mol: Chem.Mol, width: int = 320, height: int = 220) -> str:
    d = rdMolDraw2D.MolDraw2DSVG(width, height)
    opts = d.drawOptions()
    opts.clearBackground = False
    opts.bondLineWidth = 1.6
    d.DrawMolecule(Chem.Mol(mol))
    d.FinishDrawing()
    return d.GetDrawingText().replace("<?xml version='1.0' encoding='iso-8859-1'?>\n", "")


def solubility(mol: Chem.Mol, mp_c: Optional[float], logp: Optional[float] = None, logp_source: str = "RDKit Crippen cLogP") -> dict[str, Any]:
    """Aqueous solubility at 25 C from structure. GSE when a melting point is known, else ESOL."""
    mw = Descriptors.MolWt(mol)
    if logp is None:
        logp, logp_source = Crippen.MolLogP(mol), "RDKit Crippen cLogP"
    esol = esol_logs(mol)
    gse = gse_logs(logp, mp_c) if mp_c is not None else None
    chosen, model = (gse, f"GSE (melting point + {logp_source})") if gse is not None else (esol, "ESOL (structure only)")
    mg_ml = (10 ** chosen) * mw  # mol/L * g/mol = g/L = mg/mL
    return {"model": model, "log_s": round(chosen, 2), "mg_per_ml": mg_ml, "logp": round(logp, 2), "logp_source": logp_source,
            "esol_log_s": round(esol, 2), "gse_log_s": round(gse, 2) if gse is not None else None}


def bcs(mg_per_ml: float, clogp: float, dose_mg: Optional[float]) -> dict[str, Any]:
    """Provisional BCS class from computed solubility, the highest strength seen, and cLogP."""
    if not dose_mg:
        return {"class": None, "reason": "No strength known, so the dose number can't be computed."}
    d0 = (dose_mg / BCS_VOLUME_ML) / max(mg_per_ml, 1e-12)
    high_sol = d0 <= 1.0
    high_perm = clogp >= METOPROLOL_LOGP
    cls = {(True, True): "I", (False, True): "II", (True, False): "III", (False, False): "IV"}[(high_sol, high_perm)]
    return {"class": cls, "dose_number": round(d0, 3), "high_solubility": high_sol, "high_permeability": high_perm,
            "reason": f"Dose number {d0:.3g} ({'≤' if high_sol else '>'} 1) for {dose_mg:g} mg in 250 mL; "
                      f"log P {clogp:.2f} {'≥' if high_perm else '<'} metoprolol ({METOPROLOL_LOGP})."}


@lru_cache(maxsize=512)
def profile(smiles: str, mp_c: Optional[float] = None, dose_mg: Optional[float] = None,
            logp: Optional[float] = None, logp_source: str = "PubChem XLogP3") -> Optional[dict[str, Any]]:
    mol = parse(smiles)
    if mol is None:
        return None
    desc = descriptors(mol)
    sol = solubility(mol, mp_c, logp, logp_source) if logp is not None else solubility(mol, mp_c)
    return {"smiles": Chem.MolToSmiles(mol), "descriptors": desc, "solubility": sol,
            "bcs": bcs(sol["mg_per_ml"], sol["logp"], dose_mg), "svg": svg(mol)}


def hayduk_laudie_diffusivity(molar_volume_cm3: float, temp_c: float = 37.0) -> float:
    """Diffusion coefficient in water, cm2/s (Hayduk & Laudie 1974), viscosity of water at temp."""
    t = temp_c + 273.15
    visc_cp = 2.414e-2 * 10 ** (247.8 / (t - 140.0))  # Vogel-type fit for water, mPa.s
    return 13.26e-5 / (visc_cp ** 1.14 * molar_volume_cm3 ** 0.589)


def logs_to_mg_ml(log_s: float, mw: float) -> float:
    return (10 ** log_s) * mw


def mg_ml_at(temp_c: float, mg_ml_25: float, dh_j_mol: float) -> float:
    """van 't Hoff temperature correction of solubility (ideal: enthalpy of solution ~ enthalpy of fusion)."""
    r = 8.314
    return mg_ml_25 * math.exp(-dh_j_mol / r * (1 / (temp_c + 273.15) - 1 / 298.15))

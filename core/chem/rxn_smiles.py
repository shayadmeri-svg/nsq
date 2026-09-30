"""What a published reaction actually does, read from its atom-mapped reaction SMILES (ORD / USPTO).

For a target molecule and one reaction record:
  * which product fragment is the target (canonical, stereo-free comparison);
  * which reactant molecules contribute atoms to it (atom maps) — the real partners, so a template can be picked
    from data instead of by counting names; bases, acids for salt formation and solvents contribute none;
  * which bonds are formed or broken on the way (mapped-atom bonds in reactants vs product). No covalent change
    means the record is a salt formation, a free-basing or an isolation — not a kinetic step to simulate.

Nothing here is estimated: it is bookkeeping on the published structure record. When the record has no atom maps
the answer is "unknown", not a guess.
"""

from __future__ import annotations

from typing import Any, Optional

from rdkit import Chem, RDLogger
from rdkit.Chem.rdMolDescriptors import CalcMolFormula

RDLogger.DisableLog("rdApp.*")


def _plain(m: Chem.Mol) -> Optional[str]:
    """Canonical SMILES without atom maps, stereo or charges on the largest fragment's skeleton."""
    m = Chem.Mol(m)
    for a in m.GetAtoms():
        a.SetAtomMapNum(0)
    Chem.RemoveStereochemistry(m)
    try:
        return Chem.MolToSmiles(m)
    except Exception:
        return None


def _largest(m: Chem.Mol) -> Chem.Mol:
    frags = Chem.GetMolFrags(m, asMols=True, sanitizeFrags=False)
    return max(frags, key=lambda f: f.GetNumHeavyAtoms()) if frags else m


def _mols(part: str) -> list[Chem.Mol]:
    out = []
    for s in part.split("."):
        if not s:
            continue
        m = Chem.MolFromSmiles(s, sanitize=False)
        if m is None:
            continue
        try:
            Chem.SanitizeMol(m, Chem.SanitizeFlags.SANITIZE_ALL ^ Chem.SanitizeFlags.SANITIZE_PROPERTIES)
        except Exception:
            pass
        out.append(m)
    return out


def _bonds(mols: list[Chem.Mol]) -> dict[frozenset, float]:
    """{(map1, map2): bond order} for bonds whose two atoms are both mapped."""
    b: dict[frozenset, float] = {}
    for m in mols:
        for bd in m.GetBonds():
            a1, a2 = bd.GetBeginAtom().GetAtomMapNum(), bd.GetEndAtom().GetAtomMapNum()
            if a1 and a2:
                b[frozenset((a1, a2))] = bd.GetBondTypeAsDouble()
    return b


def analyse(rxn_smiles: Optional[str], target_smiles: Optional[str]) -> dict[str, Any]:
    if not rxn_smiles or rxn_smiles.count(">") != 2:
        return {"kind": "unknown", "why": "no reaction SMILES in the record"}
    r_part, _agents, p_part = rxn_smiles.split(" |")[0].split(">")
    reactants, products = _mols(r_part), _mols(p_part)
    if not products:
        return {"kind": "unknown", "why": "no product structure in the record"}
    tgt = Chem.MolFromSmiles(target_smiles) if target_smiles else None
    tgt_key = _plain(_largest(tgt)) if tgt is not None else None
    prod = next((p for p in products if tgt_key and _plain(_largest(p)) == tgt_key), None)
    matched = prod is not None
    if prod is None:  # the record's product is a salt / different form: use its largest mapped fragment
        prod = max(products, key=lambda p: sum(1 for a in p.GetAtoms() if a.GetAtomMapNum()))
    pmaps = {a.GetAtomMapNum() for a in prod.GetAtoms() if a.GetAtomMapNum()}
    if not pmaps:
        return {"kind": "unknown", "why": "the record has no atom mapping", "target_matched": matched}
    contrib = [m for m in reactants if any(a.GetAtomMapNum() in pmaps for a in m.GetAtoms())]
    rb, pb = _bonds(contrib), _bonds([prod])
    formed = [k for k in pb if k not in rb]
    broken = [k for k, v in rb.items() if (k <= pmaps and k not in pb)]
    # a bond from a product atom to an atom that leaves (mapped, not in the product) is also broken
    for m in contrib:
        for bd in m.GetBonds():
            a1, a2 = bd.GetBeginAtom().GetAtomMapNum(), bd.GetEndAtom().GetAtomMapNum()
            if (a1 in pmaps) != (a2 in pmaps) and (a1 or a2):
                if (a1 in pmaps and a2 == 0) or (a2 in pmaps and a1 == 0) or (a1 and a2):
                    broken.append(frozenset((a1, a2)))
    order = [k for k in pb if k in rb and abs(rb[k] - pb[k]) > 1e-6]
    # the target skeleton already present among the reactants = no covalent step made it
    same_skeleton = any(tgt_key and _plain(_largest(m)) == tgt_key for m in reactants)
    covalent = bool(formed or broken or order) and not same_skeleton
    parts = []
    for m in contrib:
        pl = _plain(m)
        try:
            f = CalcMolFormula(Chem.MolFromSmiles(pl)) if pl else None
        except Exception:
            f = None
        parts.append({"smiles": pl, "formula": f, "heavy_atoms": m.GetNumHeavyAtoms()})
    parts.sort(key=lambda x: -x["heavy_atoms"])
    return {
        "kind": "covalent" if covalent else "salt_or_isolation",
        "why": (f"{len(formed)} bond(s) formed, {len(set(broken))} broken" if covalent
                else "the product's skeleton is already a reactant: only a salt / protonation / isolation change"),
        "target_matched": matched, "partners": parts, "n_partners": len(parts),
        "bonds_formed": len(formed), "bonds_broken": len(set(broken)), "bond_order_changes": len(order),
        "group_key": "|".join(sorted(p["smiles"] or "?" for p in parts)),
    }

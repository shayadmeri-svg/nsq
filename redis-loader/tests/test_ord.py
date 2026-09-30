"""Open Reaction Database scan: synthetic reactions written with ord_schema's own Parquet writer."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("ord_schema")
pytest.importorskip("rdkit")

from ord_schema.parquet import DatasetWriter  # noqa: E402
from ord_schema.proto import reaction_pb2 as rp  # noqa: E402

from sources import ord as o  # noqa: E402


def _cmp(smiles, role, name=None):
    c = rp.Compound()
    c.identifiers.add(type=rp.CompoundIdentifier.SMILES, value=smiles)
    if name:
        c.identifiers.add(type=rp.CompoundIdentifier.NAME, value=name)
    c.reaction_role = role
    return c


def _rxn(rid, product, inputs, temp=None, atmos=None, bar=None, yld=None, patent=None):
    r = rp.Reaction(reaction_id=rid)
    for i, (smi, role, name) in enumerate(inputs):
        r.inputs[f"m{i}"].components.append(_cmp(smi, role, name))
    if temp is not None:
        r.conditions.temperature.setpoint.value = temp
        r.conditions.temperature.setpoint.units = rp.Temperature.CELSIUS
    if atmos:
        r.conditions.pressure.atmosphere.type = atmos
    if bar is not None:
        r.conditions.pressure.setpoint.value = bar
        r.conditions.pressure.setpoint.units = rp.Pressure.BAR
    out = r.outcomes.add()
    p = out.products.add()
    p.identifiers.add(type=rp.CompoundIdentifier.SMILES, value=product)
    if yld is not None:
        m = p.measurements.add(type=rp.ProductMeasurement.YIELD)
        m.percentage.value = yld
    if patent:
        r.provenance.patent = patent
    return r


R = rp.ReactionRole
TARGETS = None


def test_scan_matches_salts_and_flags_needs(tmp_path):
    f = tmp_path / "ds.parquet"
    rxns = [
        # paracetamol by hydrogenation of 4-nitrophenol then acetylation (one-pot), Pd/C, H2, 3 bar, MeOH
        _rxn("r1", "CC(=O)Nc1ccc(O)cc1", [("Oc1ccc([N+](=O)[O-])cc1", R.REACTANT, None), ("[H][H]", R.REAGENT, "hydrogen"),
                                          ("[Pd]", R.CATALYST, "palladium on carbon"), ("CO", R.SOLVENT, None)],
             temp=40, atmos=rp.PressureConditions.Atmosphere.HYDROGEN, bar=3, yld=91, patent="US1234567"),
        # paracetamol as its sodium salt, acetic anhydride in water — no special needs
        _rxn("r2", "CC(=O)Nc1ccc([O-])cc1.[Na+]", [("Nc1ccc(O)cc1", R.REACTANT, None), ("CC(=O)OC(C)=O", R.REAGENT, None), ("O", R.SOLVENT, None)],
             temp=25, yld=85),
        # something else entirely, made at −78 °C with n-BuLi in THF
        _rxn("r3", "CCCCc1ccccc1", [("Brc1ccccc1", R.REACTANT, None), ("[Li]CCCC", R.REAGENT, None), ("C1CCOC1", R.SOLVENT, None)], temp=-78),
    ]
    with DatasetWriter(f, name="test set", description="synthetic") as w:
        for r in rxns:
            w.write(r)
    targets = {o._canon("CC(=O)Nc1ccc(O)cc1"): {"keys": ["paracetamol"], "name": "Paracetamol", "atoms": 11}}
    hits = o.scan([f], targets, log=lambda *_: None)
    rows = hits[o._canon("CC(=O)Nc1ccc(O)cc1")]
    assert [r["id"] for r in rows] == ["r1", "r2"]  # the sodium salt matches, the −78 °C reaction does not
    r1 = rows[0]
    assert r1["needs"] == ["hydrogenation", "pressure"] and r1["pressure_bar"] == 3 and r1["yield"] == 91 and r1["solvents"] == ["Methanol"]
    assert r1["patent"] == "US1234567" and r1["dataset"] == "test set"
    s = o.summarise(rows)
    assert s["reactions"] == 2 and s["needs"]["hydrogenation"]["share_pct"] == 50.0 and s["temp_c"]["max"] == 40
    assert s["examples"][0]["id"] == "r1"  # the most demanding route first


def test_describe_cryogenic_organometallic_hazard():
    r = _rxn("x", "CCCCc1ccccc1", [("Brc1ccccc1", R.REACTANT, None), ("[Li]CCCC", R.REAGENT, "n-butyllithium"),
                                    ("[N-]=[N+]=[N-].[Na+]", R.REAGENT, "sodium azide"), ("ClCCl", R.SOLVENT, None)], temp=-78)
    d = o.describe(r, "t")
    assert o.signature("CC(=O)Nc1ccc([O-])cc1.[Na+]") == o.signature("CC(=O)Nc1ccc(O)cc1") == (11, 1, 2, 0, 0)
    assert set(d["needs"]) == {"cryogenic", "organometallic", "hazardous", "chlorinated_solvent"} and d["hazards"] == ["azide"]


def test_no_false_flags_from_common_words_and_acids():
    r = _rxn("y", "CC(=O)Nc1ccc(O)cc1", [("Nc1ccc(O)cc1", R.REACTANT, None), ("CC(=O)O", R.SOLVENT, "acetic acid"),
                                          ("Cl", R.REAGENT, "hydrogen chloride"), ("OC(=O)[O-].[Na+]", R.WORKUP, "sodium hydrogen carbonate")], temp=25)
    r.notes.procedure_details = "The mixture was cooled to room temperature and stirred overnight."
    d = o.describe(r, "t")
    assert d["needs"] == [] and d["hazards"] == []
    h = _rxn("z", "CC(=O)Nc1ccc(O)cc1", [("CC(=O)Nc1ccc([N+](=O)[O-])cc1", R.REACTANT, None), ("[Pd]", R.CATALYST, "palladium on carbon")])
    h.notes.procedure_details = "Hydrogenated under hydrogen atmosphere (50 psi)."
    assert o.describe(h, "t")["needs"] == ["hydrogenation"]


def test_recorded_amounts_give_starting_concentrations():
    r = _rxn("c", "CC(=O)Nc1ccccc1", [("Nc1ccccc1", R.REACTANT, "aniline"), ("CC(=O)Cl", R.REACTANT, "acetyl chloride"),
                                       ("ClCCl", R.SOLVENT, "dichloromethane")], temp=0, yld=90)
    comps = [c for k in sorted(r.inputs) for c in r.inputs[k].components]
    comps[0].amount.moles.value, comps[0].amount.moles.units = 10, rp.Moles.MILLIMOLE
    comps[1].amount.moles.value, comps[1].amount.moles.units = 12, rp.Moles.MILLIMOLE
    comps[2].amount.volume.value, comps[2].amount.volume.units = 50, rp.Volume.MILLILITER
    d = o.describe(r, "t")
    assert d["c0"]["volume_ml"] == 50 and d["c0"]["mol_l"] == {"Nc1ccccc1": 0.2, "CC(=O)Cl": 0.24}
    assert {x["name"]: x.get("mol") for x in d["components"]}["aniline"] == 0.01


def test_same_reaction_at_other_conditions_is_kept():
    base = {"smiles": "A>>B", "needs": [], "hazards": [], "solvents": [], "catalysts": [], "reagents": [], "patent": None, "doi": None, "dataset": "d"}
    rows = [{**base, "id": f"r{i}", "temp_c": t, "hours": 2, "yield": y} for i, (t, y) in enumerate(((20, 50), (60, 90), (20, 50)))]
    assert [e["temp_c"] for e in o.summarise(rows)["examples"]] == [60, 20]  # duplicates dropped, other temperatures kept


def test_internal_standard_is_not_a_product():
    r = _rxn("s", "CCCCc1ccccc1", [("Brc1ccccc1", R.REACTANT, None)])
    p = r.outcomes[0].products.add()
    p.identifiers.add(type=rp.CompoundIdentifier.SMILES, value="Cn1c(=O)c2c(ncn2C)n(C)c1=O")
    p.reaction_role = rp.ReactionRole.INTERNAL_STANDARD
    assert "Cn1c(=O)c2c(ncn2C)n(C)c1=O" not in o.product_smiles(r)

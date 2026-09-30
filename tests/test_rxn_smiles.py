"""Reading a published reaction record: partners from atom maps, bonds made, salt formations recognised."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from chem.rxn_smiles import analyse  # noqa: E402

ACETANILIDE = "CC(=O)Nc1ccccc1"


def test_amide_formation_is_a_covalent_two_partner_step():
    rxn = "[CH3:1][C:2](=[O:3])Cl.[NH2:4][c:5]1[cH:6][cH:7][cH:8][cH:9][cH:10]1>CCN(CC)CC>[CH3:1][C:2](=[O:3])[NH:4][c:5]1[cH:6][cH:7][cH:8][cH:9][cH:10]1"
    a = analyse(rxn, ACETANILIDE)
    assert a["kind"] == "covalent" and a["n_partners"] == 2 and a["bonds_formed"] == 1 and a["target_matched"]


def test_salt_formation_is_not_a_reaction_step():
    rxn = "[CH3:1][C:2](=[O:3])[NH:4][c:5]1[cH:6][cH:7][cH:8][cH:9][cH:10]1.Cl>O>[CH3:1][C:2](=[O:3])[NH:4][c:5]1[cH:6][cH:7][cH:8][cH:9][cH:10]1.Cl"
    a = analyse(rxn, ACETANILIDE)
    assert a["kind"] == "salt_or_isolation"


def test_unmapped_record_is_unknown_not_guessed():
    assert analyse("CC(=O)Cl.Nc1ccccc1>>CC(=O)Nc1ccccc1", ACETANILIDE)["kind"] == "unknown"
    assert analyse(None, ACETANILIDE)["kind"] == "unknown"

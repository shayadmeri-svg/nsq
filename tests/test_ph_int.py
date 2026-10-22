"""The International Pharmacopoeia parser: titles, assay limits and the dissolution test, on Ph. Int.'s own wording."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "redis-loader"))
sys.path.insert(0, str(ROOT / "core"))

from sources import ph_int as P  # noqa: E402


def test_titles_split_into_ingredients_and_form():
    assert P.split_title("Ciprofloxacin tablets (Ciprofloxacini compressi)") == (["Ciprofloxacin"], "tablets")
    assert P.split_title("Albendazole chewable tablets (Albendazoli compressi manducabili)") == (["Albendazole"], "chewable tablets")
    assert P.split_title("Dolutegravir, lamivudine and tenofovir disoproxil tablets (x)") == (["Dolutegravir", "lamivudine", "tenofovir disoproxil"], "tablets")
    assert P.split_title("Paracetamol oral solution (Paracetamoli solutio peroralum)") is None  # not a solid oral form


def test_assay_limits():
    a = P.parse_assay("Definition. Ciprofloxacin tablets contain not less than 90.0% and not more than 110.0% of the amount of "
                      "ciprofloxacin (C 17 H 18 FN 3 O 3 ) stated on the label. Identity test")
    assert (a["lo"], a["hi"]) == (90.0, 110.0)


def test_dissolution_with_q():
    text = ("Dissolution. Carry out the test as described under 5.5 Dissolution test for solid oral dosage forms , using as the "
            "dissolution medium 900 ml of hydrochloric acid (~3.65 g/L) TS and rotating the paddle at 50 revolutions per minute. "
            "At 30 minutes, withdraw a sample. The amount of ciprofloxacin released is not less than 80% (Q) of the amount declared "
            "on the label. Related substances. Prepare fresh solutions.")
    d = P.parse_dissolution(text)
    assert (d["volume_ml"], d["ph"], d["apparatus"], d["rpm"], d["time_min"], d["q_pct"]) == (900.0, 1.2, "paddle", 50.0, 30.0, 80.0)
    assert d["conditions_given"] and "Related substances" not in d["text"]


def test_dissolution_older_wording_and_medium_first():
    older = P.parse_dissolution("Dissolution. Carry out the test …, using as the dissolution medium, 500 mL of dissolution buffer, "
                                "pH 6.8, TS and rotating the paddle at 75 revolutions per minute. At 30 minutes withdraw a sample. "
                                "The amount in solution for each tablet is not less than 80% of the amount declared on the label.")
    assert (older["volume_ml"], older["ph"], older["each_unit_min_pct"]) == (500.0, 6.8, 80.0) and "q_pct" not in older
    first = P.parse_dissolution("Dissolution. For 200 mg tablets : carry out the test using 900 mL of hydrochloric acid (~3.65 g/L)TS "
                                "as the dissolution medium and rotating the paddle at 50 revolutions per minute. At 30 minutes, withdraw.")
    assert (first["volume_ml"], first["ph"], first["rpm"]) == (900.0, 1.2, 50.0)


def test_test_required_without_conditions():
    d = P.parse_dissolution("Dissolution. Carry out the test as described under 5.5 Dissolution test for solid oral dosage forms .")
    assert d is not None and not d["conditions_given"] and "q_pct" not in d

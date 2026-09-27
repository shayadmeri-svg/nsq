"""NFHS / IDSP / Comtrade parsing (synthetic files in the published layouts)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources import health_signals as hs  # noqa: E402

WIDE = ("District Names,State/UT,Number of Households surveyed,"
        "Women (age 15 years and above) with high or very high (>140 mg/dl) Blood sugar level  or taking medicine to control blood sugar level (%),"
        "Men (age 15 years and above) with high or very high (>140 mg/dl) Blood sugar level  or taking medicine to control blood sugar level (%),"
        "Women (age 15 years and above) with Elevated blood pressure (Systolic >=140 mm of Hg and/or Diastolic >=90 mm of Hg) or taking medicine to control blood pressure (%),"
        "All women age 15-49 years who are anaemic (%),Prevalence of diarrhoea in the 2 weeks preceding the survey (%)\n"
        "Nicobars,Andaman & Nicobar Islands,882,14.5,17.2,22.1,(35.9),2.4\n"
        "Pune,Maharashtra,900,12.0,15.1,24.0,45.2,*\n")


def test_nfhs_wide_district_csv(tmp_path):
    f = tmp_path / "NFHS-5_districts.csv"
    f.write_text(WIDE)
    rows = hs.parse_nfhs(f)
    pune = {r["ind"]: r["value"] for r in rows if r["district"] == "Pune"}
    assert pune == {"sugar_women": 12.0, "sugar_men": 15.1, "bp_women": 24.0, "anaemia_women": 45.2}  # '*' dropped
    assert all(r["round"] == "NFHS-5" and r["level"] == "district" for r in rows)
    assert {r["value"] for r in rows if r["district"] == "Nicobars" and r["ind"] == "anaemia_women"} == {35.9}  # (35.9) = small base, kept


def test_nfhs_long_table_rounds(tmp_path):
    f = tmp_path / "long.csv"
    f.write_text("Indicator,Geography,Geo Level,Round,Value,Parent State\n"
                 "Women age 15 years and above with high or very high blood sugar or taking medicine,Pune,District,NFHS-6,14.8,Maharashtra\n"
                 "Men age 15 years and above with elevated blood pressure or taking medicine,Maharashtra,State,NFHS-6,26.1,\n"
                 "Some other indicator,Pune,District,NFHS-6,1,Maharashtra\n")
    rows = hs.parse_nfhs(f)
    assert len(rows) == 2
    d = next(r for r in rows if r["level"] == "district")
    assert (d["ind"], d["round"], d["district"], d["state"], d["value"]) == ("sugar_women", "NFHS-6", "Pune", "Maharashtra", 14.8)
    s = next(r for r in rows if r["level"] == "state")
    assert (s["ind"], s["state"]) == ("bp_men", "Maharashtra")


def test_idsp_tables_and_pdf(tmp_path):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors

    data = [["Unique ID", "Name of State/UT", "Name of District", "Disease/ Illness", "No. of Cases", "No. of Deaths",
             "Date of start of outbreak", "Date of reporting", "Current Status"],
            ["MH/PUN/2026/31/1101", "Maharashtra", "Pune", "Dengue", "23", "0", "28-07-26", "02-08-26", "Under Control"],
            ["UP/BAL/2026/31/1102", "Uttar Pradesh", "Ballia", "Acute Diarrhoeal Disease", "41", "1", "30-07-26", "01-08-26", "Under Surveillance"],
            ["KL/TSR/2026/31/1103", "Kerala", "Thrissur", "Leptospirosis", "6", "2", "25-07-26", "03-08-26", "Under Control"]]
    pdf = tmp_path / "31st_week_2026.pdf"
    doc = SimpleDocTemplate(str(pdf), pagesize=landscape(A4))
    t = Table(data)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    doc.build([Paragraph("Disease outbreaks reported during 31st week of 2026", getSampleStyleSheet()["Normal"]), t])
    rows = hs.parse_idsp_pdf(pdf)
    assert [r["disease_key"] for r in rows] == ["Dengue", "Acute diarrhoeal disease", "Leptospirosis"]
    assert rows[1]["cases"] == 41 and rows[1]["deaths"] == 1 and rows[1]["start"] == "2026-07-30" and rows[1]["district"] == "Ballia"
    assert rows[0]["week"] == "2026-W31" and rows[0]["id"] == "MH/PUN/2026/31/1101"


def test_comtrade_normalise():
    raw = [{"reporterCode": 699, "period": 2024, "flowCode": "X", "cmdCode": "3004", "partnerCode": 842, "partnerDesc": "USA",
            "partnerISO": "USA", "primaryValue": 9.1e9, "netWgt": 1.2e8, "customsCode": "C00", "motCode": 0, "partner2Code": 0},
           {"reporterCode": 699, "period": 2024, "flowCode": "M", "cmdCode": "2941", "partnerCode": 156, "partnerDesc": "China",
            "partnerISO": "CHN", "primaryValue": 1.1e9, "netWgt": None, "customsCode": "C00", "motCode": 0, "partner2Code": 0},
           {"reporterCode": 699, "period": 2024, "flowCode": "M", "cmdCode": "2941", "partnerCode": 156, "primaryValue": 5.0,
            "customsCode": "C00", "motCode": 1000, "partner2Code": 0}]
    rows = hs.normalise_comtrade(raw)
    assert len(rows) == 2 and rows[0]["flow"] == "export" and rows[1]["partner"] == "China" and rows[1]["net_kg"] is None


def test_nfhs_factsheet_extract_layout(tmp_path):
    """jvargh7 / pratapvardhan extracts: one value column per round; women's rows come before men's without saying so."""
    f = tmp_path / "districts.csv"
    f.write_text('"state","district","Indicator","NFHS5","NFHS4","Flag_NFHS5","Flag_NFHS4"\n'
                 '"Maharashtra","Pune","84. All women age 15-49 years who are anaemic22 (%)",51.9,50,NA,NA\n'
                 '"Maharashtra","Pune","85. All women age 15-19 years who are anaemic22 (%)",55.1,54,NA,NA\n'
                 '"Maharashtra","Pune","88. Blood sugar level - high or very high (>140 mg/dl) or taking medicine to control blood sugar level23 (%)",12.3,NA,NA,NA\n'
                 '"Maharashtra","Pune","91. Blood sugar level - high or very high (>140 mg/dl) or taking medicine to control blood sugar level23 (%)",15.1,NA,NA,NA\n'
                 '"NCT Delhi","New Delhi","88. Blood sugar level - high or very high (>140 mg/dl) or taking medicine to control blood sugar level23 (%)",20.0,NA,NA,NA\n')
    rows = hs.parse_nfhs(f)
    got = {(r["district"], r["ind"], r["round"]): r["value"] for r in rows}
    assert got == {("Pune", "anaemia_women", "NFHS-5"): 51.9, ("Pune", "anaemia_women", "NFHS-4"): 50.0,
                   ("Pune", "sugar_women", "NFHS-5"): 12.3, ("Pune", "sugar_men", "NFHS-5"): 15.1,
                   ("New Delhi", "sugar_women", "NFHS-5"): 20.0}
    assert {r["state"] for r in rows} == {"Maharashtra", "Delhi"}

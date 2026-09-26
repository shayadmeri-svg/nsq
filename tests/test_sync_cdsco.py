"""sync_cdsco: CDSCO JSON rows are appended to the cumulative CSV once."""
import csv
import json
import subprocess
import sys
from pathlib import Path

LOADER = Path(__file__).resolve().parent.parent / "redis-loader"
HEADER = ["Index", "Name of Product", "Batch No", "Mfg", "Exp", "Manufactured By", "NSQ Result",
          "Reporting Source", "Reporting by Lab/State", "Reporting Month & Year", "Source"]


def _run(*args):
    return subprocess.run([sys.executable, "sync_cdsco.py", *map(str, args)], cwd=LOADER, capture_output=True, text=True)


def test_appends_new_rows_once_and_normalises_month(tmp_path):
    cum = tmp_path / "cum.csv"
    with open(cum, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerow(["1", "Paracetamol Tablets IP 500 mg", "B1", "Jan-2026", "Dec-2027", "M/s X, Baddi", "Assay",
                    "CDSCO lab", "CDL, Kolkata", "Jul-2026", "https://cdsco.gov.in"])
    payload = {"aaData": [
        {"str_product_name": "Paracetamol Tablets IP 500 mg", "str_batch_no": "B1", "dt_manufacturing_date": "Jan-2026",
         "dt_expiry_date": "Dec-2027", "str_manufactured_by": "M/s X, Baddi", "str_nsq_result": "Assay",
         "str_reporting_source": "CDSCO lab", "str_reported_by_lab_or_state": "CDL, Kolkata", "dt_reporting_month_year": "JUL-2026"},
        {"str_product_name": "Metformin Tablets IP 500 mg", "str_batch_no": "M9", "dt_manufacturing_date": "Feb-2026",
         "dt_expiry_date": "Jan-2028", "str_manufactured_by": "M/s Y, Solan", "str_nsq_result": "Dissolution",
         "str_reporting_source": "State lab", "str_reported_by_lab_or_state": "RDTL, Chandigarh", "dt_reporting_month_year": "AUG-2026"},
    ]}
    src = tmp_path / "cdsco.json"
    src.write_text(json.dumps(payload))

    r = _run("--csv", cum, "--from-json", src)
    assert r.returncode == 0, r.stderr
    assert "added 1 new" in r.stdout
    rows = list(csv.DictReader(open(cum)))
    assert len(rows) == 2 and rows[-1]["Reporting Month & Year"] == "Aug-2026" and rows[-1]["Index"] == "2"

    r = _run("--csv", cum, "--from-json", src)
    assert "added 0 new" in r.stdout and len(list(csv.DictReader(open(cum)))) == 2


def test_missing_csv_without_redis_fails_clearly(tmp_path):
    r = subprocess.run([sys.executable, "sync_cdsco.py", "--csv", str(tmp_path / "none.csv"), "--bootstrap-only"],
                       cwd=LOADER, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 1 and "not found" in r.stderr

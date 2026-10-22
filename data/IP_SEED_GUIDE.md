# Entering Indian Pharmacopoeia limits in `ip_seed.json`

One entry per monograph, entered from the licensed IP edition. The loader (`redis-loader/sources/ip.py`, the
"Indian Pharmacopoeia (limits seed)" job) checks every entry against the rules below and reports what fails; an
entry with an error is not loaded.

## The entry

```json
"telmisartan": {
  "monographs": [{
    "title": "Telmisartan Tablets",
    "form": "tablets",
    "ingredients": ["Telmisartan"],
    "combination": false,
    "reference": {"edition": "IP 2022", "volume": "III", "page": "3727–3728", "monograph": "Telmisartan Tablets"},
    "usual_strengths_mg": [20, 40, 80],
    "assay": {"lo": 90.0, "hi": 110.0},
    "dissolution": {"apparatus": "paddle", "volume_ml": 900, "medium": "phosphate buffer pH 7.5", "ph": 7.5,
                    "rpm": 75, "time_min": 30, "q_pct": 75, "conditions_given": true},
    "related_substances": {"any_secondary_pct_max": 0.5, "total_pct_max": 2.0},
    "verified": {"by": "A. Sharma", "on": "2026-10-23", "against": "IP 2022 print, vol. III"}
  }]
}
```

## Rules

1. **Key**: the molecule's INN in lowercase, words joined by `_` (`paracetamol`, `amlodipine`, `tranexamic_acid`).
   Not the US name, not the salt. The loader maps it to the tracked molecule (salts, INN/USAN pairs and synonyms
   are resolved for you).
2. **Title**: the monograph title as printed (`Amlodipine Besilate Tablets`).
3. **Form**: one of `tablets`, `film-coated tablets`, `dispersible tablets`, `chewable tablets`, `capsules`,
   `prolonged-release tablets`, `gastro-resistant tablets`, `oral suspension`, `injection`… Only immediate-release
   tablets and capsules feed the tablet models; enter the others anyway.
4. **Combinations** (`Paracetamol and Caffeine Tablets`): one entry under the first ingredient's key, every
   ingredient in `ingredients`, `"combination": true`. They are never applied to a single-ingredient product.
5. **Reference**: edition, volume (roman, as printed), and the **printed page number** at the foot of the page —
   not the PDF's page index. A monograph spanning two pages: `"3197–3198"`.
6. **Numbers are numbers**: `95.0`, not `"95.0 per cent"` or `"95%"`. Units are fixed by the field name:
   percentages in `_pct`, minutes in `_min`, millilitres in `_ml`, milligrams in `_mg`, ppm in `_ppm`.
7. **Assay**: from "contain not less than X per cent and not more than Y per cent of the stated amount" → `lo` X,
   `hi` Y.
8. **Dissolution**:
   - apparatus: `Apparatus No. 1 (Basket)` → `basket`, `Apparatus No. 2 (Paddle)` → `paddle`.
   - `volume_ml`, `rpm`, `time_min` from "Medium. 900 ml …" and "Speed and time. 50 rpm and 30 minutes".
   - `medium`: a short name (`phosphate buffer pH 6.8`, `0.1 M hydrochloric acid`, `water`).
   - `ph`: from the medium. 0.1 M HCl → `1.2`; 0.01 M HCl → `2.0`; a buffer → its stated pH; water → `null`.
   - `q_pct`: from "Q. Not less than X per cent" (older editions: "D. Not less than X per cent" — same meaning).
   - Two time points or strength-specific limits: the first in the main fields, all of them in
     `"variants": [{"time_min": 30, "q_pct": 80, "strengths_mg": [500]}, …]`.
   - `"conditions_given": true` when apparatus, volume, speed and time are all stated.
   - No dissolution test in the monograph (disintegration only): leave `dissolution` out and enter
     `"disintegration": {"max_min": 15}` if a time is stated.
9. **A test the monograph does not have**: leave the field out. Never enter `0`, a guess or a value from another
   pharmacopoeia — the limits chain falls through to the next source by itself.
10. **No monograph text**: numbers and references only. A `text` field, if any, is your own one-line summary.
11. **OCR**: the PDF is scanned, so read every number against the page image. Common misreads: `1 ¡0.0` for
    `110.0`, `O` for `0`, `l` or `I` for `1`, a dropped decimal point (`950` for `95.0`), `rn` for `m`,
    `ml` vs `mg`. Telmisartan's assay upper limit is such a case.
12. **Verified**: who checked the entry against the edition, and when. Entries without it load but are reported.

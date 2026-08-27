"""Lockstep + regression tests for the manufacturer ontology normalizer.

The ontology logic is duplicated across 6 files that MUST stay in lockstep:

    shared/company_ontology.py
    analytics/shared/company_ontology.py
    engine/shared/company_ontology.py
    simulator/intelligence/company_ontology.py
    simulator/shared/company_ontology.py
    redis-loader/load_csv_redis.py        (inlines _normalize/_similarity)

These tests make drift a CI failure rather than a latent bin-contamination
bug, and lock in the determinism invariant: the canonical bin for a
manufacturer name is a pure function of the name string (and, for merges,
of name similarity >= FUZZY_THRESHOLD) — independent of insertion order,
Redis state, or alias history.

Runnable both as `python tests/test_ontology_lockstep.py` and via pytest.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# (relative_path, normalize_fn_name, similarity_fn_name)
ONT_COPIES = [
    ("shared/company_ontology.py", "normalize_company_name", "_similarity"),
    ("analytics/shared/company_ontology.py", "normalize_company_name", "_similarity"),
    ("engine/shared/company_ontology.py", "normalize_company_name", "_similarity"),
    ("simulator/intelligence/company_ontology.py", "normalize_company_name", "_similarity"),
    ("simulator/shared/company_ontology.py", "normalize_company_name", "_similarity"),
]
REDIS_LOADER = ("redis-loader/load_csv_redis.py", "_normalize", "_similarity")

# Regression corpus: (raw, expected_normalized_key). Covers legal-stop,
# address-tail termination, sector-noise drop, city/state break, and the
# specific contamination cases that motivated this test.
CORPUS = [
    ("Hindustan Antibiotics Ltd", "hindustan antibiotics"),
    ("Hindustan Laboratories Ltd", "hindustan"),
    ("Hindustan Antibiotics Pvt Ltd", "hindustan antibiotics"),
    ("Regent Ajanta Biotech", "regent ajanta"),
    # Same manufacturer, different raw spellings / address fragments —
    # ALL must bin to the same key so the dashboard (which groups on the
    # bin via _mfg_group_label) collapses them to one row.
    ("Regent Ajanta Biotech 86-87", "regent ajanta"),
    ("M/s. Regent Ajanta Biotech", "regent ajanta"),
    ("Martin & Brown Bio-Sciences Pvt. Ltd.", "martin brown bio"),
    ("Martin And Brown Bio-Sciences Pvt. Ltd.", "martin brown bio"),
    ("Martin &Brown Bio-Sciences Pvt. Ltd.", "martin brown bio"),
    ("Jackson Laboratories Pvt. Ltd., 22-24, Majitha Road, Bye Pass Amritsar-143001 (India)", "jackson"),
    ("Aban Pharmaceuticals, Plot No. 1018, Kerala, G.I.D.C, Bavia, Distt. Ahmedabad ? 382220", "aban"),
    ("Finemax Formulation Pvt. Ltd., No-1/4, First Floor, Thirumuruga Complex, Leelavathi Nagar, Chikkarayapuram, Chenni-600069", "finemax"),
    ("M/s Jackson Laboratories Pvt. Ltd. Majitha Road", "jackson"),
    ("Cipla Pvt. Ltd. Majitha Road", "cipla"),
    ("Sun Pharmaceutical Industries Ltd", "sun"),
    ("Abbott Healthcare Pvt Ltd Mumbai", "abbott"),
    ("Lupin Pharmaceuticals Research Pvt Ltd", "lupin research"),
    ("3M India Ltd", "3m"),
    ("Unicure Remedies Pvt Ltd", "unicure"),
    ("Ajanta Pharma, Goa", "ajanta"),
]

# (a, b, expected) — "merge" means _similarity(n(a), n(b)) >= FUZZY_THRESHOLD.
SIMILARITY_CASES = [
    ("Hindustan Antibiotics Ltd", "Hindustan Laboratories Ltd", "separate"),
    ("Regent Ajanta Biotech", "Jackson Laboratories Pvt. Ltd., 22-24, Majitha Road, Bye Pass Amritsar-143001 (India)", "separate"),
    ("Hindustan Antibiotics Ltd", "Hindustan Antibiotics Pvt Ltd", "merge"),
    ("Hindustan Antibiotics Ltd", "Hindustan Antibiotics Limited", "merge"),
    ("Ajanta Pharma Ltd.", "Regent Ajanta Biotech", "separate"),
    # NOTE: both normalize to "jackson" (laboratories + pharma are sector
    # noise), so they exact-key collide -> merge. This is the known
    # generic-brand-token over-merge limitation of brand-root binning: a
    # string-only binner cannot tell "Jackson Laboratories" and "Jackson
    # Pharma" apart without keeping sector tokens, which would break
    # "Cipla" / "Cipla Pharma" merging. Out of scope for the determinism
    # fix; recorded here so a future noise-list change is a conscious
    # decision rather than a silent behavior shift.
    ("Jackson Laboratories Pvt. Ltd.", "Jackson Pharma Pvt. Ltd.", "merge"),
]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _all_modules():
    mods = []
    for i, (rel, nfn, sfn) in enumerate(ONT_COPIES):
        m = _load(rel, f"ont_{i}")
        mods.append((rel, getattr(m, nfn), getattr(m, sfn), m))
    rl = _load(REDIS_LOADER[0], "rl")
    mods.append((REDIS_LOADER[0], getattr(rl, REDIS_LOADER[1]), getattr(rl, REDIS_LOADER[2]), rl))
    return mods


def test_normalize_identical_across_copies():
    mods = _all_modules()
    ref_rel, ref_n, _, _ = mods[0]
    ref = {raw: ref_n(raw) for raw, _ in CORPUS}
    for rel, nfn, _, _ in mods[1:]:
        for raw, exp in CORPUS:
            got = nfn(raw)
            assert got == ref[raw], f"normalize drift in {rel}: {raw!r} -> {got!r} (ref {ref_rel} -> {ref[raw]!r})"
    # also assert the expected literal keys
    for raw, exp in CORPUS:
        assert ref[raw] == exp, f"normalize({raw!r}) = {ref[raw]!r}, expected {exp!r}"


def test_similarity_identical_across_copies():
    mods = _all_modules()
    ref_rel, _, ref_s, ref_mod = mods[0]
    thr = getattr(ref_mod, "FUZZY_THRESHOLD")
    raws = [a for a, _, _ in SIMILARITY_CASES] + [b for _, b, _ in SIMILARITY_CASES]
    ref_norm = {r: ref_mod.normalize_company_name(r) if hasattr(ref_mod, "normalize_company_name") else ref_mod._normalize(r) for r in raws}
    for rel, nfn, sfn, _ in mods[1:]:
        for a, b, _ in SIMILARITY_CASES:
            sa = sfn(nfn(a), nfn(b))
            sb = ref_s(ref_norm[a], ref_norm[b])
            assert abs(sa - sb) < 1e-9, f"similarity drift in {rel}: sim({a!r},{b!r})={sa} vs ref {sb}"


def test_similarity_regression():
    _, _, ref_s, ref_mod = _all_modules()[0]
    thr = getattr(ref_mod, "FUZZY_THRESHOLD")
    n = ref_mod.normalize_company_name
    for a, b, exp in SIMILARITY_CASES:
        score = ref_s(n(a), n(b))
        merged = score >= thr
        want = exp == "merge"
        assert merged == want, f"sim({a!r},{b!r})={score:.2f} thr={thr}: expected {exp}, got {'merge' if merged else 'separate'}"


def _rl():
    return _load(REDIS_LOADER[0], "rl_runner")


def test_alias_prefix_path_is_gated():
    """The alias-key prefix merge path must require similarity >= threshold.

    Regression for the order-dependent bin contamination: a later name
    whose 2/3-token prefix equals an existing key must NOT merge unless the
    normalized names are genuinely similar. Without the gate, 'Jackson
    Alpha Beta' (norm 'jackson alpha beta') would merge into an existing
    'jackson' key via the 2-token prefix at similarity ~0.
    """
    rl = _rl()
    thr = 0.85
    ont = {"jackson": {"canonical_name": "Jackson", "city": "", "state": "",
                       "website": "", "aliases": ["Jackson"], "sources": 1}}
    key, _, created = rl._resolve_or_create("Jackson Alpha Beta Ltd", "Jackson Alpha Beta Ltd", thr, ont, {})
    assert key != "jackson", f"ungated prefix merge: 'Jackson Alpha Beta' merged into 'jackson' (key={key!r})"
    assert created, f"expected a new entity, got key={key!r}"


def test_legit_prefix_merge_still_fires():
    """A prefix match whose similarity >= threshold must still merge."""
    rl = _rl()
    thr = 0.85
    ont = {"hindustan antibiotics": {"canonical_name": "Hindustan Antibiotics", "city": "", "state": "",
                                     "website": "", "aliases": ["Hindustan Antibiotics"], "sources": 1}}
    key, _, created = rl._resolve_or_create("Hindustan Antibiotics Xtra Ltd", "Hindustan Antibiotics Xtra Ltd", thr, ont, {})
    assert key == "hindustan antibiotics", f"legit prefix merge lost: key={key!r}"


def test_regent_ajanta_and_jackson_separate_both_orders():
    """The reported pair must bin separately regardless of insertion order."""
    rl = _rl()
    thr = 0.85
    regent = "Regent Ajanta Biotech"
    jackson = "Jackson Laboratories Pvt. Ltd., 22-24, Majitha Road, Bye Pass Amritsar-143001 (India)"
    for first, second in [(regent, jackson), (jackson, regent)]:
        ont = {}
        rl._resolve_or_create(first, first, thr, ont, {})
        rl._resolve_or_create(second, second, thr, ont, {})
        assert len(ont) == 2, f"order [{first[:20]!r} first] produced {len(ont)} bins, expected 2: {list(ont)}"


def test_exact_and_fuzzy_merges_preserved():
    rl = _rl()
    thr = 0.85
    # exact normalized key
    ont = {"cipla": {"canonical_name": "Cipla", "city": "", "state": "", "website": "", "aliases": ["Cipla"], "sources": 1}}
    k, _, _ = rl._resolve_or_create("Cipla Ltd.", "Cipla Ltd.", thr, ont, {})
    assert k == "cipla"
    # fuzzy
    ont = {"hindustan antibiotics": {"canonical_name": "Hindustan Antibiotics", "city": "", "state": "", "website": "", "aliases": ["Hindustan Antibiotics"], "sources": 1}}
    k, _, _ = rl._resolve_or_create("Hindustan Antibiotics Limited", "Hindustan Antibiotics Limited", thr, ont, {})
    assert k == "hindustan antibiotics"


# --- rebuild_ontology (redis-loader) ----------------------------------------
# Uses a minimal in-memory Redis stub so the rebuild path is exercised without
# a live Redis. Locks the split / re-key / collision-merge / re-stamp behavior.

import fnmatch


class _FakePipe:
    def __init__(self, store):
        self.store = store
        self.ops = []

    def delete(self, k):
        self.ops.append(("del", k))
        return self

    def hset(self, k, mapping=None, **kw):
        self.ops.append(("hset", k, mapping or kw))
        return self

    def execute(self):
        for op in self.ops:
            if op[0] == "del":
                self.store.pop(op[1], None)
            else:
                self.store.setdefault(op[1], {}).update(op[2])
        return []


class _FakeRedis:
    def __init__(self):
        self.data = {}

    def hgetall(self, k):
        return self.data.get(k, {})

    def hset(self, k, mapping=None, **kw):
        self.data.setdefault(k, {}).update(mapping or kw)

    def delete(self, k):
        self.data.pop(k, None)

    def scan_iter(self, pattern, count=None):
        for k in list(self.data.keys()):
            if fnmatch.fnmatch(k, pattern):
                yield k

    def pipeline(self):
        return _FakePipe(self.data)


def _rl_rebuild():
    rl = _load(REDIS_LOADER[0], "rl_rebuild")
    return rl


def test_rebuild_splits_contaminated_record():
    rl = _rl_rebuild()
    r = _FakeRedis()
    r.hset("nsq:ontology:companies", mapping={
        "regent": json.dumps({
            "canonical_name": "Regent Ajanta Biotech",
            "aliases": [
                "Regent Ajanta Biotech",
                "Jackson Laboratories Pvt. Ltd., 22-24, Majitha Road, Bye Pass Amritsar-143001 (India)",
            ],
            "city": "Amritsar", "state": "Punjab", "website": "", "sources": 2,
        }),
    })
    r.hset("nsq:prediction:1", mapping={
        "raw_company": "Regent Ajanta Biotech", "canonical": "Regent Ajanta Biotech",
        "ontology_key": "regent", "city": "Amritsar", "state": "Punjab",
    })
    r.hset("nsq:prediction:2", mapping={
        "raw_company": "Jackson Laboratories Pvt. Ltd., 22-24, Majitha Road, Bye Pass Amritsar-143001 (India)",
        "canonical": "Regent Ajanta Biotech", "ontology_key": "regent",
        "city": "Amritsar", "state": "Punjab",
    })
    stats = rl.rebuild_ontology(r, dry_run=False)
    keys = list(r.data["nsq:ontology:companies"].keys())
    assert "regent" not in keys, f"stale bridging key 'regent' survived: {keys}"
    assert set(keys) == {"regent ajanta", "jackson"}, f"expected split into regent ajanta + jackson, got {keys}"
    # split-away group must NOT inherit the contaminated city
    jrec = json.loads(r.data["nsq:ontology:companies"]["jackson"])
    assert jrec["city"] == "", f"split-away group kept contaminated city: {jrec}"
    # predictions re-stamped to their own bin
    assert r.data["nsq:prediction:1"]["ontology_key"] == "regent ajanta"
    assert r.data["nsq:prediction:2"]["ontology_key"] == "jackson"
    assert r.data["nsq:prediction:2"]["canonical"].startswith("Jackson")
    assert stats["split"] == 1 and stats["records_out"] == 2


def test_rebuild_rekeys_and_merges_collisions():
    rl = _rl_rebuild()
    r = _FakeRedis()
    r.hset("nsq:ontology:companies", mapping={
        "cipla": json.dumps({"canonical_name": "Cipla Ltd", "aliases": ["Cipla Ltd", "Cipla Limited"],
                              "city": "Mumbai", "state": "Maharashtra", "sources": 2}),
        "regent": json.dumps({"canonical_name": "Regent Ajanta Biotech", "aliases": ["Regent Ajanta Biotech"],
                               "city": "", "state": "", "sources": 1}),
        "hindustan antibiotics": json.dumps({"canonical_name": "Hindustan Antibiotics",
                                              "aliases": ["Hindustan Antibiotics Ltd"], "city": "Pune",
                                              "state": "Maharashtra", "sources": 1}),
        "hindustan antibiotics ltd": json.dumps({"canonical_name": "Hindustan Antibiotics Ltd",
                                                 "aliases": ["Hindustan Antibiotics Limited"], "city": "",
                                                 "state": "", "sources": 1}),
    })
    rl.rebuild_ontology(r, dry_run=False)
    keys = list(r.data["nsq:ontology:companies"].keys())
    assert "cipla" in keys
    assert "regent ajanta" in keys and "regent" not in keys          # re-keyed
    assert "hindustan antibiotics" in keys and "hindustan antibiotics ltd" not in keys  # collision merged
    ha = json.loads(r.data["nsq:ontology:companies"]["hindustan antibiotics"])
    assert "Hindustan Antibiotics Ltd" in ha["aliases"]
    assert "Hindustan Antibiotics Limited" in ha["aliases"]
    assert ha["city"] == "Pune"                                      # geo kept on the old-key owner


def test_rebuild_dry_run_does_not_write():
    rl = _rl_rebuild()
    r = _FakeRedis()
    r.hset("nsq:ontology:companies", mapping={
        "regent": json.dumps({"canonical_name": "Regent Ajanta Biotech", "aliases": ["Regent Ajanta Biotech"], "sources": 1}),
    })
    before = json.dumps(r.data, sort_keys=True)
    rl.rebuild_ontology(r, dry_run=True)
    after = json.dumps(r.data, sort_keys=True)
    assert before == after, "dry_run mutated Redis"


if __name__ == "__main__":
    fns = [v for v in globals().values() if callable(v) and v.__name__.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
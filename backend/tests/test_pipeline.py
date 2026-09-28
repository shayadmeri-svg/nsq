from __future__ import annotations


def test_full_refresh_dag():
    from app import datamap, pipeline

    g = pipeline.graph({})
    pos = {t: i for i, t in enumerate(g["order"])}
    assert len(pos) == len(g["tasks"])  # acyclic: every task placed
    ids = {n["id"] for n in datamap.NODES}
    assert all(a["node"] in ids for a in g["artifacts"].values())  # every artifact is on the data map
    before = lambda a, b: pos[a] < pos[b]  # noqa: E731
    assert before("nsq-load", "nsq-products") and before("nsq-products", "nsq-frame")
    assert before("universe-candidates", "src-clinical-trials") and before("src-clinical-trials", "universe-build")
    assert before("universe-build", "load-cdmo") and before("load-cdmo", "persist-cdmo")
    assert before("plants-seed", "plants-user") and before("nsq-load", "geo")
    assert g["order"][-1] in ("serve-warm", "persist-upstash")
    t = {x["id"]: x for x in g["tasks"]}
    assert t["src-cdsco-wc"]["skip"] and t["src-ord"]["skip"]
    assert not pipeline.graph({"include_ord": True})["tasks"][[x["id"] for x in g["tasks"]].index("src-ord")]["skip"]
    down = pipeline.descendants(g, "nsq-load")
    assert {"nsq-frame", "universe-build", "load-cdmo", "serve-warm"} <= down and "src-orange-book" not in down
    assert pipeline.states_from_log("x\n◆ nsq-load → failed\n◆ geo → skipped · upstream X failed\n") == {
        "nsq-load": {"state": "failed", "note": ""}, "geo": {"state": "skipped", "note": "upstream X failed"}}


def test_full_refresh_plan_endpoint(root):
    from conftest import H  # noqa: F401
    r = root.get("/api/jobs/full-refresh/plan").json()
    assert r["job"]["key"] == "full-refresh" and r["layers"] and r["allowed"]

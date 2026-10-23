"""Write edge-agent/sim_machines.json: every equipment type the simulator serves generically (object, variables,
typical ranges), from the catalogue, so the simulator and the machine-model profiles name the same tags.
Run after changing connect/app/equipment.py:  python connect/export_sim_machines.py"""
import json
from pathlib import Path

from app import catalog, lines

LINE = {"rmg", "fbd", "blender", "press", "coater", "autoclave", "hvac_room"}  # simulated with their own physics
out = []
for t in catalog.EQUIPMENT_TYPES:
    if t["id"] in LINE:
        continue
    obj, tags = catalog.sim_tags(t["id"])
    out.append({"type": t["id"], "name": f"{t['id'].upper().replace('_', '-')}-1", "object": obj, "batch": t["batch"],
                "signals": [{"field": s["id"], "var": tags[s["id"]], "typical": s["typical"]} for s in t["signals"]]})
# every type's signals, so the API can offer any machine set up in Connect in the Sim engine, and the simulator serve it
types = {t["id"]: {"label": t["label"], "batch": t["batch"],
                   "signals": [{"field": s["id"], "var": catalog._camel(s["id"]), "label": s["label"], "unit": s["unit"], "typical": s["typical"]}
                               for s in t["signals"]]} for t in catalog.EQUIPMENT_TYPES}
s7 = catalog.S7_SIM
(Path(__file__).resolve().parents[1] / "edge-agent" / "sim_machines.json").write_text(
    json.dumps({"machines": out, "types": types, "s7": {**s7, "object": catalog.sim_tags(s7["type"])[0]},
                # the dedicated lines' machines: line, order, minutes per batch, product, and what each signal sends
                "lines": {n: {k: m[k] for k in ("line", "position", "minutes", "product", "sim")} for n, m in lines.MACHINES.items()}}, indent=1) + "\n", encoding="utf-8")
print(len(out), "machines")

"""The demo plant: one oral-solid line with five machines (from the simulator's verified profiles) and two products
sharing four of them — paracetamol (uncoated) and azithromycin (film-coated, adds the coater).

Ranges marked DEMO are illustrative settings for the simulated line, to be replaced with a plant's validated ranges;
the weight-uniformity range is the pharmacopoeial one.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import catalog
from .auth import token_hash
from .models import Agent, Equipment, Plant, Product

DEMO_ORG = os.environ.get("PLANT_SIM_ORG", "") or "eurveda-demo"
DEMO = "Demo setting for the simulated line — replace with your validated range"
UOW = "Uniformity of weight: ±5 % for tablets over 250 mg (Ph. Eur. 2.9.5 / IP)"
SIM_ENDPOINT = "opc.tcp://localhost:4840/eurveda-sim/"
SIM_POLL_S = float(os.environ.get("CONNECT_SIM_POLL_S", "1"))  # the simulator updates every second: read it as often


def _p(ideal: float, lo: float, hi: float, check: str = "continuous", source: str = DEMO) -> dict[str, Any]:
    return {"ideal": ideal, "lo": lo, "hi": hi, "check": check, "source": source}


def seed_demo(db: Session) -> None:
    plant = db.scalar(select(Plant).where(Plant.org_slug == DEMO_ORG))
    token = os.environ.get("PLANT_SIM_TOKEN", "")
    if plant is None:
        plant = Plant(org_slug=DEMO_ORG, name="Demo plant · Oral solids line 1", location="Simulated (Eurveda plant simulator)")
        db.add(plant)
        db.flush()
        agent = None
        if token:
            agent = Agent(plant_id=plant.id, name="Demo simulator agent", token_hash=token_hash(token), token_hint=token[:10], info={})
            db.add(agent)
            db.flush()
        eq = {}
        for i, (name, prof, make) in enumerate([("RMG-1", "eurveda-sim-rmg", "Simulated RMG"), ("FBD-1", "eurveda-sim-fbd", "Simulated FBD"),
                                                ("BLENDER-1", "eurveda-sim-blender", "Simulated blender"), ("PRESS-1", "eurveda-sim-press", "Simulated press"),
                                                ("COATER-1", "eurveda-sim-coater", "Simulated pan coater")]):
            p = catalog.PROFILE_BY_ID[prof]
            e = Equipment(plant_id=plant.id, name=name, type=p["type"], position=i, make=make, model="Eurveda simulator", protocol="opcua",
                          connection={"endpoint": SIM_ENDPOINT, "poll_s": SIM_POLL_S}, tag_map=dict(p["tags"]), batch_tag=p["batch_tag"],
                          product_tag=p["product_tag"], agent_id=agent.id if agent else None, profile_id=prof)
            db.add(e)
            db.flush()
            eq[name] = e.id
        db.add(Product(plant_id=plant.id, name="Paracetamol Tablets IP 500 mg", molecule_key="paracetamol", dosage_form="tablet",
                       codes=["PCM500"], color="#06a7c4", route=[
            {"equipment_id": eq["RMG-1"], "params": {"binder_kg": _p(25, 22, 28, "end"), "wet_mix_min": _p(4, 3, 5, "end")}},
            {"equipment_id": eq["FBD-1"], "params": {"inlet_c": _p(60, 55, 65), "lod_pct": _p(1.8, 0.5, 3.0, "end"), "air_m3_h": _p(3000, 2700, 3300)}},
            {"equipment_id": eq["BLENDER-1"], "params": {"blend_min": _p(5, 4, 6, "end")}},
            {"equipment_id": eq["PRESS-1"], "params": {"force_kn": _p(13, 10, 16), "tablet_weight_mg": _p(650, 617.5, 682.5, source=UOW)}},
        ]))
        db.add(Product(plant_id=plant.id, name="Azithromycin Tablets IP 500 mg", molecule_key="azithromycin", dosage_form="film-coated tablet",
                       codes=["AZI500"], color="#6366f1", route=[
            {"equipment_id": eq["RMG-1"], "params": {"binder_kg": _p(22, 19, 26, "end"), "wet_mix_min": _p(5, 4, 6, "end")}},
            {"equipment_id": eq["FBD-1"], "params": {"inlet_c": _p(55, 50, 60), "lod_pct": _p(3.5, 2.0, 5.0, "end"), "air_m3_h": _p(3000, 2700, 3300)}},
            {"equipment_id": eq["BLENDER-1"], "params": {"blend_min": _p(6, 5, 7, "end")}},
            {"equipment_id": eq["PRESS-1"], "params": {"force_kn": _p(15, 12, 18), "tablet_weight_mg": _p(760, 722, 798, source=UOW)}},
            {"equipment_id": eq["COATER-1"], "params": {"weight_gain_pct": _p(3.0, 2.5, 3.5, "end"), "coat_inlet_c": _p(60, 55, 65),
                                                       "exhaust_c": _p(42, 38, 46), "spray_g_min": _p(120, 90, 150), "pan_rpm": _p(8, 6, 10),
                                                       "atomizing_bar": _p(2.0, 1.5, 2.5)}},
        ]))
        db.commit()
    elif token and db.scalar(select(Agent).where(Agent.token_hash == token_hash(token))) is None:
        a = Agent(plant_id=plant.id, name="Demo simulator agent", token_hash=token_hash(token), token_hint=token[:10], info={})
        db.add(a)
        db.flush()
        for e in db.scalars(select(Equipment).where(Equipment.plant_id == plant.id, Equipment.agent_id.is_(None))):
            e.agent_id = a.id
        db.commit()
    # simulator machines still on the old 5-second default read every SIM_POLL_S (a value someone set is left alone)
    changed = False
    for e in db.scalars(select(Equipment).where(Equipment.plant_id == plant.id, Equipment.profile_id.like("eurveda-sim-%"))):
        if float((e.connection or {}).get("poll_s") or 5) == 5 and SIM_POLL_S != 5:
            e.connection = {**(e.connection or {}), "poll_s": SIM_POLL_S}
            changed = True
    if changed:
        db.commit()

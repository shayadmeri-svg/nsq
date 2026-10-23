"""The equipment a pharmaceutical plant runs, by area: what each kind of machine reports and who makes it.

Each type lists the signals Eurveda understands (the field ids Plant data uses, core/chem/batch_data.py, for the
process machines), their units and typical range, and name hints that suggest a tag mapping from a machine's own tag
names. `batch` says whether the machine processes batches (a batch number to read) or runs continuously (utilities,
rooms). `makers` are established manufacturers of that kind of machine, offered when the machine is added; the model
is typed as on its nameplate. A tag map for one model is kept as a machine-model profile once it has been read from
that machine (catalog.PROFILES and the profiles a plant saves), never guessed from a brochure.
"""

from __future__ import annotations

from typing import Any

AREAS = [
    ("dispensing", "Dispensing & weighing"),
    ("granulation", "Sifting, milling & granulation"),
    ("compression", "Blending, compression & coating"),
    ("packaging", "Packaging & serialisation"),
    ("liquids", "Liquids & semisolids"),
    ("sterile", "Sterile manufacturing"),
    ("utilities", "Water, steam, air & HVAC"),
    ("storage", "Storage & stability"),
    ("qc", "QC laboratory"),
]


def _s(id: str, label: str, unit: str, lo: float, hi: float, hints: str, key: bool = False) -> dict[str, Any]:
    return {"id": id, "label": label, "unit": unit, "typical": [lo, hi], "hints": hints, "key": key}


def _t(id: str, label: str, area: str, stage: str, forms: list[str], signals: list[dict[str, Any]], makers: list[str],
       batch: bool = True) -> dict[str, Any]:
    return {"id": id, "label": label, "area": area, "stage": stage, "dosage_forms": forms, "signals": signals, "makers": makers, "batch": batch}


SOLID = ["tablet", "film-coated tablet", "capsule"]
TAB = ["tablet", "film-coated tablet"]
LIQ = ["oral liquid", "injectable"]
ALL = ["tablet", "film-coated tablet", "capsule", "oral liquid", "injectable"]
STERILE = ["injectable"]

EQUIPMENT_TYPES: list[dict[str, Any]] = [
    # --- dispensing & weighing ------------------------------------------------------------------------------------
    _t("dispensing_booth", "Dispensing / sampling booth (RLAF)", "dispensing", "Dispensing", ALL, [
        _s("downflow_m_s", "Downflow air velocity", "m/s", 0.3, 0.6, r"velocity|downflow|air.?speed", True),
        _s("hepa_dp_pa", "HEPA filter differential pressure", "Pa", 50, 450, r"hepa|filter|\bdp\b"),
        _s("booth_c", "Booth temperature", "°C", 18, 27, r"temp|tt"),
        _s("booth_rh_pct", "Booth humidity", "%RH", 30, 65, r"\brh\b|humid")],
       ["Esco", "Klenzaids", "Germfree"], batch=False),
    _t("balance", "Weighing balance / floor scale", "dispensing", "Dispensing", ALL, [
        _s("weight_kg", "Net weight", "kg", 0, 1000, r"net|weight|wt", True),
        _s("tare_kg", "Tare", "kg", 0, 100, r"tare")],
       ["Mettler-Toledo", "Sartorius", "Minebea Intec", "Shimadzu", "A&D"]),
    # --- sifting, milling & granulation ---------------------------------------------------------------------------
    _t("sifter", "Vibro sifter", "granulation", "Sifting", SOLID, [
        _s("throughput_kg_h", "Throughput", "kg/h", 20, 1500, r"through|rate|kg.?h", True),
        _s("motor_a", "Motor current", "A", 0, 15, r"current|amp|\ba\b"),
        _s("run_min", "Run time", "min", 0, 120, r"run|time|elapsed")],
       ["Russell Finex", "Gansons", "Kevin Process Technologies", "Sweco", "Allgaier"]),
    _t("mill", "Multimill / conical mill", "granulation", "Milling", SOLID, [
        _s("rotor_rpm", "Rotor / impeller speed", "rpm", 300, 4500, r"rotor|impeller|rpm|speed", True),
        _s("motor_kw", "Motor power", "kW", 0, 15, r"power|kw|load"),
        _s("feed_kg_h", "Feed rate", "kg/h", 10, 1000, r"feed|rate"),
        _s("screen_mm", "Screen size", "mm", 0.5, 8, r"screen|mesh|sieve")],
       ["Quadro (IDEX)", "Frewitt", "Fitzpatrick", "Hosokawa", "Gansons"]),
    _t("rmg", "Rapid mixer granulator", "granulation", "Granulation", SOLID, [
        _s("binder_kg", "Binder solution added", "kg", 5, 60, r"binder|solution|liquid|water.?add", True),
        _s("dry_mix_kg", "Dry mix", "kg", 20, 300, r"dry.?mix|batch.?size|load"),
        _s("wet_mix_min", "Wet mixing time", "min", 0.5, 15, r"wet.?mix|knead"),
        _s("impeller_kw", "Impeller power", "kW", 0, 30, r"impeller|power|kw|load")],
       ["Diosna", "GEA (Collette)", "Glatt", "L.B. Bohle", "Gansons", "Kevin Process Technologies", "Bectochem"]),
    _t("fbd", "Fluid-bed dryer", "granulation", "Drying", SOLID, [
        _s("lod_pct", "Loss on drying", "%", 0, 25, r"\blod\b|moist", True),
        _s("inlet_c", "Inlet air temperature", "°C", 25, 95, r"inlet.?t|supply.?t|tt.?1?01", True),
        _s("outlet_c", "Outlet air temperature", "°C", 20, 80, r"outlet|exhaust"),
        _s("product_c", "Product temperature", "°C", 20, 70, r"product|bed"),
        _s("inlet_rh_pct", "Inlet relative humidity", "%", 0, 90, r"\brh\b|humid"),
        _s("air_m3_h", "Air flow", "m³/h", 500, 6000, r"air.?flow|cmh|airflow"),
        _s("elapsed_min", "Elapsed drying time", "min", 0, 180, r"elapsed|timer|run.?time")],
       ["Glatt", "GEA (Aeromatic-Fielder)", "Gansons", "Kevin Process Technologies", "Freund-Vector", "L.B. Bohle", "Diosna"]),
    _t("fbp", "Fluid-bed processor (granulating / Wurster coating)", "granulation", "Granulation", SOLID, [
        _s("product_c", "Product temperature", "°C", 20, 60, r"product|bed", True),
        _s("spray_g_min", "Spray rate", "g/min", 10, 800, r"spray", True),
        _s("inlet_c", "Inlet air temperature", "°C", 30, 90, r"inlet"),
        _s("exhaust_c", "Exhaust temperature", "°C", 20, 60, r"exhaust|outlet"),
        _s("atomizing_bar", "Atomizing air pressure", "bar", 0.5, 4, r"atomi|aap"),
        _s("air_m3_h", "Process air flow", "m³/h", 300, 8000, r"air.?flow|cmh"),
        _s("filter_dp_pa", "Filter differential pressure", "Pa", 200, 3000, r"filter|\bdp\b")],
       ["Glatt", "GEA (Aeromatic-Fielder)", "Freund-Vector", "Gansons", "Kevin Process Technologies", "Diosna"]),
    _t("tray_dryer", "Tray dryer", "granulation", "Drying", SOLID, [
        _s("chamber_c", "Chamber temperature", "°C", 30, 90, r"temp|chamber", True),
        _s("elapsed_min", "Drying time", "min", 0, 720, r"elapsed|time")],
       ["Gansons", "Kevin Process Technologies"]),
    _t("roller_compactor", "Roller compactor", "granulation", "Dry granulation", SOLID, [
        _s("roll_force_kn_cm", "Roll force", "kN/cm", 2, 20, r"force|press", True),
        _s("roll_gap_mm", "Roll gap", "mm", 1, 6, r"gap", True),
        _s("roll_rpm", "Roll speed", "rpm", 1, 20, r"roll.?s|roll.?rpm"),
        _s("screw_rpm", "Feed screw speed", "rpm", 5, 150, r"screw|feed")],
       ["Gerteis", "Alexanderwerk", "Freund-Vector", "Fitzpatrick"]),
    # --- blending, compression & coating --------------------------------------------------------------------------
    _t("blender", "Blender (octagonal, bin, V, double-cone)", "compression", "Blending", SOLID, [
        _s("blend_min", "Blend time", "min", 0.5, 40, r"blend|mix.?time|lube", True),
        _s("blender_rpm", "Blender speed", "rpm", 2, 40, r"rpm|speed")],
       ["L.B. Bohle", "Servolift", "GEA", "Gansons", "Bectochem", "Kevin Process Technologies"]),
    _t("press", "Tablet press", "compression", "Compression", TAB, [
        _s("force_kn", "Main compression force", "kN", 1, 60, r"main.?force|compression|mcf|\bforce", True),
        _s("tablet_weight_mg", "Tablet weight", "mg", 100, 1500, r"weight|\bwt\b", True),
        _s("precompression_kn", "Pre-compression force", "kN", 0, 10, r"pre.?comp|pcf"),
        _s("press_rpm", "Turret speed", "rpm", 5, 90, r"turret|speed|rpm"),
        _s("punch_diameter_mm", "Punch diameter", "mm", 5, 25, r"punch|dia")],
       ["Fette Compacting", "Korsch", "Romaco Kilian", "GEA (Courtoy)", "IMA", "ACG", "Cadmach", "Sejong Pharmatech", "Natoli"]),
    _t("deduster_md", "Deduster & metal detector", "compression", "Compression", TAB, [
        _s("rejects", "Rejected tablets", "count", 0, 500, r"reject", True),
        _s("throughput_tph", "Throughput", "tablets/h", 10000, 500000, r"through|output|rate")],
       ["Mettler-Toledo (Safeline)", "Loma", "CEIA", "Kraemer"]),
    _t("capsule_filler", "Capsule filler", "compression", "Encapsulation", ["capsule"], [
        _s("fill_weight_mg", "Fill weight", "mg", 50, 1000, r"fill.?w|weight", True),
        _s("filler_speed_cph", "Speed", "capsules/h", 1000, 200000, r"speed|output|cph")],
       ["ACG", "Syntegon (Bosch)", "IMA", "MG2", "Harro Höfliger", "Sejong Pharmatech"]),
    _t("coater", "Pan coater", "compression", "Coating", ["film-coated tablet"], [
        _s("weight_gain_pct", "Coating weight gain", "%", 0, 6, r"weight.?gain|gain", True),
        _s("coat_inlet_c", "Inlet air temperature", "°C", 30, 80, r"inlet.?t|supply", True),
        _s("exhaust_c", "Exhaust temperature", "°C", 25, 60, r"exhaust|outlet"),
        _s("spray_g_min", "Spray rate", "g/min", 10, 400, r"spray"),
        _s("pan_rpm", "Pan speed", "rpm", 1, 20, r"pan|drum|rpm"),
        _s("atomizing_bar", "Atomizing air pressure", "bar", 0.5, 4, r"atomi|aap")],
       ["ACG", "Glatt", "O'Hara Technologies", "L.B. Bohle", "Freund-Vector", "Thomas Engineering", "GEA", "Gansons"]),
    # --- packaging & serialisation --------------------------------------------------------------------------------
    _t("blister", "Blister packing machine", "packaging", "Primary packing", SOLID, [
        _s("sealing_c", "Sealing temperature", "°C", 140, 230, r"seal", True),
        _s("forming_c", "Forming temperature", "°C", 100, 170, r"form"),
        _s("speed_cpm", "Speed", "cycles/min", 10, 600, r"speed|cpm|bpm"),
        _s("rejects", "Rejected blisters", "count", 0, 500, r"reject")],
       ["Uhlmann", "Marchesini", "IMA", "Romaco Noack", "ACG Pampac", "Syntegon (Bosch)", "CAM"]),
    _t("strip_packing", "Strip packing machine", "packaging", "Primary packing", SOLID, [
        _s("sealing_c", "Sealing temperature", "°C", 120, 220, r"seal", True),
        _s("speed_cpm", "Speed", "strips/min", 10, 300, r"speed")],
       ["ACG Pampac", "Marchesini"]),
    _t("bottle_line", "Bottle line (counter, capper, induction sealer)", "packaging", "Primary packing", ALL, [
        _s("capping_torque_ncm", "Capping torque", "N·cm", 50, 400, r"torque", True),
        _s("count_per_bottle", "Count per bottle", "units", 10, 1000, r"count"),
        _s("induction_kw", "Induction sealer power", "kW", 0.5, 6, r"induct|seal"),
        _s("speed_bpm", "Speed", "bottles/min", 10, 300, r"speed|bpm")],
       ["Marchesini", "IMA", "Syntegon (Bosch)", "Romaco"]),
    _t("cartonator", "Cartonator", "packaging", "Secondary packing", ALL, [
        _s("speed_cpm", "Speed", "cartons/min", 10, 500, r"speed|cpm", True),
        _s("rejects", "Rejected cartons", "count", 0, 200, r"reject")],
       ["Uhlmann", "Marchesini", "IMA", "Romaco Promatic", "ACG Pampac"]),
    _t("checkweigher", "Checkweigher", "packaging", "Secondary packing", ALL, [
        _s("gross_g", "Gross weight", "g", 1, 5000, r"gross|weight", True),
        _s("rejects", "Rejected packs", "count", 0, 200, r"reject"),
        _s("speed_ppm", "Speed", "packs/min", 10, 600, r"speed|ppm")],
       ["Mettler-Toledo", "Minebea Intec", "Ishida", "Wipotec"]),
    _t("serialization", "Serialisation & aggregation (track and trace)", "packaging", "Secondary packing", ALL, [
        _s("codes_printed", "Codes printed", "count", 0, 1e6, r"print", True),
        _s("codes_verified", "Codes verified", "count", 0, 1e6, r"verif|grade"),
        _s("rejects", "Rejects", "count", 0, 1000, r"reject")],
       ["Antares Vision", "Systech (Markem-Imaje)", "Optel", "ACG Inspection", "Körber (Seidenader)", "Uhlmann"]),
    _t("labeller", "Labeller", "packaging", "Secondary packing", ALL, [
        _s("labels_applied", "Labels applied", "count", 0, 1e6, r"label|applied", True),
        _s("rejects", "Rejects", "count", 0, 500, r"reject"),
        _s("speed_ppm", "Speed", "units/min", 10, 600, r"speed")],
       ["Herma", "Marchesini", "Krones"]),
    # --- liquids & semisolids -------------------------------------------------------------------------------------
    _t("liquid_vessel", "Liquid manufacturing vessel", "liquids", "Compounding", ["oral liquid", "injectable"], [
        _s("vessel_c", "Product temperature", "°C", 5, 90, r"temp|tt", True),
        _s("agitator_rpm", "Agitator speed", "rpm", 10, 1500, r"agit|stirr|rpm"),
        _s("ph", "pH", "pH", 1, 13, r"\bph\b"),
        _s("level_l", "Level", "L", 0, 10000, r"level|volume")],
       ["GEA", "Bectochem", "Romaco FrymaKoruma"]),
    _t("ointment_vessel", "Ointment / cream manufacturing plant (vacuum)", "liquids", "Compounding", ["ointment / cream"], [
        _s("product_c", "Product temperature", "°C", 20, 85, r"temp|product", True),
        _s("vacuum_mbar", "Vacuum", "mbar", 10, 1000, r"vac", True),
        _s("agitator_rpm", "Anchor agitator speed", "rpm", 5, 80, r"agit|anchor"),
        _s("homogenizer_rpm", "Homogeniser speed", "rpm", 500, 3600, r"homog")],
       ["Romaco FrymaKoruma", "IKA", "Ystral", "Bectochem"]),
    _t("homogenizer", "Homogeniser / colloid mill", "liquids", "Compounding", ["oral liquid", "ointment / cream"], [
        _s("rotor_rpm", "Rotor speed", "rpm", 500, 10000, r"rpm|rotor|speed", True),
        _s("product_c", "Product temperature", "°C", 10, 80, r"temp"),
        _s("pressure_bar", "Homogenising pressure", "bar", 0, 1000, r"press")],
       ["IKA", "Silverson", "Ystral", "GEA"]),
    _t("filtration", "Filtration skid (clarifying / sterile)", "liquids", "Filtration", LIQ, [
        _s("dp_bar", "Differential pressure", "bar", 0, 3, r"\bdp\b|diff", True),
        _s("flow_l_h", "Flow", "L/h", 10, 10000, r"flow"),
        _s("inlet_bar", "Inlet pressure", "bar", 0, 5, r"inlet|press")],
       ["Sartorius", "Merck Millipore", "Pall (Cytiva)"]),
    _t("filling_line", "Liquid filling line", "liquids", "Filling", ["oral liquid"], [
        _s("fill_volume_ml", "Fill volume", "mL", 1, 1000, r"fill.?vol|volume", True),
        _s("line_speed_bpm", "Line speed", "units/min", 10, 600, r"speed|bpm|upm")],
       ["Marchesini", "IMA", "Syntegon (Bosch)", "Groninger"]),
    _t("tube_filler", "Tube filling & sealing", "liquids", "Filling", ["ointment / cream"], [
        _s("fill_weight_g", "Fill weight", "g", 2, 250, r"fill|weight", True),
        _s("sealing_c", "Sealing temperature", "°C", 150, 450, r"seal|hot.?air"),
        _s("speed_tpm", "Speed", "tubes/min", 10, 300, r"speed")],
       ["IWK (Syntegon)", "Norden", "ProSys"]),
    # --- sterile manufacturing ------------------------------------------------------------------------------------
    _t("vial_washer", "Vial / ampoule washer", "sterile", "Washing", STERILE, [
        _s("wfi_c", "WFI temperature", "°C", 60, 95, r"wfi|water.?t", True),
        _s("wfi_bar", "WFI pressure", "bar", 0.5, 4, r"wfi.?p|water.?p"),
        _s("air_bar", "Compressed air pressure", "bar", 0.5, 4, r"air"),
        _s("speed_vpm", "Speed", "vials/min", 20, 600, r"speed")],
       ["Syntegon (Bosch)", "IMA", "Bausch+Ströbel", "Optima", "Groninger"]),
    _t("depyrogenation_tunnel", "Depyrogenation tunnel", "sterile", "Depyrogenation", STERILE, [
        _s("hot_zone_c", "Hot-zone temperature", "°C", 250, 350, r"hot|steril|heat", True),
        _s("belt_mm_min", "Belt speed", "mm/min", 50, 500, r"belt|speed"),
        _s("cooling_c", "Cooling-zone temperature", "°C", 15, 60, r"cool"),
        _s("dp_pa", "Pressure to the room", "Pa", 2, 30, r"\bdp\b|diff")],
       ["Syntegon (Bosch)", "IMA", "Bausch+Ströbel"]),
    _t("vial_filling", "Vial / ampoule filling & stoppering", "sterile", "Aseptic filling", STERILE, [
        _s("fill_volume_ml", "Fill volume", "mL", 0.5, 100, r"fill|volume", True),
        _s("speed_vpm", "Speed", "units/min", 20, 600, r"speed"),
        _s("laf_m_s", "Laminar airflow velocity", "m/s", 0.36, 0.54, r"laf|velocity|airflow"),
        _s("rejects", "Rejects", "count", 0, 500, r"reject")],
       ["Syntegon (Bosch)", "IMA", "Groninger", "Optima", "Bausch+Ströbel", "Marchesini"]),
    _t("isolator", "Isolator / RABS", "sterile", "Aseptic filling", STERILE, [
        _s("dp_pa", "Pressure to the room", "Pa", 10, 100, r"\bdp\b|diff|press", True),
        _s("h2o2_ppm", "H₂O₂ concentration", "ppm", 0, 1500, r"h2o2|vhp|peroxide"),
        _s("particles_05_m3", "Particles ≥ 0.5 µm", "per m³", 0, 3520, r"0\.?5|particle")],
       ["Skan", "Getinge", "Franz Ziel", "Comecer", "Fedegari"]),
    _t("lyophilizer", "Freeze dryer (lyophiliser)", "sterile", "Lyophilisation", STERILE, [
        _s("shelf_c", "Shelf temperature", "°C", -55, 40, r"shelf", True),
        _s("product_c", "Product temperature", "°C", -55, 40, r"product|probe"),
        _s("chamber_ubar", "Chamber pressure", "µbar", 20, 1000, r"chamber|pirani|capac|press", True),
        _s("condenser_c", "Condenser temperature", "°C", -85, -40, r"condens")],
       ["GEA", "IMA Life", "SP Industries", "Tofflon", "Millrock", "HOF Sonderanlagenbau"]),
    _t("autoclave", "Autoclave / steam sterilizer", "sterile", "Sterilisation", ["injectable"], [
        _s("chamber_c", "Chamber temperature", "°C", 20, 140, r"chamber|temp", True),
        _s("chamber_bar", "Chamber pressure", "bar", 0, 4, r"press"),
        _s("f0_min", "F0", "min", 0, 60, r"\bf0\b|lethal")],
       ["Fedegari", "Getinge", "Steris", "Belimed"]),
    # --- water, steam, air & HVAC ---------------------------------------------------------------------------------
    _t("pw_system", "Purified water / WFI generation & loop", "utilities", "Utilities", ALL, [
        _s("conductivity_us_cm", "Conductivity", "µS/cm", 0.05, 5, r"conduct|cond", True),
        _s("toc_ppb", "TOC", "ppb", 10, 500, r"\btoc\b|carbon", True),
        _s("loop_c", "Loop temperature", "°C", 15, 90, r"temp|tt"),
        _s("flow_m3_h", "Loop flow", "m³/h", 0.5, 30, r"flow"),
        _s("return_m_s", "Return velocity", "m/s", 0.5, 3, r"return|velocity")],
       ["Stilmas", "BWT", "Veolia", "Evoqua", "Thermax", "Ion Exchange (India)"], batch=False),
    _t("clean_steam", "Pure (clean) steam generator", "utilities", "Utilities", STERILE, [
        _s("steam_bar", "Steam pressure", "bar", 1, 6, r"press|bar", True),
        _s("steam_c", "Steam temperature", "°C", 110, 165, r"temp"),
        _s("condensate_us_cm", "Condensate conductivity", "µS/cm", 0.1, 2, r"conduct")],
       ["Stilmas", "BWT", "Steris (Finn-Aqua)", "Spirax Sarco"], batch=False),
    _t("compressed_air", "Compressed air / nitrogen", "utilities", "Utilities", ALL, [
        _s("pressure_bar", "Header pressure", "bar", 4, 10, r"press|bar", True),
        _s("dew_point_c", "Pressure dew point", "°C", -70, 5, r"dew", True),
        _s("flow_nm3_h", "Flow", "Nm³/h", 10, 5000, r"flow")],
       ["Atlas Copco", "Ingersoll Rand", "ELGi", "Kaeser"], batch=False),
    _t("ahu", "Air handling unit (AHU)", "utilities", "HVAC", ALL, [
        _s("supply_c", "Supply air temperature", "°C", 12, 26, r"supply.?t|sat\b|temp", True),
        _s("supply_rh_pct", "Supply air humidity", "%RH", 20, 70, r"\brh\b|humid"),
        _s("filter_dp_pa", "Final filter differential pressure", "Pa", 100, 600, r"filter|\bdp\b", True),
        _s("airflow_m3_h", "Supply air flow", "m³/h", 1000, 60000, r"flow|cmh"),
        _s("fan_hz", "Supply fan speed", "Hz", 20, 50, r"fan|vfd|hz")],
       ["Carrier", "Daikin", "Trane", "Blue Star", "Johnson Controls"], batch=False),
    _t("hvac_room", "Room / HVAC monitoring", "utilities", "Environment", ALL, [
        _s("room_c", "Room temperature", "°C", 15, 30, r"temp|tt", True),
        _s("room_rh_pct", "Room humidity", "%RH", 20, 70, r"\brh\b|humid", True),
        _s("dp_pa", "Differential pressure", "Pa", 0, 60, r"\bdp\b|diff.?press|pa\b")],
       ["Siemens (Desigo)", "Honeywell", "Johnson Controls (Metasys)", "Schneider Electric", "Vaisala", "Rotronic"], batch=False),
    _t("particle_counter", "Environmental monitoring (particle counter)", "utilities", "Environment", ALL, [
        _s("particles_05_m3", "Particles ≥ 0.5 µm", "per m³", 0, 3520000, r"0\.?5|small", True),
        _s("particles_5_m3", "Particles ≥ 5 µm", "per m³", 0, 29000, r"\b5\b|5\.0|large")],
       ["Particle Measuring Systems", "Lighthouse Worldwide Solutions", "Beckman Coulter (MET ONE)", "TSI", "Climet"], batch=False),
    _t("dust_collector", "Dust collector", "utilities", "Utilities", SOLID, [
        _s("dp_pa", "Filter differential pressure", "Pa", 200, 2500, r"\bdp\b|filter", True),
        _s("fan_a", "Fan current", "A", 0, 60, r"current|amp|fan")],
       ["Donaldson", "Camfil", "Nederman"], batch=False),
    _t("chiller", "Chiller / brine plant", "utilities", "Utilities", ALL, [
        _s("supply_c", "Supply temperature", "°C", -20, 15, r"supply|leaving|chw.?s", True),
        _s("return_c", "Return temperature", "°C", -15, 20, r"return|entering|chw.?r"),
        _s("flow_m3_h", "Flow", "m³/h", 5, 500, r"flow")],
       ["Carrier", "Trane", "Daikin", "Blue Star", "Voltas"], batch=False),
    _t("boiler", "Boiler", "utilities", "Utilities", ALL, [
        _s("steam_bar", "Steam pressure", "bar", 3, 17, r"press|steam", True),
        _s("feedwater_c", "Feed-water temperature", "°C", 60, 110, r"feed"),
        _s("load_pct", "Firing rate", "%", 0, 100, r"load|firing")],
       ["Thermax", "Forbes Marshall", "Bosch Industriekessel"], batch=False),
    # --- storage & stability --------------------------------------------------------------------------------------
    _t("cold_room", "Cold room / pharmaceutical refrigerator", "storage", "Storage", ALL, [
        _s("temp_c", "Temperature", "°C", -25, 25, r"temp|tt", True),
        _s("door_open", "Door open", "0/1", 0, 1, r"door")],
       ["Thermo Fisher Scientific", "Haier Biomedical", "Blue Star", "Remi"], batch=False),
    _t("stability_chamber", "Stability chamber", "storage", "Stability", ALL, [
        _s("chamber_c", "Chamber temperature", "°C", 4, 60, r"temp", True),
        _s("chamber_rh_pct", "Chamber humidity", "%RH", 10, 95, r"\brh\b|humid", True)],
       ["Binder", "Weiss Technik", "Memmert", "Thermolab", "Newtronic", "Remi"], batch=False),
    _t("warehouse", "Warehouse mapping / data loggers", "storage", "Storage", ALL, [
        _s("temp_c", "Temperature", "°C", 2, 35, r"temp", True),
        _s("rh_pct", "Humidity", "%RH", 20, 80, r"\brh\b|humid")],
       ["Vaisala", "Testo", "ELPRO", "Rotronic"], batch=False),
    # --- QC laboratory ---------------------------------------------------------------------------------------------
    _t("dissolution_tester", "Dissolution tester", "qc", "QC testing", SOLID, [
        _s("bath_c", "Bath / vessel temperature", "°C", 36.5, 37.5, r"temp|bath|vessel", True),
        _s("rpm", "Paddle / basket speed", "rpm", 25, 150, r"rpm|speed", True)],
       ["Agilent", "Distek", "Sotax", "Erweka", "Electrolab", "Labindia"]),
    _t("hplc", "HPLC / chromatography (via the CDS)", "qc", "QC testing", ALL, [
        _s("assay_pct", "Assay result", "% of label", 85, 115, r"assay|content", True),
        _s("impurity_pct", "Largest impurity", "%", 0, 2, r"impur|related")],
       ["Waters (Empower)", "Agilent (OpenLab)", "Shimadzu (LabSolutions)", "Thermo Fisher (Chromeleon)"]),
]
TYPE_BY_ID = {t["id"]: t for t in EQUIPMENT_TYPES}

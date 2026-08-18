"""Curated GMP / testing / causes / mitigation knowledge for the analytics
manufacturer-investigation tab.

PRODUCT_CATALOG is a verbatim port of the isolated simulator's drug workbench
(simulator/app.py) so the analytics app can surface real, curated GMP corridors,
IP 2026 / Ph. Eur. testing standards and typical defect causes without importing
the simulator (which is intentionally isolated and carries its own shared/ copies).
Amoxicillin is adapted from data_loader.RESEARCH_PROFILES (the simulator catalog
does not include it). SOLUTION_BANK is recovered from the deleted analytics
landing.py _risk_card.

No fabricated content: products whose active ingredient is not in this catalog
fall back to generic pharmacopeial guidance (generic_standards), and failure
categories without a curated playbook fall back to ICH Q9 (mitigations_for).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Excipient:
    name: str
    role: str
    ratio: float
    description: str


@dataclass
class ParamSpec:
    label: str
    min: float
    max: float
    ideal: float
    unit: str


@dataclass
class TestingGuidelines:
    assay: str
    dissolution: str
    impurities: str


@dataclass
class Drug:
    id: str
    name: str
    dose: str
    dosage_form: str
    total_alerts: int
    source_file: str
    common_alerts: list[str]
    vigibase_risks: list[dict[str, str]]
    patent_ref: str
    patent_link: str | None
    optimal_process: str
    ideal_excipients: list[Excipient]
    ideal_parameters: dict[str, ParamSpec]
    ip2026: TestingGuidelines
    ph_eur: TestingGuidelines
    # Free-text GMP note for APIs whose corridor isn't encoded as ParamSpecs
    # (e.g. amoxicillin, sourced from RESEARCH_PROFILES). Empty for the 16
    # simulator drugs, whose GMP corridor lives in ideal_parameters.
    gmp_note: str = ""


def _g(assay: str, dissolution: str, impurities: str) -> TestingGuidelines:
    return TestingGuidelines(assay=assay, dissolution=dissolution, impurities=impurities)


PRODUCT_CATALOG: dict[str, Drug] = {
    d.id: d
    for d in [
        Drug(
            id="paracetamol",
            name="Paracetamol",
            dose="650 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=124,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Assay (Sub-potency of active ingredient)",
                "Dissolution (Fails rate of release at 30 minutes)",
                "Disintegration (Exceeds 15-minute standard limit)",
                "Related Substances (Excess Free 4-aminophenol / Impurity K > 0.1%)",
                "Description (Tablet Capping / Lamination)",
            ],
            vigibase_risks=[
                {"hazard": "Hepatotoxicity Acceleration",
                 "desc": "Hydrolysis product 4-aminophenol significantly elevates liver toxicity profile."},
                {"hazard": "Therapeutic Failure",
                 "desc": "Delayed dissolution causes sub-therapeutic plasma concentrations during acute pyrexia."},
            ],
            patent_ref="US Patent 9,231,104B2 (Stable Paracetamol Compaction)",
            patent_link=None,
            optimal_process="Wet Granulation",
            ideal_excipients=[
                Excipient("PVP K30", "Binder", 4.0, "Polyvinylpyrrolidone prevents tablet capping."),
                Excipient("Crospovidone", "Disintegrant", 5.0, "Superdisintegrant facilitating rapid dissolution."),
                Excipient("Microcrystalline Cellulose", "Diluent", 5.0, "Improves flow and compression properties."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Limits capping when kept under 1.5%."),
            ],
            ideal_parameters={
                "moistureLOD": ParamSpec("Granule Moisture (LOD %)", 1.5, 2.5, 2.0, "%"),
                "compForce":   ParamSpec("Main Compression Force (kN)", 10, 16, 13, "kN"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Water/Methanol/Glacial Acetic Acid (70:30:1). Flow rate: 1.0 mL/min.",
                "USP Apparatus 2 (Paddle) at 50 RPM; Medium: 900 mL Phosphate Buffer pH 5.8; Limit: NLT 80% dissolved in 30 minutes.",
                "Free 4-aminophenol: Maximum 0.1%.",
            ),
            ph_eur=_g(
                "UV Spectrophotometry at 249 nm on reconstituted standard.",
                "Paddle Apparatus at 50 RPM; Medium: Water; Limit: NLT 80% (Q) in 45 minutes.",
                "Impurity K: Maximum 0.15%.",
            ),
        ),
        Drug(
            id="tamoxifen",
            name="Tamoxifen Citrate",
            dose="20 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=38,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Dissolution (Fails release criteria due to polymorphic transition)",
                "Uniformity of Content (Active ingredient segregation in dry blend)",
                "Assay (Sub-potency of active tamoxifen citrate content)",
            ],
            vigibase_risks=[
                {"hazard": "Oncology Sub-Potency Risk",
                 "desc": "Active assay loss or failing dissolution can trigger breast cancer recurrence."},
                {"hazard": "Localized GI Distress",
                 "desc": "Agglomerated high-concentration local deposits lead to direct mucosal irritation."},
            ],
            patent_ref="WO Patent WO2000064416A2 (Stable Tamoxifen Formulations)",
            patent_link="https://patents.google.com/patent/WO2000064416A2/en",
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Anhydrous Lactose", "Diluent", 75.0, "Provides excellent flowability and mechanical properties."),
                Excipient("Sodium Starch Glycolate", "Disintegrant", 4.0, "Superdisintegrant promoting rapid bursting."),
                Excipient("Colloidal Silicon Dioxide", "Glidant", 0.5, "Optimizes blend flow and reduces segregation."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Sufficient lubrication without coating the hydrophobic API."),
            ],
            ideal_parameters={
                "mixTime":   ParamSpec("Dry Blending Time (mins)", 15, 25, 20, "mins"),
                "pressSpeed": ParamSpec("Rotary Press Speed (RPM)", 20, 40, 30, "RPM"),
            },
            ip2026=_g(
                "Liquid Chromatography on a C18 packing column with UV detection at 240 nm.",
                "USP Apparatus 2 at 50 RPM; 900 mL 0.02 N HCl; Limit: NLT 75% in 30 minutes.",
                "Total related chemical substances: Maximum 1.0%.",
            ),
            ph_eur=_g(
                "HPLC assay compared with tamoxifen citrate chemical reference standards.",
                "Apparatus 2 at 50 RPM; Medium: 0.02 M Hydrochloric acid; Limit: NLT 75% in 30 minutes.",
                "E-isomer content: Maximum 1.0%.",
            ),
        ),
        Drug(
            id="rabeprazole",
            name="Rabeprazole Sodium",
            dose="20 mg",
            dosage_form="Enteric-Coated Tablet",
            total_alerts=45,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Acid Resistance (Enteric polymer coat gastric decay failure)",
                "Description (Maillard Browning color failure under humidity)",
                "Assay (Sub-potency from chemical degradation in acid environment)",
                "Dissolution (Fails rate of release in intestinal buffer stage)",
            ],
            vigibase_risks=[
                {"hazard": "Gastric Acid Rebound",
                 "desc": "Premature enteric degradation renders the PPI inactive, causing severe mucosal irritation."},
                {"hazard": "Esophageal Erosion Progression",
                 "desc": "Therapeutic failures lead directly to worsening of untreated GERD and gastric ulcers."},
            ],
            patent_ref="EP Patent 1,224,931A1 (Alkaline Stabilization of Benzimidazoles)",
            patent_link=None,
            optimal_process="Dry Granulation",
            ideal_excipients=[
                Excipient("Sodium Carbonate", "Alkalizer", 5.0, "Establishes a basic microenvironment to prevent acid degradation."),
                Excipient("Mannitol", "Diluent", 12.0, "Non-reducing sugar; prevents browning."),
                Excipient("HPMC K100", "Enteric Polymer", 6.0, "Provides stomach-acid-resistant coat."),
                Excipient("Magnesium Stearate", "Lubricant", 1.2, "Ensures punch release."),
            ],
            ideal_parameters={
                "ambientRH":  ParamSpec("Cleanroom Relative Humidity (%)", 15, 30, 22, "%"),
                "rollerForce": ParamSpec("Roller Compactor Force (kN/cm)", 4.0, 8.0, 6.0, "kN/cm"),
            },
            ip2026=_g(
                "HPLC validation. Standard C18 column, Mobile Phase: Phosphate buffer pH 7.0/Acetonitrile (65:35).",
                "Acid Stage: 0.1M HCl for 2 hours (NMT 10% dissolved); Buffer Stage: pH 6.8 Phosphate Buffer (NLT 75% in 45 mins).",
                "Total related substances: NMT 1.0%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography standard matching pharmacopeia guidelines.",
                "Dual-stage test replicating gastric to intestinal transit fluid boundaries.",
                "Individual unspecified impurities: NMT 0.1%.",
            ),
        ),
        Drug(
            id="pantoprazole",
            name="Pantoprazole Sodium",
            dose="40 mg",
            dosage_form="Delayed-Release Tablet",
            total_alerts=52,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Dissolution (Fails pH 6.8 buffer-stage rate of release)",
                "Assay (Sub-potency from active hydrolytic decomposition)",
                "Acid Resistance (Enteric shell early dissolution in acid stage)",
            ],
            vigibase_risks=[
                {"hazard": "Acid Breakthrough GERD",
                 "desc": "Uncontrolled proton pump inhibition failure resulting in chemical burns of the esophagus."},
                {"hazard": "Duodenal Ulcer Bleeding",
                 "desc": "Low systemic assay levels fail to raise gastric pH above 4.0, delaying mucosal healing."},
            ],
            patent_ref="US Patent 5,948,789 (Pantoprazole Sodium Stabilization)",
            patent_link=None,
            optimal_process="Dry Granulation",
            ideal_excipients=[
                Excipient("Sodium Carbonate anhydrous", "Alkalizer", 8.0, "Alkaline buffer to maintain basic environment for acid-labile core."),
                Excipient("Crospovidone", "Disintegrant", 4.5, "Ensures rapid tablet burst during pH 6.8 buffer stage."),
                Excipient("Methacrylic Acid Copolymer Type C", "Enteric Polymer", 12.0, "Provides stomach-acid-resistant enteric barrier."),
                Excipient("Calcium Stearate", "Lubricant", 1.0, "Preferred over magnesium stearate to avoid alkaline interaction drifts."),
            ],
            ideal_parameters={
                "ambientRH":  ParamSpec("Compression Room RH (%)", 10, 25, 18, "%"),
                "rollerForce": ParamSpec("Roller Compactor Force (kN/cm)", 3.0, 6.0, 4.5, "kN/cm"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Phosphate buffer pH 7.0/Acetonitrile (60:40).",
                "Acid Stage: 0.1M HCl (NMT 10% in 120 mins); Buffer Stage: pH 6.8 Phosphate Buffer (NLT 75% in 45 mins).",
                "Pantoprazole Sulfone / N-oxide impurities: Maximum 0.2%.",
            ),
            ph_eur=_g(
                "Liquid chromatography with UV detection at 290 nm.",
                "Dual pH stage test; Buffer stage limit: NLT 75% in 45 minutes.",
                "Any individual impurity: Maximum 0.1%.",
            ),
        ),
        Drug(
            id="esomeprazole",
            name="Esomeprazole Magnesium",
            dose="40 mg",
            dosage_form="Delayed-Release Tablet",
            total_alerts=29,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Dissolution (Premature dissolution in acid stage from pellet coat rupture)",
                "Assay (Sub-potency due to enteric pellet degradation during compression)",
                "Uniformity of Content (Variable active pellet distribution inside tablet core)",
            ],
            vigibase_risks=[
                {"hazard": "Gastric Mucosal Degradation",
                 "desc": "Rupturing of enteric pellets inside MUPS triggers immediate active ingredient breakdown in the stomach."},
                {"hazard": "Active Assay Degradation",
                 "desc": "Exposure to gastric pH transforms active Esomeprazole to inactive sulfonamides."},
            ],
            patent_ref="US Patent 6,368,581 (Multi-Unit Particulate System MUPS Tableting)",
            patent_link=None,
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Microcrystalline Cellulose Spheres", "Diluent", 45.0, "Acts as cushioning agent to prevent enteric pellet breakage."),
                Excipient("Crospovidone", "Disintegrant", 5.0, "Swells rapidly to release enteric-coated pellets."),
                Excipient("Enteric Coated Esomeprazole Pellets", "Active Component", 35.0, "Pre-coated active pellets."),
                Excipient("Sodium Stearyl Fumarate", "Lubricant", 1.0, "Avoids hydrophobic capping during compression."),
            ],
            ideal_parameters={
                "compForce": ParamSpec("Main Compression Force (kN)", 4.0, 8.0, 6.0, "kN"),
                "feedRate":  ParamSpec("Pellet Feeder Rate (kg/hr)", 15, 30, 22, "kg/hr"),
            },
            ip2026=_g(
                "HPLC system with C8 column, Mobile Phase: Acetonitrile/Phosphate Buffer pH 7.6.",
                "Acid Phase: 0.1M HCl (NMT 10% in 2 hours); Buffer Phase: pH 6.8 Buffer (NLT 80% in 30 mins).",
                "Related compound A: Maximum 0.15%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing standards at UV 302 nm.",
                "MUPS specific dissolution test; Buffer stage: NLT 80% in 30 mins.",
                "Total unspecified degradation products: Maximum 0.5%.",
            ),
        ),
        Drug(
            id="telmisartan",
            name="Telmisartan",
            dose="40 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=68,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Dissolution (Fails release in pH 7.5 buffer due to meglumine crystallization)",
                "Description (Hygroscopic liquefaction and severe sticking in blister packaging)",
                "Assay (Sub-potency driven by solid-state crystal transitions)",
            ],
            vigibase_risks=[
                {"hazard": "Hypertensive Crisis",
                 "desc": "Failure to dissolve leads to instant loss of blood pressure control and risk of stroke."},
                {"hazard": "Blister Integrity Degradation",
                 "desc": "Moisture ingress causes tablet deliquescence, introducing biological contaminants."},
            ],
            patent_ref="US Patent 6,358,986B1 (Telmisartan Solubilized Core Matrix)",
            patent_link=None,
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Meglumine", "Alkalizer", 6.0, "Increases local pH to solubilize the acidic drug."),
                Excipient("Sorbitol", "Diluent", 14.0, "Ensures compaction stability."),
                Excipient("Poloxamer 188", "Surfactant", 3.0, "Enhances surface wetting."),
                Excipient("Magnesium Stearate", "Lubricant", 1.5, "Ensures tablet release."),
            ],
            ideal_parameters={
                "mixTime":   ParamSpec("Dry Blending Time (mins)", 15, 25, 20, "mins"),
                "pressSpeed": ParamSpec("Rotary Press Speed (RPM)", 20, 45, 32, "RPM"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Ammonium acetate buffer pH 4.0/Methanol (40:60).",
                "USP Apparatus 2 (Paddle) at 75 RPM; Medium: 900 mL pH 7.5 Phosphate Buffer; Limit: NLT 75% in 45 minutes.",
                "Total related degradation products: NMT 0.5%.",
            ),
            ph_eur=_g(
                "Liquid chromatography standard using reference standards.",
                "Paddle apparatus at 75 RPM in pH 7.5 media; Limit: NLT 75% in 45 minutes.",
                "Individual degradation products: NMT 0.2%.",
            ),
        ),
        Drug(
            id="metformin",
            name="Metformin HCl",
            dose="500 mg",
            dosage_form="Extended-Release Tablet",
            total_alerts=82,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Weight Variation (Fails tablet weight limits from poor powder flow)",
                "Dissolution (Dose dumping / uncontrolled rapid release of hydrophilic matrix)",
                "Assay (Sub-potency from raw material blend segregation)",
            ],
            vigibase_risks=[
                {"hazard": "Lactic Acidosis Spike",
                 "desc": "Dose dumping releases excessive Metformin rapidly, pushing kidney filtration boundaries."},
                {"hazard": "Erratic Blood Glucose",
                 "desc": "Weight and content variations between tablets trigger uncoordinated glycemic highs and lows."},
            ],
            patent_ref="US Patent 6,610,324 (Swellable Hydrophilic Metformin Matrix)",
            patent_link=None,
            optimal_process="Wet Granulation",
            ideal_excipients=[
                Excipient("HPMC K100M", "Binder", 28.0, "Forms swellable gel matrix that controls drug release rate."),
                Excipient("Sodium Carboxymethylcellulose", "Disintegrant", 8.0, "Synergistic hydrophilic polymer promoting uniform gel boundary."),
                Excipient("Microcrystalline Cellulose", "Diluent", 15.0, "Provides compaction matrix strength."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Lubricant for dense high-volume tableting."),
            ],
            ideal_parameters={
                "binderVolume": ParamSpec("Granulation Water (L)", 8.0, 12.0, 10.0, "L"),
                "dryTime":      ParamSpec("Fluid Bed Dryer Time (mins)", 30, 50, 40, "mins"),
            },
            ip2026=_g(
                "Spectrophotometric assessment at 233 nm using verified standard references.",
                "USP Apparatus 1 (Basket) at 100 RPM; Medium: pH 6.8 Buffer; Limit: 1 hr (20-40%), 3 hr (45-65%), 8 hr (NLT 85%).",
                "Dicyandiamide impurity: Maximum 0.02%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing raw metformin standard curves.",
                "Apparatus 1 at 100 RPM; pH 6.8 buffer parameters matching pharmacopeial standards.",
                "Total related degradation products: Maximum 0.1%.",
            ),
        ),
        Drug(
            id="glimepiride",
            name="Glimepiride",
            dose="2 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=31,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Uniformity of Content (Severe failures in microgram-scale distribution)",
                "Assay (Sub-potency and super-potency hot-spots from powder segregation)",
                "Dissolution (Fails rate of release due to active particle agglomeration)",
            ],
            vigibase_risks=[
                {"hazard": "Severe Hypoglycemia Shock",
                 "desc": "Hotspots (excess API) in poorly mixed batches cause acute, life-threatening blood sugar drops."},
                {"hazard": "Persistent Hyperglycemia",
                 "desc": "Sub-potency tablets due to powder segregation lead to chronic elevated HbA1c levels."},
            ],
            patent_ref="US Patent 6,180,660 (Uniform Low-Dose Sulfonylurea Formulations)",
            patent_link=None,
            optimal_process="Wet Granulation",
            ideal_excipients=[
                Excipient("Lactose Monohydrate", "Diluent", 65.0, "Main diluent carrier providing uniform density."),
                Excipient("PVP K25", "Binder", 3.5, "Binds microgram active particles evenly onto carrier granules."),
                Excipient("Sodium Starch Glycolate", "Disintegrant", 4.0, "Promotes rapid tablet disintegration."),
                Excipient("Magnesium Stearate", "Lubricant", 0.8, "Lubricates punch boundaries."),
            ],
            ideal_parameters={
                "mixSpeed":  ParamSpec("High-Shear Mixer Speed (RPM)", 100, 200, 150, "RPM"),
                "micronSize": ParamSpec("API Micronized Particle Size (µm)", 2.0, 8.0, 5.0, "µm"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Acetonitrile/Phosphate Buffer pH 3.5.",
                "Apparatus 2 at 75 RPM; Medium: pH 7.8 Phosphate Buffer; Limit: NLT 80% in 15 minutes.",
                "Glimepiride cis-isomer limit: Maximum 0.4%.",
            ),
            ph_eur=_g(
                "HPLC comparing validation peaks at UV 228 nm.",
                "Paddle at 75 RPM in pH 7.8 media; Limit: NLT 80% in 15 minutes.",
                "Total related chemical compounds: Maximum 0.5%.",
            ),
        ),
        Drug(
            id="amlodipine",
            name="Amlodipine Besylate",
            dose="5 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=41,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Assay (Active transesterification and hydrolytic degradation)",
                "Dissolution (Fails rate of release due to solid-state hydrate transitions)",
                "Related Substances (Excess Amlodipine pyridine derivative Impurity D > 0.3%)",
            ],
            vigibase_risks=[
                {"hazard": "Loss of Angina Control",
                 "desc": "Decomposed active ester fails to maintain steady calcium channel blockade."},
                {"hazard": "Sudden BP Spikes",
                 "desc": "Hydrate shifts prevent rapid dissolution, causing unpredictable delay in emergency drug release."},
            ],
            patent_ref="US Patent 4,879,303 (Stable Amlodipine Besylate Compact)",
            patent_link=None,
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Microcrystalline Cellulose PH102", "Diluent", 70.0, "Dry binder/diluent with low moisture content."),
                Excipient("Anhydrous Dibasic Calcium Phosphate", "Diluent", 22.0, "Non-hygroscopic carrier preventing hydrolysis."),
                Excipient("Sodium Starch Glycolate", "Disintegrant", 3.0, "Swells without adsorbing moisture from atmosphere."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Ensures reliable ejection."),
            ],
            ideal_parameters={
                "packagingRH":   ParamSpec("Packaging Environment RH (%)", 10, 30, 20, "%"),
                "mainPressForce": ParamSpec("Compaction Force (kN)", 8.0, 14.0, 11.0, "kN"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Water/Acetonitrile/Methanol with Triethylamine.",
                "Apparatus 2 at 75 RPM; Medium: 0.01M HCl; Limit: NLT 75% in 30 minutes.",
                "Amlodipine impurity D (pyridine derivative): Maximum 0.3%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing standard besylate curves.",
                "Paddle at 75 RPM; 0.01M HCl; Limit: NLT 75% in 30 minutes.",
                "Total unspecified impurities: Maximum 0.25%.",
            ),
        ),
        Drug(
            id="losartan",
            name="Losartan Potassium",
            dose="50 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=34,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Dissolution (Fails release criteria due to film-coat sintering barrier)",
                "Identification (Chemical identity overlap during baseline raw materials testing)",
                "Assay (Sub-potency driven by core degradation during aqueous coating)",
            ],
            vigibase_risks=[
                {"hazard": "Vasoconstriction Recurrence",
                 "desc": "Dissolution drift delays active AT_1 block, causing dangerous vascular spasms."},
                {"hazard": "Allergenic Core Degradants",
                 "desc": "Moisture trapped during coating sintering triggers micro-hydrolysis into reactive fragments."},
            ],
            patent_ref="US Patent 5,608,075 (Stable Film Coated Losartan)",
            patent_link=None,
            optimal_process="Dry Granulation",
            ideal_excipients=[
                Excipient("Microcrystalline Cellulose", "Diluent", 55.0, "Compactible base filler."),
                Excipient("Lactose Monohydrate", "Diluent", 30.0, "Provides fast release characteristics."),
                Excipient("Opadry II Coating System", "Enteric Polymer", 3.5, "Moisture protection film layer."),
                Excipient("Magnesium Stearate", "Lubricant", 1.2, "Ensures lubrication on rotary compaction."),
            ],
            ideal_parameters={
                "coatingTemp": ParamSpec("Coating Bed Temperature (°C)", 38.0, 46.0, 42.0, "°C"),
                "sprayRate":   ParamSpec("Coating Spray Rate (mL/min)", 10.0, 25.0, 18.0, "mL/min"),
            },
            ip2026=_g(
                "HPLC validation utilizing C18 column, Phosphate buffer/Acetonitrile mobile phase.",
                "Apparatus 2 at 50 RPM; Medium: Water; Limit: NLT 75% in 30 minutes.",
                "Total related degradants: Maximum 0.2%.",
            ),
            ph_eur=_g(
                "Spectrophotometric identity and assay comparison at UV 254 nm.",
                "Paddle at 50 RPM; Water medium; Limit: NLT 75% in 30 minutes.",
                "Individual degradation products: Maximum 0.1%.",
            ),
        ),
        Drug(
            id="ramipril",
            name="Ramipril",
            dose="5 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=49,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Related Substances (Excess diketopiperazine (DKP) cyclization degradants > 0.5%)",
                "Assay (Severe sub-potency from moisture-driven intramolecular cyclization)",
                "Dissolution (Erratic core release profile from degraded active molecules)",
            ],
            vigibase_risks=[
                {"hazard": "Cardiovascular Risk Spikes",
                 "desc": "Conversion of ramipril to inactive diketopiperazine (DKP) results in untreated chronic hypertension."},
                {"hazard": "Severe ACE-Inhibitor Failure",
                 "desc": "Hydrolytic degradation destroys therapeutic efficacy, exposing patients to post-MI risks."},
            ],
            patent_ref="EP Patent 0,317,478 (In-Situ Stabilization of Ramipril with Alumina)",
            patent_link=None,
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Colloidal Aluminum Hydroxide", "Alkalizer", 5.0, "Provides complexation shield preventing intramolecular cyclization."),
                Excipient("Pregelatinized Starch (Low Moisture)", "Diluent", 40.0, "Inert starch containing less than 1.0% water."),
                Excipient("Sodium Stearyl Fumarate", "Lubricant", 1.0, "Provides necessary punch release without shearing the drug."),
            ],
            ideal_parameters={
                "coreMoisture": ParamSpec("Tablet Core Moisture LOD (%)", 0.5, 1.5, 1.0, "%"),
                "compForce":    ParamSpec("Punch Compression Force (kN)", 6.0, 12.0, 9.0, "kN"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Methanol/Water with Perchloric acid.",
                "Apparatus 1 (Basket) at 50 RPM; Medium: 0.1M HCl; Limit: NLT 80% in 45 minutes.",
                "Diketopiperazine (DKP Impurity): Maximum 0.5%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing ramiprilat chemical references.",
                "Basket at 50 RPM in acid medium; Limit: NLT 80% in 45 minutes.",
                "Total unspecified impurities: Maximum 0.25%.",
            ),
        ),
        Drug(
            id="atenolol",
            name="Atenolol",
            dose="50 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=23,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Dissolution (Fails rate of release due to mechanical hydrate-state transitions)",
                "Assay (Potency loss from high compaction shear during dry compounding)",
                "Disintegration (Delayed core physical breakdown under standard buffer)",
            ],
            vigibase_risks=[
                {"hazard": "Tachycardia Breakthrough",
                 "desc": "Hydrate-anhydrous shifts compromise tablet dissolving speed, causing angina breakthrough."},
                {"hazard": "Arrhythmia Escalation",
                 "desc": "Low dissolution profile leads to insufficient plasma concentration during physical exertion."},
            ],
            patent_ref="US Patent 3,836,671 (Atenolol Compaction and Solubilisation Profiles)",
            patent_link=None,
            optimal_process="Wet Granulation",
            ideal_excipients=[
                Excipient("Microcrystalline Cellulose", "Diluent", 45.0, "Ensures high physical matrix binding."),
                Excipient("PVP K30", "Binder", 4.0, "Provides strong granule binding during wet massing."),
                Excipient("Crospovidone", "Disintegrant", 5.0, "Rapid water absorption and expansion matrix."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Limits capping risk."),
            ],
            ideal_parameters={
                "dryTemp":   ParamSpec("Dryer Inlet Air Temperature (°C)", 45.0, 60.0, 52.0, "°C"),
                "shearForce": ParamSpec("Granulator Shear Rate (kN)", 5.0, 15.0, 10.0, "kN"),
            },
            ip2026=_g(
                "Spectrophotometric evaluation of atenolol standard references at 275 nm.",
                "Apparatus 2 at 50 RPM; Medium: 0.1M HCl; Limit: NLT 75% in 30 minutes.",
                "Atenolol related compound A: Maximum 0.3%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing standard validations at UV 226 nm.",
                "Paddle at 50 RPM; Acid medium; Limit: NLT 75% in 30 minutes.",
                "Total unspecified degradation products: Maximum 0.25%.",
            ),
        ),
        Drug(
            id="atorvastatin",
            name="Atorvastatin Calcium",
            dose="10 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=57,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Related Substances (Excess acid-catalyzed lactonization impurity > 0.3%)",
                "Dissolution (Fails rate of release due to hydrophobic wetting failure)",
                "Assay (Active content decline in acidic excipient microenvironments)",
            ],
            vigibase_risks=[
                {"hazard": "Rebound Hypercholesterolemia",
                 "desc": "Acidic degradation converts active statin to inactive lactone, triggering hepatic LDL receptor drops."},
                {"hazard": "Coronary Plaque Instability",
                 "desc": "Erratic dissolution blocks proper vascular protective therapy."},
            ],
            patent_ref="US Patent 5,686,104 (Atorvastatin Calcium Buffering System)",
            patent_link=None,
            optimal_process="Wet Granulation",
            ideal_excipients=[
                Excipient("Calcium Carbonate", "Alkalizer", 6.0, "Acts as microenvironmental alkaline buffer protecting drug from acid degradation."),
                Excipient("Lactose Monohydrate", "Diluent", 50.0, "Provides highly soluble dispersion matrix."),
                Excipient("Poloxamer 188", "Disintegrant", 2.0, "Surfactant that lowers surface tension to wet the hydrophobic API."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Standard tableting release lubricant."),
            ],
            ideal_parameters={
                "calciumCarbonateRatio": ParamSpec("Alkalizer Buffer Ratio (%)", 4.0, 8.0, 6.0, "%"),
                "binderSprayRate":       ParamSpec("Granulator Spray Rate (g/min)", 40.0, 80.0, 60.0, "g/min"),
            },
            ip2026=_g(
                "HPLC utilizing C18 column, Mobile Phase: Acetonitrile/Tetrahydrofuran/Water/Ammonium Acetate buffer.",
                "Apparatus 2 at 75 RPM; Medium: pH 6.8 Buffer; Limit: NLT 75% in 30 minutes.",
                "Atorvastatin lactone related substance: Maximum 0.3%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing standard curves at UV 244 nm.",
                "Paddle at 75 RPM in pH 6.8 media; Limit: NLT 75% in 30 minutes.",
                "Total unspecified degradation products: Maximum 0.15%.",
            ),
        ),
        Drug(
            id="rosuvastatin",
            name="Rosuvastatin Calcium",
            dose="10 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=39,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Related Substances (Excess photo-oxidation of heptenoic acid chain)",
                "Assay (Sub-potency driven by ambient UV exposure during dry granulation)",
                "Description (Discoloration and yellowing under cleanroom lighting)",
            ],
            vigibase_risks=[
                {"hazard": "Inadequate Lipid Management",
                 "desc": "Oxidized active complex fails to inhibit HMG-CoA reductase effectively."},
                {"hazard": "Intestinal Tract Toxicity",
                 "desc": "Photo-degradants cause direct lipid oxidation across the mucosal linings of the intestinal tract."},
            ],
            patent_ref="US Patent 6,316,460 (Stabilised Rosuvastatin Complex)",
            patent_link=None,
            optimal_process="Dry Granulation",
            ideal_excipients=[
                Excipient("Dibasic Calcium Phosphate anhydrous", "Diluent", 40.0, "Inert calcium carrier stabilizing the calcium chelate structure."),
                Excipient("Butylated Hydroxyanisole (BHA)", "Disintegrant", 0.1, "Crucial antioxidant that halts heptenoic acid chain oxidation."),
                Excipient("Microcrystalline Cellulose PH101", "Diluent", 45.0, "Dry granulator compaction aid."),
                Excipient("Sodium Stearyl Fumarate", "Lubricant", 1.0, "Oxidatively inert lubricant."),
            ],
            ideal_parameters={
                "cleanroomLux": ParamSpec("Cleanroom UV Filtering Light (Lux)", 100.0, 300.0, 200.0, "Lux"),
                "rollerForce":  ParamSpec("Roller Compactor Compression (kN/cm)", 4.0, 8.0, 6.0, "kN/cm"),
            },
            ip2026=_g(
                "HPLC method using C18 column with Mobile Phase: Acetonitrile/Phosphate Buffer pH 3.0.",
                "Apparatus 2 at 50 RPM; Medium: 0.05M Phosphate Buffer pH 6.8; Limit: NLT 75% in 45 minutes.",
                "Rosuvastatin diastereomer: Maximum 0.2%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing standard calibrations at UV 242 nm.",
                "Paddle at 50 RPM; pH 6.8 buffer; Limit: NLT 75% in 45 minutes.",
                "Total related degradation products: Maximum 0.5%.",
            ),
        ),
        Drug(
            id="sitagliptin",
            name="Sitagliptin Phosphate",
            dose="100 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=27,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Assay (Potency loss from interfacial nucleophilic cross-migration in bilayer)",
                "Related Substances (Traces of degradation products at bilayer interface)",
                "Dissolution (Fails rate of release profile validation under neutral buffer)",
            ],
            vigibase_risks=[
                {"hazard": "Glycemic Instability Spike",
                 "desc": "Bilayer degradation limits the active DPP-4 blockade, leading to rapid postprandial glucose peaks."},
                {"hazard": "Immunosuppressant Failure",
                 "desc": "Uncontrolled cross-migration degradation yields active breakdown complexes."},
            ],
            patent_ref="US Patent 7,326,708 (Stable Sitagliptin Bilayer Solid Oral Core)",
            patent_link=None,
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Microcrystalline Cellulose PH200", "Diluent", 50.0, "Large particle MCC acting as an interface physical barrier."),
                Excipient("Calcium Hydrogen Phosphate", "Diluent", 35.0, "Inert dicalcium base preventing chemical migration."),
                Excipient("Croscarmellose Sodium", "Disintegrant", 4.0, "Superdisintegrant for rapid release."),
                Excipient("Sodium Stearyl Fumarate", "Lubricant", 1.5, "Inert tablet release lubricant."),
            ],
            ideal_parameters={
                "barrierLayerThick": ParamSpec("Bilayer Interfacial Barrier (mm)", 0.5, 1.5, 1.0, "mm"),
                "bilayerCompForce":  ParamSpec("Secondary Compression Force (kN)", 12.0, 20.0, 16.0, "kN"),
            },
            ip2026=_g(
                "HPLC validation. Standard C18 column, Mobile Phase: Acetonitrile/Phosphate Buffer pH 6.5.",
                "Apparatus 2 at 75 RPM; Medium: Water; Limit: NLT 75% in 30 minutes.",
                "Total unspecified related compounds: Maximum 0.5%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing raw sitagliptin standards.",
                "Paddle at 75 RPM; Water medium; Limit: NLT 75% in 30 minutes.",
                "Individual degradation products: Maximum 0.15%.",
            ),
        ),
        Drug(
            id="vildagliptin",
            name="Vildagliptin",
            dose="50 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=33,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Related Substances (Excess hygroscopic cyclization degradation product > 0.4%)",
                "Description (Tablet softening and core gelation under accelerated humidity stress)",
                "Assay (Low active potency in standard stability chamber storage)",
            ],
            vigibase_risks=[
                {"hazard": "Loss of Glycemic Regulation",
                 "desc": "Moisture ingress catalyzes rapid active molecule cyclization, transforming active drug to inactive cyclic degradants."},
                {"hazard": "Diabetic Instability Escalation",
                 "desc": "Softened tablet matrices result in incomplete active dose absorption."},
            ],
            patent_ref="US Patent 6,011,155 (Vildagliptin Stable Solid Formulations)",
            patent_link=None,
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Anhydrous Lactose", "Diluent", 60.0, "Moisture-free binder matrix."),
                Excipient("Microcrystalline Cellulose (Ultra Dry)", "Diluent", 30.0, "Provides compaction support without carrying water."),
                Excipient("Sodium Starch Glycolate", "Disintegrant", 3.0, "Superdisintegrant with high moisture-absorbing tolerances."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Limits capping under direct compression."),
            ],
            ideal_parameters={
                "environmentRH":    ParamSpec("Cleanroom Relative Humidity (%)", 10, 25, 18, "%"),
                "blisterFoilThick": ParamSpec("Alu-Alu Blister Foil Thickness (µm)", 20, 35, 28, "µm"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Acetonitrile/Phosphate Buffer pH 7.0.",
                "Apparatus 2 at 50 RPM; Medium: Phosphate Buffer pH 6.8; Limit: NLT 75% in 30 minutes.",
                "Vildagliptin cyclic degradation compound: Maximum 0.4%.",
            ),
            ph_eur=_g(
                "Liquid chromatography compared with vildagliptin reference standards.",
                "Paddle at 50 RPM; pH 6.8 media; Limit: NLT 75% in 30 minutes.",
                "Total related degradation products: Maximum 0.5%.",
            ),
        ),
        Drug(
            id="amoxicillin",
            name="Amoxicillin",
            dose="",
            dosage_form="",
            total_alerts=0,
            source_file="",
            common_alerts=[],
            vigibase_risks=[],
            patent_ref="US Patent 4,497,947 (Stable Amoxicillin Trihydrate)",
            patent_link=None,
            optimal_process="Wet Granulation",
            ideal_excipients=[],
            ideal_parameters={},
            gmp_note="RH < 40% throughout processing; LDPE-aluminium blister.",
            ip2026=_g(
                "HPLC method using C18 column; Mobile Phase: Phosphate Buffer/Acetonitrile (per IP 2026 amoxicillin monograph).",
                "Apparatus 2 (Paddle) at 75 RPM; Limit: NLT 80% (Q) dissolved in 30 minutes.",
                "Related substances: NMT 1.0%.",
            ),
            ph_eur=_g(
                "Liquid chromatography per Ph. Eur. monograph 0260 (Amoxicillin Trihydrate).",
                "Paddle at 75 RPM; Medium: Water; Limit: NLT 80% (Q) in 30 minutes.",
                "Total impurities: Maximum 1.5%.",
            ),
        ),
    ]
}


# ---------------------------------------------------------------------------
# Mitigation playbook — recovered verbatim from the deleted analytics/landing.py
# _risk_card.solution_bank. Keys are Failure_Category_Primary values. Only 7 of
# the 16 derived failure categories have a curated playbook; the rest fall back
# to the ICH Q9 risk-management action (mitigations_for) rather than fabricated
# advice.
# ---------------------------------------------------------------------------
SOLUTION_BANK: dict[str, list[str]] = {
    "Dissolution": [
        "Tighten dissolution method transfer and validate sink conditions per USP <711> / IP 2026.",
        "Use design-of-experiments to lock granule PSD and tablet hardness ranges.",
    ],
    "Assay / Content": [
        "Implement in-process blend uniformity sampling (n=10) and NIR trend monitoring.",
        "Re-validate HPLC sample preparation to rule out extraction variability.",
    ],
    "Related Substances": [
        "Stress-test API-excipient compatibility and tighten storage RH limits.",
        "Validate impurity profiling method against a qualified reference standard.",
    ],
    "Description / Appearance": [
        "Review film-coat formulation and pan loading; target consistent exhaust temperature.",
        "Add visual inspection stations with standardized lighting and defect catalog.",
    ],
    "Sterility / Microbial": [
        "Re-qualify media-fill simulations and environmental monitoring programs.",
        "Audit aseptic technique and gowning qualification records.",
    ],
    "Uniformity of Weight": [
        "Calibrate feed frames and compression force sensors on a tighter schedule.",
        "Set weight-control limits at ±3% with automatic reject diverters.",
    ],
    "pH": [
        "Validate pH meter calibration cadence and electrode maintenance SOP.",
        "Tighten buffer preparation tolerances and solution ageing limits.",
    ],
}

_ICH_Q9_FALLBACK = [
    "Conduct a targeted QRM review against ICH Q9 and update the control strategy.",
]


def mitigations_for(category: str) -> list[str]:
    """Return the curated mitigation playbook for a Failure_Category_Primary
    value, or the ICH Q9 fallback when no playbook exists (never fabricates)."""
    return list(SOLUTION_BANK.get(category, _ICH_Q9_FALLBACK))


def generic_standards(product_name: str = "this product") -> dict[str, str]:
    """Honest pharmacopeial fallback for products whose API is not in the
    curated catalog. Verbatim copies of data_loader._generic_research /
    _generic_regulatory (parameterized by name) — no invented specifics."""
    return {
        "scientific": (
            f"Patent link: search WIPO / USPTO / IPO for '{product_name}' (no curated profile) | "
            f"Formulation: standard oral solid unit-dose monograph; review SmPC for excipient precedents | "
            f"GMP: ICH Q7/Q9 risk-based; typical LOD 2–3%, compression 10–14 kN | "
            f"Patent status: API likely off-patent if listed in WHO essential medicines"
        ),
        "regulatory": (
            "Eu. Phr.: consult the relevant Ph. Eur. monograph for the active substance; "
            "if not monographed, follow Ph. Eur. general chapter 2.9.3 (dissolution) and 2.9.6 (uniformity) | "
            "I.P. 2026: consult Indian Pharmacopoeia 2026 monograph; "
            "if not monographed, follow IP general chapters for the dosage form"
        ),
    }


def match_api(text: str) -> str | None:
    """Return the first curated API id whose token appears in `text`, or None.
    Mirrors data_loader._first_api_match but over the richer PRODUCT_CATALOG.
    Substring-on-product-name: brand-name products that omit the generic API
    token will not match and fall through to generic_standards (honest).

    Stays strictly within PRODUCT_CATALOG: the return value is always a
    PRODUCT_CATALOG key, so callers (the GMP & testing standards recap) can
    index PRODUCT_CATALOG with it safely. For the breadth-first molecule
    *labelling* layer (Sankey/heatmap), use match_molecule instead."""
    t = str(text or "").lower()
    for api_id in PRODUCT_CATALOG:
        if api_id in t:
            return api_id
    return None


# ---------------------------------------------------------------------------
# Progressive curation target for the molecule (API) labelling layer.
# ---------------------------------------------------------------------------
# match_api only recognises the 17 APIs that carry a full Drug record in
# PRODUCT_CATALOG (GMP corridor, IP 2026 / Ph. Eur. specs) — those power the
# GMP & testing standards recap, which needs the full record.
#
# The Sankey / heatmap molecule layer wants *breadth*, not full monographs:
# it labels every flagged product with its active-ingredient grouping. To
# grow that labelling progressively without authoring a full Drug record,
# add entries here. match_molecule() consults PRODUCT_CATALOG first, then
# this map. The analytics UI surfaces the molecules not yet in either
# (ranked by alert count) under "Molecules to curate" so they can be copied
# in one at a time.
#
#   key   = a lowercase substring that appears in the raw product name
#           (e.g. "albendazole", "iron sucrose", "amoxycillin")
#   value = the display label for the molecule node (e.g. "albendazole", or
#           "amoxicillin + clavulanate" to normalise a combo spelling)
EXTRA_CURATED_APIS: dict[str, str] = {
    # "albendazole": "albendazole",
    # "aceclofenac": "aceclofenac",
    # "iron sucrose": "iron sucrose",
    # "amoxycillin": "amoxicillin + clavulanate",
}


def match_molecule(text: str) -> str | None:
    """Molecule *label* for the Sankey/heatmap layer: a curated API id from
    PRODUCT_CATALOG if its token appears in `text`, else an EXTRA_CURATED_APIS
    label, else None (the caller falls back to the product-ontology key).
    Unlike match_api, the return is a display label, not necessarily a
    PRODUCT_CATALOG key — do NOT index PRODUCT_CATALOG with it."""
    t = str(text or "").lower()
    for api_id in PRODUCT_CATALOG:
        if api_id in t:
            return api_id
    for token, label in EXTRA_CURATED_APIS.items():
        if token in t:
            return label
    return None

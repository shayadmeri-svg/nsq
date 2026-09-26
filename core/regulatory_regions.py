"""How generic-medicine regulation differs by market — a curated reference.

Used by the Playground's regulatory map. Every row is general, publicly
documented regulatory structure (membership lists, statute-level rules), not
molecule-specific data. Values we could not state with confidence are None
and shown as "check". Verify against the cited sources before relying on a
value for a filing decision.

AS_OF is the date the table was compiled.
"""

from __future__ import annotations

from typing import Any

AS_OF = "2026-09"

SOURCES = {
    "pics": {"label": "PIC/S — members list", "url": "https://picscheme.org/en/members"},
    "ich": {"label": "ICH — members & observers", "url": "https://www.ich.org/page/members-observers"},
    "who_pq": {"label": "WHO Prequalification of medicines", "url": "https://extranet.who.int/prequal/"},
    "fda_ob": {"label": "FDA Orange Book / Hatch-Waxman", "url": "https://www.fda.gov/drugs/drug-approvals-and-databases/approved-drug-products-therapeutic-equivalence-evaluations-orange-book"},
    "ema_generics": {"label": "EMA — generic medicines", "url": "https://www.ema.europa.eu/en/human-regulatory-overview/marketing-authorisation/generic-hybrid-medicines"},
    "dscsa": {"label": "FDA — DSCSA", "url": "https://www.fda.gov/drugs/drug-supply-chain-integrity/drug-supply-chain-security-act-dscsa"},
    "fmd": {"label": "EU Falsified Medicines Directive", "url": "https://health.ec.europa.eu/medicinal-products/falsified-medicines_en"},
    "cdsco": {"label": "CDSCO — Revised Schedule M (GSR 922(E), 2023)", "url": "https://cdsco.gov.in"},
    "ama": {"label": "African Medicines Agency", "url": "https://www.nepad.org/microsite/african-medicines-agency-ama"},
}

# region: used to group on the map / comparison
REGIONS = ["North America", "Europe", "South Asia", "East Asia", "Oceania", "Latin America", "Africa", "Middle East"]

FIELDS = [
    {"key": "regulator", "label": "Regulator"},
    {"key": "generic_route", "label": "Generic route"},
    {"key": "gmp_standard", "label": "GMP standard"},
    {"key": "pics_member", "label": "PIC/S member", "source": "pics"},
    {"key": "ich", "label": "ICH status", "source": "ich"},
    {"key": "data_exclusivity", "label": "Data / market protection for originators"},
    {"key": "patent_linkage", "label": "Patent linkage (approval tied to patents)"},
    {"key": "serialisation", "label": "Serialisation / track-and-trace"},
    {"key": "reliance", "label": "Reliance on other regulators"},
]

# country code (ISO alpha-2, "EU" = the EU/EEA block)
MARKETS: dict[str, dict[str, Any]] = {
    "US": {
        "name": "United States", "region": "North America", "regulator": "FDA",
        "generic_route": "ANDA (Hatch-Waxman); Orange Book TE codes",
        "gmp_standard": "cGMP 21 CFR 210/211", "pics_member": True, "ich": "Founding member",
        "data_exclusivity": "5 y NCE, 3 y new clinical investigation, 7 y orphan", "data_exclusivity_years": 5,
        "patent_linkage": True, "serialisation": "DSCSA — unit-level, interoperable tracing",
        "reliance": "None (own review); pre-approval inspections of Indian sites",
        "strictness": 5, "notes": "Paragraph IV challenges and 180-day first-filer exclusivity.",
    },
    "EU": {
        "name": "European Union / EEA", "region": "Europe", "regulator": "EMA + national agencies",
        "generic_route": "Art. 10(1) generic MA — centralised, decentralised or mutual recognition",
        "gmp_standard": "EU GMP (EudraLex Vol. 4) incl. Annex 1 sterile", "pics_member": True, "ich": "Founding member",
        "data_exclusivity": "8 y data + 2 y market protection (+1 y new indication)", "data_exclusivity_years": 8,
        "patent_linkage": False, "serialisation": "Falsified Medicines Directive — unique identifier + anti-tamper",
        "reliance": "Mutual recognition agreements (e.g. with US FDA) for inspections",
        "strictness": 5, "notes": "QP batch release in the EU; API written confirmation for imported APIs; SPCs extend patents up to 5 y.",
    },
    "GB": {
        "name": "United Kingdom", "region": "Europe", "regulator": "MHRA",
        "generic_route": "Generic MA; International Recognition Procedure",
        "gmp_standard": "UK GMP (EU GMP basis)", "pics_member": True, "ich": "Member",
        "data_exclusivity": "8 + 2 (+1) y (retained EU rules)", "data_exclusivity_years": 8,
        "patent_linkage": False, "serialisation": "EU FMD no longer applies in Great Britain",
        "reliance": "International Recognition Procedure — relies on FDA, EMA, Health Canada, TGA and others",
        "strictness": 5, "notes": "",
    },
    "CA": {
        "name": "Canada", "region": "North America", "regulator": "Health Canada",
        "generic_route": "ANDS", "gmp_standard": "Canadian GMP (GUI-0001)", "pics_member": True, "ich": "Member",
        "data_exclusivity": "8 y (+6 months paediatric)", "data_exclusivity_years": 8,
        "patent_linkage": True, "serialisation": None, "reliance": "MRAs with EU and others",
        "strictness": 5, "notes": "PM(NOC) Regulations link generic approval to listed patents.",
    },
    "JP": {
        "name": "Japan", "region": "East Asia", "regulator": "PMDA / MHLW", "generic_route": "Generic application (BE required)",
        "gmp_standard": "J-GMP (PIC/S aligned)", "pics_member": True, "ich": "Founding member",
        "data_exclusivity": "Re-examination period, typically 8 y for new actives", "data_exclusivity_years": 8,
        "patent_linkage": True, "serialisation": None, "reliance": "Foreign manufacturer accreditation required",
        "strictness": 5, "notes": "",
    },
    "AU": {
        "name": "Australia", "region": "Oceania", "regulator": "TGA", "generic_route": "Generic registration (ARTG)",
        "gmp_standard": "PIC/S GMP", "pics_member": True, "ich": "Observer",
        "data_exclusivity": "5 y", "data_exclusivity_years": 5, "patent_linkage": True, "serialisation": None,
        "reliance": "Comparable overseas regulator (COR) pathways", "strictness": 4, "notes": "",
    },
    "IN": {
        "name": "India", "region": "South Asia", "regulator": "CDSCO + State licensing authorities",
        "generic_route": "Manufacturing licence from the state regulator; CDSCO approval for new drugs",
        "gmp_standard": "Revised Schedule M (WHO-GMP aligned, 2023)", "pics_member": False, "ich": "Observer",
        "data_exclusivity": "None (no regulatory data exclusivity)", "data_exclusivity_years": 0,
        "patent_linkage": False, "serialisation": "Barcodes for exports; QR codes on APIs and top-selling brands",
        "reliance": "Accepts some foreign data; NSQ testing by CDSCO and state labs",
        "strictness": 3, "notes": "Section 3(d) of the Patents Act limits evergreening; NSQ alerts are published monthly.",
    },
    "BR": {
        "name": "Brazil", "region": "Latin America", "regulator": "ANVISA", "generic_route": "Genérico (BE vs reference)",
        "gmp_standard": "ANVISA GMP (PIC/S member)", "pics_member": True, "ich": "Member",
        "data_exclusivity": "None for human medicines", "data_exclusivity_years": 0, "patent_linkage": False,
        "serialisation": None, "reliance": "Optimised pathways relying on reference agencies", "strictness": 4, "notes": "",
    },
    "MX": {
        "name": "Mexico", "region": "Latin America", "regulator": "COFEPRIS", "generic_route": "Genérico intercambiable",
        "gmp_standard": "NOM-059 (PIC/S member)", "pics_member": True, "ich": "Member",
        "data_exclusivity": "5 y (administrative practice)", "data_exclusivity_years": 5, "patent_linkage": True,
        "serialisation": None, "reliance": "Equivalence agreements recognising FDA, EMA, Health Canada and others", "strictness": 4,
        "notes": "Patent linkage via the Official Gazette listing.",
    },
    "ZA": {
        "name": "South Africa", "region": "Africa", "regulator": "SAHPRA", "generic_route": "Multi-source medicine registration",
        "gmp_standard": "PIC/S GMP", "pics_member": True, "ich": "Observer",
        "data_exclusivity": "None", "data_exclusivity_years": 0, "patent_linkage": False, "serialisation": None,
        "reliance": "Reliance on recognised regulators; WHO PQ", "strictness": 4, "notes": "",
    },
    "NG": {
        "name": "Nigeria", "region": "Africa", "regulator": "NAFDAC", "generic_route": "Product registration (dossier + GMP inspection)",
        "gmp_standard": "WHO GMP", "pics_member": False, "ich": None,
        "data_exclusivity": "None", "data_exclusivity_years": 0, "patent_linkage": False, "serialisation": None,
        "reliance": "WHO PQ / collaborative registration; WHO GLL maturity level 3", "strictness": 3,
        "notes": "One of the largest markets for Indian generics in Africa.",
    },
    "KE": {
        "name": "Kenya", "region": "Africa", "regulator": "Pharmacy and Poisons Board", "generic_route": "Product registration",
        "gmp_standard": "WHO GMP", "pics_member": False, "ich": None, "data_exclusivity": "None", "data_exclusivity_years": 0,
        "patent_linkage": False, "serialisation": None, "reliance": "EAC joint assessment; WHO PQ collaborative registration",
        "strictness": 3, "notes": "",
    },
    "GH": {
        "name": "Ghana", "region": "Africa", "regulator": "Food and Drugs Authority", "generic_route": "Product registration",
        "gmp_standard": "WHO GMP", "pics_member": False, "ich": None, "data_exclusivity": "None", "data_exclusivity_years": 0,
        "patent_linkage": False, "serialisation": None, "reliance": "WHO PQ collaborative registration; ECOWAS work-sharing",
        "strictness": 3, "notes": "",
    },
    "EG": {
        "name": "Egypt", "region": "Africa", "regulator": "Egyptian Drug Authority", "generic_route": "Registration (box system)",
        "gmp_standard": "Egyptian GMP (WHO based)", "pics_member": False, "ich": None, "data_exclusivity": None,
        "data_exclusivity_years": None, "patent_linkage": None, "serialisation": None, "reliance": "Reference-country reliance",
        "strictness": 3, "notes": "",
    },
    "SA": {
        "name": "Saudi Arabia", "region": "Middle East", "regulator": "SFDA", "generic_route": "Generic registration (GCC / national)",
        "gmp_standard": "GCC GMP (PIC/S member)", "pics_member": True, "ich": "Member",
        "data_exclusivity": None, "data_exclusivity_years": None, "patent_linkage": None, "serialisation": "RSD track-and-trace",
        "reliance": "Abridged pathway relying on FDA / EMA approvals", "strictness": 4, "notes": "",
    },
    "CN": {
        "name": "China", "region": "East Asia", "regulator": "NMPA", "generic_route": "Generic registration + consistency evaluation (BE)",
        "gmp_standard": "China GMP", "pics_member": False, "ich": "Member",
        "data_exclusivity": None, "data_exclusivity_years": None, "patent_linkage": True, "serialisation": "Drug traceability code",
        "reliance": "Limited", "strictness": 4, "notes": "Patent linkage with early-resolution mechanism since 2021.",
    },
}

# EU / EEA members for colouring the block on a world map (ISO alpha-2).
EU_MEMBERS = ["AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT",
              "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO"]


def table() -> dict[str, Any]:
    return {"as_of": AS_OF, "fields": FIELDS, "sources": SOURCES, "regions": REGIONS, "markets": MARKETS,
            "eu_members": EU_MEMBERS,
            "disclaimer": "Regulatory structure compiled from public sources; verify on the regulator's site before a filing decision. 'check' = not stated with confidence."}

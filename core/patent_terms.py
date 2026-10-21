"""Patent status per market, from sourced facts plus statutory term rules.

Every status this module returns says how it was reached:

  sourced   the publisher says so (FDA Orange Book, Google Patents legal status for that country's patent)
  derived   follows from sourced dates by a statute cited in the result (e.g. India: 20 years from the
            filing date, no extension, so a family whose international filing was 2006-03-20 cannot have an
            Indian patent in force after 2026-03-20)
  unknown   nothing public settles it — shown as "unknown", never as "patented"

Inputs are the facts other sources fetched (no hand-entered dates):
  * the anchor compound patent: the Orange Book drug-substance patent, enriched by the Google Patents family
    (international filing date, per-country legal status and expiry, SPC documents)
  * the first approval year of the molecule anywhere (ChEMBL `first_approval`)
  * the first EU marketing authorisation (EMA), for the SPC ceiling

Assumption used by the derived rules, stated in every note that relies on it: a compound patent is filed
before the molecule's first approval. Later salt / polymorph / formulation patents can exist; they protect a
product, not the molecule, and India's Section 3(d) excludes most of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

TERM_YEARS = 20


@dataclass(frozen=True)
class Jurisdiction:
    code: str
    name: str
    max_extension_years: float  # patent term extension / SPC / CSP on top of 20 years from filing
    rule: str
    citation: str
    url: str
    extra: str = ""


# Statutes: patent term and the longest extension a pharmaceutical patent can get.
JURISDICTIONS: dict[str, Jurisdiction] = {j.code: j for j in [
    Jurisdiction("IN", "India", 0, "20 years from the filing date (for a PCT national-phase patent, the international filing date); no term extension",
                 "Patents Act 1970, s. 53 and s. 138(4)", "https://ipindia.gov.in/writereaddata/Portal/IPOAct/1_31_1_patent-act-1970-11march2015.pdf",
                 "Product patents for medicines exist only for applications filed on or after 1 January 1995 (mailbox, Patents (Amendment) Act 2005)."),
    Jurisdiction("BR", "Brazil", 0, "20 years from filing; the 10-years-from-grant minimum was struck down in 2021, so no extension",
                 "Lei 9.279/1996 art. 40; STF ADI 5529 (2021)", "https://www.planalto.gov.br/ccivil_03/leis/l9279.htm"),
    Jurisdiction("ZA", "South Africa", 0, "20 years from the date of application; no term extension",
                 "Patents Act 57 of 1978, s. 46", "https://www.gov.za/documents/patents-act-26-mar-2015-1206"),
    Jurisdiction("MX", "Mexico", 5, "20 years from filing; up to 5 years more for unreasonable grant delay",
                 "Ley Federal de Protección a la Propiedad Industrial (2020), arts. 53 and 126", "https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPPI.pdf"),
    Jurisdiction("CN", "China", 5, "20 years from filing; new-drug patent term compensation up to 5 years (patents granted from 2021)",
                 "Patent Law of the PRC (2020 amendment), arts. 42", "https://english.cnipa.gov.cn/"),
    Jurisdiction("JP", "Japan", 5, "20 years from filing; extension up to 5 years for a pharmaceutical approval",
                 "Patent Act, art. 67", "https://www.japaneselawtranslation.go.jp/en/laws/view/4097"),
    Jurisdiction("KR", "South Korea", 5, "20 years from filing; extension up to 5 years for a pharmaceutical approval",
                 "Patent Act, art. 88 and 89", "https://www.law.go.kr/"),
    Jurisdiction("CA", "Canada", 2, "20 years from filing; a Certificate of Supplementary Protection adds up to 2 years",
                 "Patent Act, s. 44 and ss. 104–134", "https://laws-lois.justice.gc.ca/eng/acts/p-4/"),
    Jurisdiction("AU", "Australia", 5, "20 years from filing; extension up to 5 years for a pharmaceutical substance",
                 "Patents Act 1990, s. 67 and s. 70", "https://www.legislation.gov.au/C2004A04014/latest/text"),
    Jurisdiction("EU", "European Union", 5.5, "20 years from filing (European patent); an SPC adds up to 5 years, capped at 15 years from the first EU authorisation, +6 months paediatric",
                 "EPC art. 63; Regulation (EC) 469/2009 arts. 13 and 36", "https://eur-lex.europa.eu/eli/reg/2009/469/oj"),
    Jurisdiction("GB", "United Kingdom", 5.5, "20 years from filing; an SPC adds up to 5 years (+6 months paediatric)",
                 "Patents Act 1977 s. 25; retained Regulation 469/2009", "https://www.legislation.gov.uk/eur/2009/469/contents"),
    Jurisdiction("US", "United States", 5, "20 years from filing plus term adjustment; patent term extension up to 5 years (35 USC 156)",
                 "35 U.S.C. §154 and §156", "https://www.law.cornell.edu/uscode/text/35/156"),
]}

# Countries the platform shows, in display order.
MARKETS = ["US", "EU", "IN", "GB", "JP", "CA", "AU", "BR", "MX", "ZA", "CN", "KR"]

_DEAD = ("expired", "ceased", "withdrawn", "abandoned", "revoked", "lapsed", "not in force")


def add_years(d: date, years: float) -> date:
    whole = int(years)
    months = round((years - whole) * 12)
    y, m = d.year + whole, d.month + months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    day = min(d.day, 28) if m == 2 else min(d.day, 30) if m in (4, 6, 9, 11) else d.day
    return date(y, m, day)


@dataclass
class Status:
    code: str
    status: str  # off_patent | loe_pending | patented | unknown
    basis: str  # sourced | derived | unknown
    date: Optional[date] = None  # expiry (or latest possible expiry for a derived upper bound)
    note: str = ""
    sources: list[dict[str, str]] = field(default_factory=list)  # [{label, url}]
    barrier: str = "none"

    def as_geo(self) -> dict[str, Any]:
        j = JURISDICTIONS.get(self.code)
        return {"country_code": self.code, "country_name": j.name if j else self.code, "market_status": self.status,
                "loe_date": self.date.isoformat() if self.date else None, "export_eligible": self.status == "off_patent",
                "patent_barrier": self.barrier if self.status != "off_patent" else "none", "notes": self.note,
                "basis": self.basis, "sources": self.sources}


def _by_date(code: str, expiry: date, today: date, basis: str, note: str, sources: list[dict[str, str]], barrier: str = "composition") -> Status:
    if expiry < today:
        return Status(code, "off_patent", basis, expiry, note, sources)
    soon = expiry <= add_years(today, 5)
    return Status(code, "loe_pending" if soon else "patented", basis, expiry, note, sources, barrier)


def statute(code: str) -> dict[str, str]:
    j = JURISDICTIONS[code]
    return {"label": j.citation, "url": j.url}


def market_status(code: str, *, today: date, family: Optional[dict[str, Any]] = None, first_approval_year: Optional[int] = None,
                  first_eu_authorisation: Optional[date] = None) -> Status:
    """Status of the molecule's compound protection in one market (not the US: see us_status)."""
    j = JURISDICTIONS[code]
    fam = family or {}
    anchor = fam.get("anchor") or {}
    filing = _date(fam.get("international_filing") or anchor.get("filing"))
    gp_src = ({"label": f"Google Patents {anchor.get('number')}", "url": anchor.get("url")} if anchor.get("url") else None)

    # 1. The country's own family member, as Google Patents reports its legal status.
    countries = fam.get("countries") or {}
    # a European patent is validated in the UK, so the EP record stands for GB when there is no national one
    member = countries.get("EP") if code == "EU" else countries.get(code) or (countries.get("EP") if code == "GB" else None)
    if member and member.get("status"):
        st = member["status"].lower()
        src = [{"label": f"Google Patents {member['number']} ({member['status']})", "url": member.get("url", "")}]
        exp = _date(member.get("expiration"))
        if any(w in st for w in _DEAD):
            spc = [s for s in fam.get("spcs") or [] if s.get("country") in _EU_SPC_COUNTRIES] if code in ("EU", "GB") else []
            if spc and filing:
                ceiling = _spc_ceiling(filing, first_eu_authorisation)
                note = (f"The European patent {member['number']} has expired, but SPCs were granted on it "
                        f"({', '.join(s['number'] for s in spc[:4])}). An SPC runs at most 5 years past the patent and 15 years from the "
                        f"first EU authorisation{f' ({first_eu_authorisation.isoformat()})' if first_eu_authorisation else ''}, so protection ends by "
                        f"{ceiling.isoformat()} (+6 months if a paediatric extension was granted).")
                return _by_date(code, ceiling, today, "derived", note, src + [statute(code)] + [{"label": f"SPC {s['number']}", "url": s.get("url", "")} for s in spc[:3]])
            # "Expired - Lifetime" is the base term; a pharmaceutical term extension (JP, KR, AU, CA, CN, MX) is registered
            # separately and Google's status does not show it, so stay conservative until the extension window has passed.
            m_filing = _date(member.get("filing")) or filing
            if "lifetime" in st and code not in ("EU", "GB") and j.max_extension_years and m_filing:
                latest = add_years(m_filing, TERM_YEARS + j.max_extension_years)
                if latest >= today:
                    return _by_date(code, latest, today, "derived",
                                    f"{member['number']}: base term expired (Google Patents), but {j.name} allows a term extension for a "
                                    f"medicine ({j.rule}) that is registered separately, so protection may last until {latest.isoformat()}.",
                                    src + [statute(code)])
            return Status(code, "off_patent", "sourced", exp, f"{member['number']}: {member['status']} (Google Patents legal status).", src)
        if exp:
            return _by_date(code, exp, today, "sourced", f"{member['number']}: {member['status']}, expires {exp.isoformat()} (Google Patents).", src)
        m_filing = _date(member.get("filing")) or filing
        if m_filing and ("active" in st or "pending" in st):
            latest = add_years(m_filing, TERM_YEARS + j.max_extension_years)
            if code in ("EU", "GB") and first_eu_authorisation:
                latest = add_years(_spc_ceiling(m_filing, first_eu_authorisation), 0.5)
            what = "in force" if "active" in st else "an application still pending (it may yet be granted)"
            note = (f"{member['number']} is {what} (Google Patents legal status). It runs at most until {latest.isoformat()}: "
                    f"{j.rule}; filed {m_filing.isoformat()}.")
            return _by_date(code, latest, today, "sourced", note, src + [statute(code)])

    # 2. Statutory upper bound from the international filing date.
    if filing:
        latest = add_years(filing, TERM_YEARS + j.max_extension_years)
        if code in ("EU", "GB") and first_eu_authorisation:
            latest = add_years(_spc_ceiling(filing, first_eu_authorisation), 0.5)
        src = [statute(code)] + ([gp_src] if gp_src else [])
        if latest < today:
            return Status(code, "off_patent", "derived", latest,
                          f"The compound patent family was filed on {filing.isoformat()} ({anchor.get('number', 'Orange Book compound patent')}). "
                          f"{j.name}: {j.rule}, so no patent in this family can be in force after {latest.isoformat()}.", src)
        if j.max_extension_years == 0:
            note = (f"Not confirmed: {j.name} has no open patent register API, and Google Patents lists no {j.name} member of this family. "
                    f"If one was granted it expires on {latest.isoformat()} at the latest ({j.rule}; filed {filing.isoformat()}).")
            return _by_date(code, latest, today, "derived", note, src)

    # 3. Age of the molecule: its compound patent was filed before its first approval.
    if first_approval_year:
        years_ago = today.year - first_approval_year
        bound = TERM_YEARS + j.max_extension_years
        if years_ago > bound:
            extra = f" {j.extra}" if code == "IN" and first_approval_year < 1995 else ""
            return Status(code, "off_patent", "derived", None,
                          f"First approved in {first_approval_year} (ChEMBL). A compound patent is filed before approval, and in {j.name} "
                          f"it lasts at most {bound:g} years ({j.rule}), so the molecule itself is no longer patentable there.{extra}",
                          [statute(code), {"label": "ChEMBL first approval", "url": ""}])
    return Status(code, "unknown", "unknown", None,
                  f"No public source settles {j.name}: no family member with a legal status, and the molecule is too recent for the term rule.")


def us_status(ob: Optional[dict[str, Any]], *, today: date, first_approval_year: Optional[int] = None,
              family: Optional[dict[str, Any]] = None) -> Status:
    """US status from the Orange Book: generics on the market mean the molecule is open; patents that remain are
    product-specific (a formulation, a use) and are reported as such, not as a block on the molecule."""
    src = [{"label": "FDA Orange Book", "url": "https://www.fda.gov/drugs/drug-approvals-and-databases/orange-book-data-files"}]
    if not ob:
        if first_approval_year and today.year - first_approval_year > TERM_YEARS + 5:
            return Status("US", "off_patent", "derived", None,
                          f"No Orange Book patent record (for example an OTC-monograph drug). First approved in {first_approval_year} (ChEMBL): "
                          "a compound patent lasts at most 20 years from filing plus 5 years of extension, so the molecule is open.",
                          [statute("US")])
        return Status("US", "unknown", "unknown", None, "No Orange Book or Purple Book record.")
    subst = _date(ob.get("last_substance_patent_expiry"))
    excl = _date(ob.get("last_exclusivity_expiry"))
    last_any = _date(ob.get("last_patent_expiry"))
    first_generic = _date(ob.get("first_generic_approval"))
    andas = int(ob.get("anda_active") or 0)
    # When the family says which drug-substance patent is the compound, later ones (a crystal form, a salt) protect a
    # form of the molecule: they are reported, but the molecule's date is the compound patent's.
    later_form = None
    anchor = (family or {}).get("anchor") or {}
    comp_exp = _date((family or {}).get("compound_expires") or anchor.get("ob_expires"))
    if (family or {}).get("anchor_is_compound") and comp_exp and subst and subst > comp_exp:
        later_form = subst
        subst = comp_exp
    product_left = max([d for d in (later_form, subst, excl, last_any) if d and d >= today], default=None)
    old = bool(first_approval_year and today.year - first_approval_year > TERM_YEARS + 5)
    subst_live = bool(subst and subst >= today)
    leftover = (f" Orange Book patents / exclusivities run to {product_left.isoformat()}, but they cover specific products "
                "(a later salt or crystal form, a formulation, a strength or a use), not the molecule.") if product_left else ""
    if old:
        return Status("US", "off_patent", "derived", first_generic,
                      f"Open for generics: first approved in {first_approval_year} (ChEMBL), so its compound patent (filed before approval, "
                      f"at most 20 + 5 years) has expired{f'; {andas} generic (ANDA) products are approved' if andas else ''}.{leftover}",
                      src + [statute("US")], "formulation" if product_left else "none")
    if andas > 0 and not subst_live:
        why = (f"{andas} generic (ANDA) product{'s are' if andas != 1 else ' is'} approved"
               + (f", the first on {first_generic.isoformat()}" if first_generic else ""))
        return Status("US", "off_patent", "sourced", first_generic, f"Open for generics: {why}.{leftover}", src,
                      "formulation" if product_left else "none")
    future = [d for d in (subst, excl) if d and d >= today]
    if future:
        exp = max(future)
        kind = "drug-substance patent" if subst and subst == exp else "FDA exclusivity"
        gen = (f" {andas} generic (ANDA) approval{'s' if andas != 1 else ''} already granted — launch waits for the patent "
               "(or a settlement date)." if andas else " No generic is approved yet.")
        lf = (f" A later Orange Book drug-substance patent (a form, composition or use of the molecule) runs to {later_form.isoformat()}: "
              "a generic has to avoid what it claims." if later_form and later_form > exp else "")
        comp = max(((family or {}).get("compound_patents") or []), key=lambda a: a.get("ob_expires") or "", default=None)
        if subst and subst == exp and comp and comp.get("ob_expires") == exp.isoformat():
            kind = f"compound patent ({comp['number']}: {comp.get('title') or ''})"
        return _by_date("US", exp, today, "sourced", f"Latest unexpired {kind} in the Orange Book: {exp.isoformat()}.{gen}{lf}", src)
    if last_any and last_any >= today:
        return _by_date("US", last_any, today, "sourced", "Only formulation / method-of-use patents remain in the Orange Book; no generic approved yet.",
                        src, "formulation")
    last = max([d for d in (subst, excl, last_any) if d], default=None)
    if last:
        return Status("US", "off_patent", "sourced", last, f"Every Orange Book patent and exclusivity has expired (last {last.isoformat()}).", src)
    rld = _date((ob.get("rld") or {}).get("approval"))
    if rld and add_years(rld, 20) < today:
        return Status("US", "off_patent", "derived", rld, f"No patents listed and the reference product was approved on {rld.isoformat()}.", src)
    return Status("US", "unknown", "unknown", None, "The Orange Book lists no patents and the approval is recent.", src)


def eu_from_ema(ema: Optional[dict[str, Any]], *, today: date) -> Optional[Status]:
    """A centrally authorised EU generic is direct evidence the molecule is open in the EU."""
    if not ema:
        return None
    first = _date(ema.get("first_generic_authorised"))
    if (ema.get("generics") or ema.get("biosimilars")) and first:
        return Status("EU", "off_patent", "sourced", first,
                      f"{ema.get('generics') or ema.get('biosimilars')} generic/biosimilar authorisation(s) at the EMA, the first on {first.isoformat()}.",
                      [{"label": "EMA medicines data", "url": "https://www.ema.europa.eu/en/medicines/download-medicine-data"}])
    return None


_EU_SPC_COUNTRIES = {"AT", "BE", "BG", "CH", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GB", "GR", "HR", "HU", "IE", "IT", "LT",
                     "LU", "LV", "MT", "NL", "NO", "PL", "PT", "RO", "SE", "SI", "SK"}


def _spc_ceiling(filing: date, first_eu: Optional[date]) -> date:
    """Latest SPC end: 5 years past the patent, and at most 15 years from the first EU authorisation
    (never earlier than the patent itself)."""
    base, cap = add_years(filing, TERM_YEARS), add_years(filing, TERM_YEARS + 5)
    return max(base, min(cap, add_years(first_eu, 15))) if first_eu else cap


def _date(v: Any) -> Optional[date]:
    if not v:
        return None
    if isinstance(v, date):
        return v
    s = str(v)
    try:
        return date.fromisoformat(s[:10]) if len(s) >= 10 else date.fromisoformat(s[:7] + "-01")
    except ValueError:
        return None

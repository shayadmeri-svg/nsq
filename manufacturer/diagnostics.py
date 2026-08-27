"""Q-engine diagnostics view — single-issue root-cause deep dive.

Maps onto the Figma 'Q-engine diagnostics' screen (Root cause analysis with
two evidence modes — API-informed OOS insights + Data-informed issues — plus
a GMP corridor process narrative, pharmacopeial methods, regulatory
provenance, and a synthesis-route gap). Layout/component-shape authority =
Figma; color/icon authority = the scientific tone (Okabe-Ito, monochrome
bioicons, no emoji, no Figma accent purples/pinks).

This is a thin render layer over ``diagnostics_core.build_diagnosis`` (pure
logic, headless-tested) and the synced GMP/pharmacopeia knowledge cores. It
ports the analytics ``_render_manufacturer_investigation`` evidence sections
into a *single-issue, tenant-scoped* view. No engine/simulator HTTP — the
GMP corridor comes from ``gmp_knowledge``, not the simulator (the CPP-slider
simulator surfaces are a later phase).

Persona emphasis (the seam from auth.py) shifts only section ordering and
which sections default-open — the content is identical for every persona.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from diagnostics_core import Diagnosis, build_diagnosis
from gmp_knowledge import (
    AUTHORITY_TIER_MONOGRAPH,
    Provenance,
)
from pharmacopeia_diff import (
    DIFF_INCOMPARABLE,
    DIFF_METHOD_EQUIVALENT,
    DIFF_NSQ_RELEVANT,
    Pharmacopeia,
    PharmacopeialMethod,
)
from pharmacopeia_methods import CONFIDENCE_HIGH, CONFIDENCE_NONE
from tenants import Tenant
from ui.icons import bioicon
from ui.palette import THEME

# Diagnostics is reached from the dashboard's Deep-dive button (a specific
# issue index) or the nav tab (a random issue index). The app.py router owns
# those session-state keys; this module only renders the resolved index.
DIAG_INDEX_KEY = "mq_diag_issue_idx"

_VERDICT_LABEL = {
    DIFF_NSQ_RELEVANT: "NSQ-relevant",
    DIFF_METHOD_EQUIVALENT: "equivalent",
    DIFF_INCOMPARABLE: "incomparable",
}


# ---------------------------------------------------------------------------
# Small render helpers (ported compactly from analytics/app.py)
# ---------------------------------------------------------------------------
def _section_header(title: str, icon: str) -> None:
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;'
        f'font-size:16px;font-weight:700;color:var(--mq-text);margin:4px 0 8px;">'
        f'{bioicon(icon, 18, "var(--mq-primary)")}{title}</div>',
        unsafe_allow_html=True,
    )


def _provenance_badge(prov: Provenance | None, label: str = "Source") -> None:
    """Compact, monochrome provenance caption — the rigour gate made visible."""
    if prov is None:
        st.caption(f"{label}: no provenance — do not treat as authoritative.")
        return
    bits = [f"{label}: [{prov.authority_tier}] {prov.source_ref or '(no ref)'}"]
    if prov.reference_url:
        bits.append(f"({prov.reference_url})")
    if prov.retrieved_at:
        bits.append(f"retrieved {prov.retrieved_at}")
    if prov.n:
        bits.append(f"n={prov.n}")
    if "TODO" in (prov.notes or ""):
        bits.append("· citation TODO")
    st.caption(" ".join(bits))


def _fmt_method(method: PharmacopeialMethod | None, section: str) -> str:
    """Compact one-line rendering of a parsed compendial method cell."""
    if method is None or method.parse_confidence == CONFIDENCE_NONE:
        return "—"
    parts: list[str] = []
    if section == "dissolution":
        if method.apparatus:
            parts.append(method.apparatus)
        if method.rpm is not None:
            parts.append(f"{method.rpm:g} RPM")
        if method.medium:
            parts.append(method.medium)
        if method.medium_ph is not None:
            parts.append(f"pH {method.medium_ph:g}")
        if method.q_limit_pct is not None:
            parts.append(f"Q≥{method.q_limit_pct:g}%")
        for t in method.timepoints:
            parts.append(f"@{t.time_min:g} min")
    elif section == "assay":
        if method.detection:
            parts.append(method.detection)
        if method.column:
            parts.append(method.column)
        if method.mobile_phase:
            parts.append(f"MP {method.mobile_phase}")
    elif section == "impurities":
        if method.impurity_name:
            parts.append(method.impurity_name)
        if method.impurity_limit_pct is not None:
            parts.append(f"≤{method.impurity_limit_pct:g}%")
    conf = "" if method.parse_confidence == CONFIDENCE_HIGH else f" [{method.parse_confidence}]"
    if not parts:
        return f"text unparseable{conf}"
    return " · ".join(parts) + conf


def _fmt_te_codes(codes: list[str]) -> str:
    return ", ".join(codes) if codes else "(none — OTC / not TE-coded)"


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------
def _render_issue_header(diag: Diagnosis) -> None:
    st.markdown(
        f'<div style="border:1px solid var(--mq-border);border-radius:10px;'
        f'padding:14px 16px;background:var(--mq-surface);'
        f'display:grid;grid-template-columns:1fr auto;gap:6px 12px;align-items:center;">'
        f'  <div>'
        f'    <div style="font-weight:700;font-size:18px;color:var(--mq-text);">'
        f'      {diag.product}</div>'
        f'    <div style="font-size:12px;color:var(--mq-text-muted);margin-top:4px;">'
        f'      Batch {diag.batch} · {diag.lab} · {diag.month} · {diag.form}</div>'
        f'  </div>'
        f'  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px;">'
        f'    <span style="font-size:12px;font-weight:600;color:var(--mq-danger);'
        f'      border:1px solid var(--mq-border);border-radius:6px;padding:3px 10px;">'
        f'      {diag.nsq_result}</span>'
        f'    <span style="font-size:12px;color:var(--mq-text-secondary);">'
        f'      Failure category: <strong>{diag.failure_category}</strong></span>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Deep dive on one of {diag.tenant_alert_count} NSQ alerts for this manufacturer."
    )


def _render_root_cause(diag: Diagnosis) -> None:
    _section_header("Root cause analysis", "microscope")

    # --- Data-informed issues (aggregate over the tenant frame) ---
    st.markdown("**Data-informed issues**")
    if diag.dominant_failures:
        for cat, n, pct in diag.dominant_failures:
            marker = " *(this issue)*" if cat == diag.failure_category else ""
            st.markdown(f"- **{cat}** — a dominant failure mode ({n} alerts, {pct}%){marker}")
    else:
        st.caption("No dominant failure-mode signal for this manufacturer.")
    if diag.form_span > 1:
        st.markdown(f"- Issues span **{diag.form_span} dosage forms**.")
    if diag.geo_concentration:
        geo = ", ".join(f"{s} ({n})" for s, n in diag.geo_concentration)
        st.markdown(f"- Geographic concentration: {geo}.")
    if diag.temporal_clusters:
        tcl = ", ".join(f"{m} ({n})" for m, n in diag.temporal_clusters)
        st.markdown(f"- Temporal clusters: {tcl}.")
    if not diag.is_dominant_failure and diag.failure_category != "—":
        st.caption(
            f"This issue's category ({diag.failure_category}) is an outlier, not a "
            f"dominant mode for this manufacturer — review case-specific factors."
        )

    # --- API-informed OOS insights ---
    st.markdown("**API-informed OOS insights**")
    if diag.drug is not None:
        drug = diag.drug
        st.caption(
            "Curated typical-defect lists are authored narrative (uncited, no "
            "denominator) — review against the empirical cohort, not as grounded fact."
        )
        if drug.common_alerts:
            for a in drug.common_alerts:
                st.markdown(f"- {a}")
            _provenance_badge(drug.common_alerts_prov, "Typical causes")
        if drug.vigibase_risks:
            st.markdown("**Post-market risk signals (VigiBase):**")
            for r in drug.vigibase_risks:
                st.markdown(f"- **{r.get('hazard', '—')}** — {r.get('desc', '')}")
            _provenance_badge(drug.vigibase_risks_prov, "VigiBase risks")
    else:
        st.markdown(
            "This product's active ingredient is not in the curated GMP catalog, "
            "so no API-specific defect mechanism is available."
        )
        if diag.generic_text:
            st.markdown(f"**Scientific context** — {diag.generic_text['scientific']}")
            st.markdown(f"**Regulatory guidelines** — {diag.generic_text['regulatory']}")
            st.caption("Generic pharmacopeial fallback — no fabricated specifics.")


def _render_gmp_corridor(diag: Diagnosis) -> None:
    _section_header("GMP corridor", "beaker")
    if diag.drug is None:
        st.caption(
            "No curated GMP corridor for this product's active ingredient. "
            "Apply ICH Q7/Q9 risk-based manufacturing controls and the dosage "
            "form's general compendial chapters (e.g. Ph. Eur. 2.9.3 dissolution, "
            "2.9.6 uniformity) until a product-specific corridor is sourced."
        )
        return
    drug = diag.drug
    st.markdown(f"**Optimal process:** {drug.optimal_process or '—'}")
    _provenance_badge(drug.optimal_process_prov, "Process")
    if drug.ideal_parameters:
        lines = [
            f"- {p.label}: {p.min}–{p.max} {p.unit} (target {p.ideal} {p.unit})"
            for p in drug.ideal_parameters.values()
        ]
        st.markdown("**Critical processing corridor**\n" + "\n".join(lines))
        first_prov = next(iter(drug.ideal_parameters.values())).provenance
        _provenance_badge(first_prov, "GMP corridor")
    elif drug.gmp_note:
        st.markdown(f"**GMP** — {drug.gmp_note}")
    else:
        st.markdown("**GMP corridor** — not specified in the curated catalog.")
    if drug.ideal_excipients:
        rows = [{"Excipient": e.name, "Role": e.role, "% w/w": e.ratio,
                 "Rationale": e.description}
                for e in drug.ideal_excipients]
        st.markdown("**Formulation (ideal excipient profile)**")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_pharmacopeia(diag: Diagnosis) -> None:
    _section_header("Pharmacopeial methods & cross-monograph diff", "document")
    if diag.drug is None:
        st.caption(
            "No curated compendial method set for this product. Consult the "
            "relevant IP 2026 / Ph. Eur. monograph for the active substance; "
            "if not monographed, follow the dosage form's general chapters."
        )
        return
    drug = diag.drug
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**IP 2026**")
        st.markdown(f"- Assay: {drug.ip2026.assay}")
        st.markdown(f"- Dissolution: {drug.ip2026.dissolution}")
        st.markdown(f"- Impurities: {drug.ip2026.impurities}")
        _provenance_badge(drug.ip2026.provenance, "IP 2026")
    with c2:
        st.markdown("**Ph. Eur.**")
        st.markdown(f"- Assay: {drug.ph_eur.assay}")
        st.markdown(f"- Dissolution: {drug.ph_eur.dissolution}")
        st.markdown(f"- Impurities: {drug.ph_eur.impurities}")
        _provenance_badge(drug.ph_eur.provenance, "Ph. Eur.")

    diffs = diag.method_diffs
    st.markdown(
        f"**Cross-pharmacopeia method diff** — {diag.nsq_relevant_method_diffs}/3 "
        f"sections NSQ-relevant (IP 2026 vs Ph. Eur.)"
    )
    rows = []
    for d in diffs:
        rows.append({
            "Section": d.section,
            "IP 2026": _fmt_method(d.methods[Pharmacopeia.IP2026], d.section),
            "Ph. Eur.": _fmt_method(d.methods[Pharmacopeia.PH_EUR], d.section),
            "USP": _fmt_method(d.methods[Pharmacopeia.USP], d.section),
            "ICH Q4B": (
                "Annex 7(R2) — general ch.; prod.-specific outside scope"
                if d.ich_harmonisation else "—"
            ),
            "Verdict": _VERDICT_LABEL[d.significance],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    nq_rationales = [f"**{d.section}**: {d.rationale}"
                     for d in diffs if d.significance == DIFF_NSQ_RELEVANT]
    if nq_rationales:
        st.markdown("**NSQ-relevant differences:**")
        for r in nq_rationales:
            st.markdown(f"- {r}")
    if drug.ich_harmonisation_prov is not None:
        _provenance_badge(drug.ich_harmonisation_prov, "ICH Q4B harmonisation")


def _render_provenance(diag: Diagnosis) -> None:
    _section_header("Regulatory provenance", "info")
    if diag.drug is None:
        st.caption("No curated regulatory provenance for this product.")
        return
    drug = diag.drug
    st.markdown(f"**Patent:** {drug.patent_ref or '—'}"
                + (f" — [link]({drug.patent_link})" if drug.patent_link else ""))
    _provenance_badge(drug.patent_prov, "Patent")

    ob = drug.orange_book
    if ob is None:
        st.caption(
            "FDA Orange Book: no entry (not FDA-approved in the US) — honestly "
            "absent, not faked."
        )
    else:
        st.markdown("**FDA Orange Book** — real US regulatory-equivalence data")
        rows = [
            {"Field": "Active ingredient (US)", "Value": ob.active_ingredient},
            {"Field": "TE codes", "Value": _fmt_te_codes(ob.te_codes)},
            {"Field": "RLD applicant", "Value": ob.rld_applicant or "—"},
            {"Field": "RLD application", "Value": ob.rld_app_number or "—"},
            {"Field": "RLD approval date", "Value": ob.rld_approval_date or "—"},
            {"Field": "Reference standard", "Value": "yes" if ob.reference_standard else "no"},
            {"Field": "Dosage forms", "Value": ", ".join(ob.dosage_forms) or "—"},
            {"Field": "Marketing status", "Value": ", ".join(ob.marketing_statuses) or "—"},
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        _provenance_badge(ob.provenance, "FDA Orange Book")

    st.caption(
        "**Authority tiers** — [monograph] compendial spec · [ich_guideline] ICH "
        "Q4B/Q8/Q9/Q10 · [regulatory_registry] FDA Orange Book / EMA / CDSCO · "
        "[patent] registry-cited · [empirical_cohort] cohort n+query · "
        "[expert_corridor] illustrative · [uncited] citation TODO."
    )


def _render_synthesis_gap(diag: Diagnosis) -> None:
    _section_header("Synthesis route", "molecule")
    st.info(
        "Synthesis-route steps with patent cites (e.g. the Figma's "
        "Hydrogenation → Hydrolysis → Condensation → N-Alkylation → Final "
        "Hydrolysis → Purification, patent US7943781B2) are **not yet in the "
        "GMP knowledge core**. This section is a placeholder until that data is "
        "curated — no chemistry is invented here."
    )


def _render_mitigation_preview(diag: Diagnosis) -> None:
    _section_header("Suggested mitigations (preview)", "check")
    if diag.mitigations:
        for m in diag.mitigations:
            st.markdown(f"- {m.text}")
            _provenance_badge(m.provenance, "Mitigation")
    else:
        st.caption("No curated mitigation playbook for this failure category.")
    st.caption(
        "Full CAPA plan — per-excipient actions + critical processing spec "
        "windows — lands in the Q-engine mitigation tab (phase 3)."
    )


# (key, title, icon, render_fn)
_SECTIONS: tuple[tuple[str, str, str, callable], ...] = (
    ("root_cause", "Root cause analysis", "microscope", _render_root_cause),
    ("gmp_corridor", "GMP corridor", "beaker", _render_gmp_corridor),
    ("pharmacopeia", "Pharmacopeial methods", "document", _render_pharmacopeia),
    ("provenance", "Regulatory provenance", "info", _render_provenance),
    ("synthesis", "Synthesis route", "molecule", _render_synthesis_gap),
    ("mitigation", "Suggested mitigations", "check", _render_mitigation_preview),
)

# Persona emphasis — section order + which sections default-open. Content is
# identical; only ordering and expander defaults shift.
_PERSONA_ORDER: dict[str, list[str]] = {
    "QA": ["root_cause", "gmp_corridor", "pharmacopeia", "provenance", "synthesis", "mitigation"],
    "Regulatory": ["root_cause", "pharmacopeia", "provenance", "synthesis", "gmp_corridor", "mitigation"],
    "Executive": ["root_cause", "mitigation", "provenance", "gmp_corridor", "pharmacopeia", "synthesis"],
}
_PERSONA_OPEN: dict[str, set[str]] = {
    "QA": {"root_cause", "gmp_corridor", "pharmacopeia"},
    "Regulatory": {"root_cause", "pharmacopeia", "provenance", "synthesis"},
    "Executive": {"root_cause", "mitigation"},
}
_BY_KEY = {k: (t, ic, fn) for k, t, ic, fn in _SECTIONS}


def _pick_issue_index(df: pd.DataFrame) -> int:
    """Resolve the diagnostics target index from session state, seeding a
    random one when the nav tab was clicked without a specific target."""
    idx = st.session_state.get(DIAG_INDEX_KEY)
    if idx is None or not (0 <= int(idx) < len(df)):
        import random
        idx = random.randrange(len(df))
        st.session_state[DIAG_INDEX_KEY] = idx
    return int(idx)


def render_diagnostics(df: pd.DataFrame, tenant: Tenant, persona: str) -> None:
    """Render the Q-engine diagnostics deep-dive for one resolved issue."""
    if df.empty:
        st.warning(
            f"No records found for tenant **{tenant.canonical}** to diagnose."
        )
        return

    idx = _pick_issue_index(df)
    row = df.iloc[idx]
    diag = build_diagnosis(row, df)

    # Header + a re-roll control (the nav-tab entry point picks a random
    # issue; this lets the user draw another without going back).
    _render_issue_header(diag)
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("Pick another issue", key="mq_diag_reroll",
                     help="Randomly select a different issue to deep-dive."):
            st.session_state[DIAG_INDEX_KEY] = None
            st.rerun()
    with c2:
        st.caption(f"Signed in as **{persona}** — section emphasis adapts to role.")

    order = _PERSONA_ORDER.get(persona, _PERSONA_ORDER["QA"])
    open_set = _PERSONA_OPEN.get(persona, _PERSONA_OPEN["QA"])
    for key in order:
        title, icon, fn = _BY_KEY[key]
        with st.expander(title, expanded=key in open_set):
            fn(diag)
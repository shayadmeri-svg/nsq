"""Q-engine — manufacturer (tenant) app.

A dedicated, tenant-scoped Streamlit app separated from /analytics and
/simulator. Phase 1 renders only the Dashboard / Home Page for one
config-driven tenant (default: Regent Ajanta Biotech). The active tenant
is selected by NSQ_TENANT (see tenants.py).

Context separation (per the next-build-user-facing-app memory): this app
imports only the shared data layer (data_loader / company_ontology /
nsq_redis via shared/) and its own ui/ + tenant layer. It does NOT
import from analytics/ or simulator/, and it makes no engine/simulator
HTTP calls in phase 1 — those land in phase 2 (diagnostics / mitigation
/ in-silico simulator).

Run:  just run-manufacturer   (port 8503)
"""

from __future__ import annotations

import os
import sys

import streamlit as st

# Resolve the synced shared/ modules and the local ui/ package.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "shared"))
sys.path.insert(0, _HERE)

from tenants import get_active_tenant  # noqa: E402
from tenant_scope import (  # noqa: E402
    load_tenant_frame,
    tenant_display,
)
from dashboard import render_dashboard  # noqa: E402
from diagnostics import render_diagnostics  # noqa: E402
import auth  # noqa: E402
from ui.components import (  # noqa: E402
    ACTIVE_TAB_KEY,
    DASHBOARD_TAB,
    DIAG_TAB,
    nav_pills,
    render_auth_header,
    render_header,
    render_signin_card,
)
from ui.palette import css_variables  # noqa: E402


def main() -> None:
    st.set_page_config(
        page_title="Q-engine",
        layout="wide",
    )

    # Inject the scientific palette + base rules once.
    st.markdown(css_variables(), unsafe_allow_html=True)

    # Sign-in gate: until the user signs in, show only the gate card.
    # This replaces the old hardcoded manufacturer context block — the
    # manufacturer (tenant) + persona are now established at sign-in.
    if not auth.is_authenticated():
        render_header()
        render_signin_card()
        return

    tenant = auth.selected_tenant()
    persona = auth.current_persona() or "QA"
    canonical, city = tenant_display(tenant)

    render_auth_header(canonical, city, persona)

    # Tab router: the active tab lives in session state (set by nav_pills
    # and the dashboard's Deep-dive buttons). Default to the Dashboard.
    active = st.session_state.get(ACTIVE_TAB_KEY, DASHBOARD_TAB)
    nav_pills(active=active)

    # Load + scope the frame to the signed-in tenant (shared by both views).
    df = load_tenant_frame(tenant)
    if active == DIAG_TAB:
        render_diagnostics(df, tenant, persona)
    else:
        render_dashboard(df, tenant)


if __name__ == "__main__":
    main()
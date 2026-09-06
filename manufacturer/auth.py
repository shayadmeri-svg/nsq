"""Session-only sign-in state for the manufacturer app.

This is NOT real authentication — there is no password, no backend, and
no credential storage. The sign-in gate simply establishes two pieces of
session context that the app needs to render:

  1. **Which manufacturer (tenant)** the user is acting as — selected
     from the tenant registry (replacing the old hardcoded context block
     / the NSQ_TENANT-only default).
  2. **Which persona** they hold — QA / Regulatory / Executive (the
     three audiences the Q-engine serves; see the figma-q-engine-design
     and next-build-user-facing-app memories). Phase 1 does not yet vary
     the view by persona, but capturing it here is the seam for that.

All state lives in ``st.session_state`` under the ``mq_*`` keys, so it is
per-browser-tab and clears when the session ends. A real auth layer (SSO
/ OIDC against the CDMO's IdP) is a later phase; until then the sign-in
is a context-establishment gate, not a security boundary.
"""

from __future__ import annotations

import streamlit as st

from tenants import Tenant, all_tenants, get_active_tenant, get_tenant

# The three Q-engine personas (QA / Regulatory / Executive).
PERSONAS: tuple[str, ...] = ("QA", "Regulatory", "Executive")

_AUTH_KEY = "mq_authenticated"
_TENANT_KEY = "mq_tenant_key"
_PERSONA_KEY = "mq_persona"


def is_authenticated() -> bool:
    return bool(st.session_state.get(_AUTH_KEY))


def current_persona() -> str | None:
    return st.session_state.get(_PERSONA_KEY)


def selected_tenant() -> Tenant:
    """The tenant the user signed in as, falling back to the env default
    (so the app still works if the gate is bypassed)."""
    tenant = get_tenant(st.session_state.get(_TENANT_KEY, ""))
    return tenant or get_active_tenant()


def sign_in(tenant_key: str, persona: str) -> None:
    st.session_state[_AUTH_KEY] = True
    st.session_state[_TENANT_KEY] = tenant_key
    st.session_state[_PERSONA_KEY] = persona


def sign_out() -> None:
    for key in (_AUTH_KEY, _TENANT_KEY, _PERSONA_KEY):
        st.session_state.pop(key, None)


def tenant_choices() -> list[tuple[str, str]]:
    """(tenant_key, display_label) pairs for the sign-in manufacturer select.

    Every manufacturer in the ontology, not a one-entry tuple — curated
    tenants first, then alphabetical. Streamlit's selectbox filters as you
    type, which is what makes a list this long usable.
    """
    return [(t.key, f"{t.canonical} — {t.city}") for t in all_tenants()]
// Session store — replicates manufacturer/auth.py's session-only model
// (tenant + persona in client state, no server validation, no token). The
// Streamlit app stores these as mq_* session_state keys; here they live in a
// zustand store persisted to localStorage so a refresh keeps the user signed
// in for the same ephemeral session.

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Persona, Tenant } from "../lib/types";

interface SessionState {
  signedIn: boolean;
  tenantKey: string | null;
  tenant: Tenant | null; // snapshot of the chosen tenant for the header pill
  persona: Persona | null;
  signIn: (tenant: Tenant, persona: Persona) => void;
  signOut: () => void;
}

export const useSession = create<SessionState>()(
  persist(
    (set) => ({
      signedIn: false,
      tenantKey: null,
      tenant: null,
      persona: null,
      signIn: (tenant, persona) =>
        set({ signedIn: true, tenantKey: tenant.key, tenant, persona }),
      signOut: () =>
        set({ signedIn: false, tenantKey: null, tenant: null, persona: null }),
    }),
    { name: "q-engine-session" },
  ),
);
// Static UI registry — port of diagnostics.py _SECTIONS / _PERSONA_ORDER /
// _PERSONA_OPEN. The section components live in components/diagnostics/sections
// and are keyed here; the DiagnosticsView renders them in persona order with
// the persona's default-open set.

import type { Persona } from "./types";

export type SectionKey =
  | "root_cause"
  | "gmp_corridor"
  | "pharmacopeia"
  | "provenance"
  | "synthesis"
  | "mitigation";

export interface SectionMeta {
  key: SectionKey;
  title: string;
  icon: string; // bioicon name
}

export const SECTIONS: SectionMeta[] = [
  { key: "root_cause", title: "Root cause analysis", icon: "microscope" },
  { key: "gmp_corridor", title: "GMP corridor", icon: "beaker" },
  { key: "pharmacopeia", title: "Pharmacopeial methods", icon: "document" },
  { key: "provenance", title: "Regulatory provenance", icon: "info" },
  { key: "synthesis", title: "Synthesis route", icon: "molecule" },
  { key: "mitigation", title: "Suggested mitigations", icon: "check" },
];

export const PERSONA_ORDER: Record<Persona, SectionKey[]> = {
  QA: ["root_cause", "gmp_corridor", "pharmacopeia", "provenance", "synthesis", "mitigation"],
  Regulatory: ["root_cause", "pharmacopeia", "provenance", "synthesis", "gmp_corridor", "mitigation"],
  Executive: ["root_cause", "mitigation", "provenance", "gmp_corridor", "pharmacopeia", "synthesis"],
};

export const PERSONA_OPEN: Record<Persona, Set<SectionKey>> = {
  QA: new Set(["root_cause", "gmp_corridor", "pharmacopeia"]),
  Regulatory: new Set(["root_cause", "pharmacopeia", "provenance", "synthesis"]),
  Executive: new Set(["root_cause", "mitigation"]),
};

// Verdict labels for MethodDiff.significance — port of diagnostics._VERDICT_LABEL.
export const VERDICT_LABEL: Record<string, string> = {
  NSQ_RELEVANT: "NSQ-relevant",
  METHOD_EQUIVALENT: "equivalent",
  INCOMPARABLE: "incomparable",
};
// Compact one-line rendering of a parsed compendial method cell, and the
// TE-code formatter — ports of diagnostics.py _fmt_method / _fmt_te_codes.
// Kept verbatim so the React Diagnostics sections read identically to the
// Streamlit app.

import type { PharmacopeialMethod } from "../../lib/types";
import { VERDICT_LABEL } from "../../lib/sections";

export const CONFIDENCE_NONE = "NONE";
export const CONFIDENCE_HIGH = "HIGH";

export function fmtMethod(method: PharmacopeialMethod | null, section: string): string {
  if (method === null || method.parse_confidence === CONFIDENCE_NONE) return "—";
  const parts: string[] = [];
  if (section === "dissolution") {
    if (method.apparatus) parts.push(method.apparatus);
    if (method.rpm != null) parts.push(`${method.rpm} RPM`);
    if (method.medium) parts.push(method.medium);
    if (method.medium_ph != null) parts.push(`pH ${method.medium_ph}`);
    if (method.q_limit_pct != null) parts.push(`Q≥${method.q_limit_pct}%`);
    for (const t of method.timepoints) parts.push(`@${t.time_min} min`);
  } else if (section === "assay") {
    if (method.detection) parts.push(method.detection);
    if (method.column) parts.push(method.column);
    if (method.mobile_phase) parts.push(`MP ${method.mobile_phase}`);
  } else if (section === "impurities") {
    if (method.impurity_name) parts.push(method.impurity_name);
    if (method.impurity_limit_pct != null) parts.push(`≤${method.impurity_limit_pct}%`);
  }
  const conf = method.parse_confidence === CONFIDENCE_HIGH ? "" : ` [${method.parse_confidence}]`;
  if (parts.length === 0) return `text unparseable${conf}`;
  return parts.join(" · ") + conf;
}

export function fmtTeCodes(codes: string[]): string {
  return codes.length ? codes.join(", ") : "(none — OTC / not TE-coded)";
}

export function verdictLabel(significance: string): string {
  return VERDICT_LABEL[significance] ?? significance;
}
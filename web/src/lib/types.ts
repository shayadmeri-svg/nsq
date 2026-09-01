// TypeScript interfaces mirroring the manufacturer_api JSON payloads.
// The backend serialises dataclasses via _json_safe: dataclass -> dict,
// enum -> .value, tuple -> list. Pharmacopeia enum values are the strings
// "IP 2026" / "Ph. Eur." / "USP", so MethodDiff.methods is keyed by those.

export type Persona = "QA" | "Regulatory" | "Executive";

export interface Tenant {
  key: string;
  canonical: string;
  city: string;
  ontology_key: string;
}

export interface ConfigPayload {
  tenants: Tenant[];
  personas: Persona[];
}

export interface Kpi {
  label: string;
  value: string | number;
  help: string;
}

export interface Issue {
  id: string;
  product: string;
  batch: string;
  lab: string;
  month: string;
  nsq_result: string;
  failure_category: string;
  form: string;
}

// Plotly figure is a loosely-typed dict (data + layout); react-plotly.js takes
// the full object. Keep it permissive.
export type PlotlyFigure = Record<string, unknown> | null;

export interface DashboardPayload {
  tenant: { key: string; canonical: string; city: string };
  period: string;
  kpis: Kpi[];
  charts: {
    by_type: PlotlyFigure;
    over_time: PlotlyFigure;
    by_form: PlotlyFigure;
    form_vs_issue: PlotlyFigure;
  };
  issues: Issue[];
  issue_count: number;
  empty: boolean;
}

// --- Diagnosis sub-structures (mirror the gmp_knowledge / pharmacopeia_diff
// dataclasses, as serialised by _json_safe) -------------------------------

export interface Provenance {
  authority_tier: string;
  source_type: string;
  source_ref: string;
  retrieved_at: string;
  reference_url: string;
  notes: string;
  query_id: string;
  n: string;
}

export interface Timepoint {
  time_min: number;
  q_limit_pct: number | null;
}

export interface PharmacopeialMethod {
  pharmacopeia: string; // "IP 2026" | "Ph. Eur." | "USP"
  section: string; // "assay" | "dissolution" | "impurities"
  apparatus: string | null;
  medium: string | null;
  medium_ph: number | null;
  rpm: number | null;
  timepoints: Timepoint[];
  q_limit_pct: number | null;
  impurity_name: string | null;
  impurity_limit_pct: number | null;
  detection: string | null;
  column: string | null;
  mobile_phase: string | null;
  raw_text: string;
  provenance: Provenance | null;
  parse_confidence: string; // HIGH | MEDIUM | LOW | NONE
}

export interface MethodDiff {
  section: string;
  methods: Record<string, PharmacopeialMethod | null>; // keyed by pharmacopeia value
  significance: string; // NSQ_RELEVANT | METHOD_EQUIVALENT | INCOMPARABLE
  rationale: string;
  ich_harmonisation: string | null;
}

export interface TestingGuidelines {
  assay: string;
  dissolution: string;
  impurities: string;
  provenance: Provenance | null;
}

export interface Excipient {
  name: string;
  role: string;
  ratio: number;
  description: string;
  provenance: Provenance | null;
}

export interface ParamSpec {
  label: string;
  min: number;
  max: number;
  ideal: number;
  unit: string;
  provenance: Provenance | null;
}

export interface OrangeBookRecord {
  active_ingredient: string;
  te_codes: string[];
  rld_applicant: string | null;
  rld_app_number: string | null;
  rld_approval_date: string | null;
  reference_standard: boolean;
  rld_dosage_form: string | null;
  dosage_forms: string[];
  strengths: string[];
  marketing_statuses: string[];
  provenance: Provenance | null;
  notes: string;
}

export interface Mitigation {
  text: string;
  provenance: Provenance;
}

export interface Drug {
  id: string;
  name: string;
  dose: string;
  dosage_form: string;
  total_alerts: number;
  source_file: string;
  common_alerts: string[];
  vigibase_risks: Array<Record<string, string>>;
  patent_ref: string;
  patent_link: string | null;
  optimal_process: string;
  ideal_excipients: Excipient[];
  ideal_parameters: Record<string, ParamSpec>;
  ip2026: TestingGuidelines;
  ph_eur: TestingGuidelines;
  gmp_note: string;
  patent_prov: Provenance | null;
  optimal_process_prov: Provenance | null;
  common_alerts_prov: Provenance | null;
  vigibase_risks_prov: Provenance | null;
  usp: TestingGuidelines | null;
  orange_book: OrangeBookRecord | null;
  ich_harmonisation_prov: Provenance | null;
}

export interface Diagnosis {
  product: string;
  batch: string;
  nsq_result: string;
  failure_category: string;
  form: string;
  lab: string;
  month: string;
  dominant_failures: Array<[string, number, number]>; // (category, count, pct)
  form_span: number;
  geo_concentration: Array<[string, number]>; // (state, count)
  temporal_clusters: Array<[string, number]>; // ("YYYY-MM", count)
  is_dominant_failure: boolean;
  tenant_alert_count: number;
  api_id: string | null;
  drug: Drug | null;
  generic_fallback: boolean;
  generic_text: { scientific: string; regulatory: string } | null;
  method_diffs: MethodDiff[];
  nsq_relevant_method_diffs: number;
  mitigations: Mitigation[];
  synthesis_gap: boolean;
}

export interface DiagnosticsPayload {
  diagnosis: Diagnosis;
  issue_id: string;
  tenant: { key: string; canonical: string; city: string };
  persona: Persona;
}
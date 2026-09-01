// DiagnosticsView — assembles the issue header, the "Pick another issue"
// re-roll control, and the six sections in persona order as an Accordion,
// with the persona's default-open set. Port of diagnostics.py
// render_diagnostics (the render layer; the bundle comes from the API).

import type { Diagnosis, Persona } from "../../lib/types";
import { PERSONA_OPEN, PERSONA_ORDER, SECTIONS, type SectionKey } from "../../lib/sections";
import { IssueHeader } from "./IssueHeader";
import { BioIcon, type BioiconName } from "../icons/BioIcon";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "../ui/accordion";
import { RootCause } from "./sections/RootCause";
import { GmpCorridor } from "./sections/GmpCorridor";
import { Pharmacopeial } from "./sections/Pharmacopeial";
import { Provenance } from "./sections/Provenance";
import { SynthesisGap } from "./sections/SynthesisGap";
import { MitigationPreview } from "./sections/MitigationPreview";

const SECTION_COMPONENTS: Record<SectionKey, (p: { diag: Diagnosis }) => React.ReactNode> = {
  root_cause: RootCause,
  gmp_corridor: GmpCorridor,
  pharmacopeia: Pharmacopeial,
  provenance: Provenance,
  synthesis: () => <SynthesisGap />,
  mitigation: MitigationPreview,
};

export function DiagnosticsView({
  diag,
  persona,
  onPickAnother,
}: {
  diag: Diagnosis;
  persona: Persona;
  onPickAnother: () => void;
}) {
  const order = PERSONA_ORDER[persona];
  const openSet = PERSONA_OPEN[persona];
  const meta = (key: SectionKey) => SECTIONS.find((s) => s.key === key)!;

  return (
    <div className="space-y-5">
      <IssueHeader diag={diag} />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <button
          onClick={onPickAnother}
          className="inline-flex items-center justify-center rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground hover:bg-accent"
        >
          Pick another issue
        </button>
        <p className="sm:col-span-3 self-center text-xs text-muted-foreground">
          Signed in as <strong>{persona}</strong> — section emphasis adapts to role.
        </p>
      </div>

      <Accordion type="multiple" defaultValue={Array.from(openSet)}>
        {order.map((key) => {
          const m = meta(key);
          const Section = SECTION_COMPONENTS[key];
          return (
            <AccordionItem key={key} value={key}>
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  <BioIcon name={m.icon as BioiconName} size={18} className="text-primary" />
                  {m.title}
                </span>
              </AccordionTrigger>
              <AccordionContent>
                <Section diag={diag} />
              </AccordionContent>
            </AccordionItem>
          );
        })}
      </Accordion>
    </div>
  );
}
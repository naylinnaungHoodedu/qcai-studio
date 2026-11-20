import { evidencePanelView } from "@/lib/evidence-panel";
import type { EvidencePanelPayload } from "@/lib/types";

// The evidence behind a tutor answer the learner already received (plan Phase 3 task 3.8): the decision, the quoted
// passages (links only when the span route is enabled), the "lexically screened" label, any reduced mode, and the
// verification state. Labels only; it never shows anything from the two-pass shadow.
// A group, not a labelled section: a chat holds one panel per answer, and a labelled section is a region landmark,
// so N answers made N landmarks with the same name. Each passage link names its position ("Passage 2: ..."), so two
// passages of one section never share a link text (WCAG 2.4.4).
export function EvidencePanel({ evidence }: { evidence: EvidencePanelPayload }) {
  const view = evidencePanelView(evidence);
  return (
    <div role="group" aria-label="Evidence for this answer" className="assistant-evidence-panel">
      <p className="assistant-evidence-decision">{view.decision}</p>
      {view.labels.length ? (
        <ul className="assistant-evidence-labels">
          {view.labels.map((label) => (
            <li key={label}>{label}</li>
          ))}
        </ul>
      ) : null}
      {view.degraded.length ? (
        <ul className="assistant-evidence-degraded">
          {view.degraded.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
      <p className="assistant-evidence-verdict">{view.verdict}</p>
      {view.spans.length ? (
        <ol className="assistant-evidence-spans">
          {view.spans.map((span) => (
            <li key={span.key}>
              {span.href ? (
                <a href={span.href} rel="nofollow">
                  {span.label}
                </a>
              ) : (
                <span>{span.label}</span>
              )}
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

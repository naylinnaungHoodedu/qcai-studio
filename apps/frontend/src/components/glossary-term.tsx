import type { ReactNode } from "react";

import { getGlossaryDefinition } from "@/lib/glossary";

// Inline plain-language helper: wraps a jargon term so hovering (or a screen
// reader) surfaces a short, jargon-free definition. Server component, zero JS,
// CSP-safe. Falls back to plain text when the term is not in the glossary.
export function GlossaryTerm({
  term,
  children,
}: {
  term: string;
  children?: ReactNode;
}) {
  const definition = getGlossaryDefinition(term);
  const label = children ?? term;

  if (!definition) {
    return <>{label}</>;
  }

  return (
    <abbr className="glossary-term" title={definition}>
      {label}
    </abbr>
  );
}

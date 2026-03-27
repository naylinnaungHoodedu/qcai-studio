import type { Metadata } from "next";

import { buildPageMetadata } from "@/lib/metadata";
import { ATTRIBUTION_STATEMENT, CONTACT_EMAIL, OWNER_NAME } from "@/lib/site";

export const metadata: Metadata = buildPageMetadata({
  title: "Attribution",
  description:
    "Review project ownership, AI-assistance attribution, and the recommended public-facing attribution statement for QC+AI Studio.",
  path: "/attribution",
});

export default function AttributionPage() {
  return (
    <div className="page-stack">
      <section className="section-block">
        <p className="eyebrow">Attribution</p>
        <h1>Project attribution</h1>
        <p className="hero-text">{ATTRIBUTION_STATEMENT}</p>
      </section>
      <section className="panel legal-copy">
        <h2>Ownership</h2>
        <p>{OWNER_NAME} retains product ownership, domain direction, acceptance decisions, and final submission responsibility for QC+AI Studio.</p>
        <h2>Recommended public statement</h2>
        <p>
          QC+AI Studio is a full-stack QC+AI learning platform built and significantly enhanced using OpenAI Codex, with product ownership, domain direction, and final review led by {OWNER_NAME} ({CONTACT_EMAIL}).
        </p>
        <h2>Contact</h2>
        <p>
          Attribution questions can be directed to <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
        </p>
      </section>
    </div>
  );
}

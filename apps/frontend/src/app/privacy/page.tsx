import type { Metadata } from "next";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { StructuredData } from "@/components/structured-data";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";
import { CONTACT_EMAIL } from "@/lib/site";

export const metadata: Metadata = buildPageMetadata({
  title: "Privacy Policy",
  description:
    "Understand how QC+AI Studio handles guest cookies, authenticated access, learner activity, and contact requests.",
  path: "/privacy",
});

export default function PrivacyPage() {
  const structuredData = buildBreadcrumbStructuredData([
    { name: "Home", path: "/" },
    { name: "Privacy", path: "/privacy" },
  ]);

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id="privacy-breadcrumb-jsonld" />
      <section className="section-block">
        <Breadcrumbs
          items={[
            { label: "Home", href: "/" },
            { label: "Privacy" },
          ]}
        />
        <p className="eyebrow">Privacy</p>
        <h1>Privacy policy</h1>
        <p className="hero-text">
          QC+AI Studio is an educational platform. It stores only the learner data needed to run lessons, notes, quizzes, builder activity, project submissions, and adaptive analytics.
        </p>
      </section>
      <section className="panel legal-copy">
        <h2>What the app stores</h2>
        <p>Guest sessions use browser cookies to identify the active learner and protect same-site mutations.</p>
        <p>The public deployment uses those guest sessions for open-demo learner access when Auth0 sign-in is not configured on the client.</p>
        <p>Authenticated access, when configured, uses Auth0-issued credentials so the backend can resolve a stable user identity.</p>
        <p>Notes, quiz attempts, analytics events, builder submissions, project submissions, peer reviews, and learner-profile settings may be persisted to support the learning experience.</p>
        <h2>How data is used</h2>
        <p>Stored learner activity is used to deliver progress tracking, adaptive-path recommendations, skill-gap analysis, project review flows, and community activity surfaces.</p>
        <h2>Contact</h2>
        <p>
          Privacy questions can be directed to <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
        </p>
      </section>
    </div>
  );
}

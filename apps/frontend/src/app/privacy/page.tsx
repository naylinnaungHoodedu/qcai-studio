import type { Metadata } from "next";
import Link from "next/link";

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
          QC+AI Studio is an educational platform. It stores only the learner data needed to run lessons, notes,
          quizzes, builder activity, project submissions, adaptive analytics, and basic account security for the public
          studio.
        </p>
      </section>
      <section className="panel legal-copy">
        <h2>What the app stores</h2>
        <p>
          QC+AI Studio stores the minimum account and learner-activity data needed to provide the public study
          experience. That can include an email address and password hash for first-party local accounts, Auth0-backed
          identity claims when external sign-in is configured, and learner records such as notes, quiz attempts,
          builder runs, project submissions, peer reviews, flashcard/lesson progress, and analytics events tied to a
          guest or authenticated user identifier.
        </p>
        <h2>Cookies and session security</h2>
        <p>
          The public deployment uses first-party cookies for guest continuity and CSRF protection. Guest cookies can
          persist for up to one year so a returning learner can continue a study path without creating an account.
          First-party signed-in sessions for local accounts are shorter lived and are used only to keep the requested
          session authenticated.
        </p>
        <p>
          The site does not rely on advertising trackers to deliver lessons. If optional third-party identity or AI
          features are enabled, they are used for authentication or grounded learning support rather than behavioral ad
          targeting.
        </p>
        <h2>How data is used</h2>
        <p>
          Stored learner activity is used to deliver progress tracking, adaptive-path recommendations, skill-gap
          analysis, project review flows, builder and project community surfaces, operational debugging, and abuse
          prevention. The platform uses that data to run the learning product the learner explicitly requested; it is
          not presented as a general-purpose data brokerage or ad-tech system.
        </p>
        <h2>Retention and deletion</h2>
        <p>
          Guest-session cookies and local-auth session cookies expire automatically according to their configured
          lifetimes. Local-account deletion is available directly from the <Link href="/account">account page</Link>;
          when a local account is deleted, the live application removes the local account record, active sessions, and
          associated notes, quizzes, QA history, analytics events, builder activity, project submissions, peer reviews,
          learner-profile state, and arena records tied to that account.
        </p>
        <p>
          Operational logs, deployment logs, and backup artifacts may persist for a limited period after account
          deletion where needed for security review, abuse prevention, disaster recovery, or legal compliance. If a
          guest learner needs support clearing demo-path data that is not directly attached to a local account, contact
          the operator using the address below.
        </p>
        <h2>Infrastructure and subprocessors</h2>
        <p>
          The public deployment runs on Google Cloud infrastructure for hosting, storage, and managed data services.
          Optional integrations may include Auth0 for federated sign-in and OpenAI or Pinecone for retrieval-grounded
          AI features when those integrations are explicitly configured. Those optional services are not required for
          every public page view.
        </p>
        <h2>Lawful basis and rights where applicable</h2>
        <p>
          Where privacy laws ask for a lawful-basis explanation, the platform relies on the processing needed to
          provide the requested learning service, maintain platform security, and respond to user-initiated requests.
          Depending on the applicable jurisdiction, learners may have rights to request access, correction, deletion,
          or additional information about their data.
        </p>
        <h2>Education and minors</h2>
        <p>
          QC+AI Studio is written for advanced learners and is not designed as a children&apos;s entertainment service.
          It is best suited to higher-education, graduate, professional, or supervised advanced-secondary settings.
          Learners who are minors should use the platform only with appropriate school, institution, or guardian
          oversight.
        </p>
        <h2>Contact</h2>
        <p>
          Privacy questions, rights requests, or data-handling concerns can be directed to{" "}
          <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. The public support and disclosure surface is also
          available on the <Link href="/support">support page</Link>.
        </p>
      </section>
    </div>
  );
}

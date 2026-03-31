import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { StructuredData } from "@/components/structured-data";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";
import { CONTACT_EMAIL } from "@/lib/site";
import { COOKIE_INVENTORY, PRIVACY_IMPLEMENTATION_NOTES, RETENTION_SCHEDULE } from "@/lib/privacy-disclosures";

export const metadata: Metadata = buildPageMetadata({
  title: "Privacy Policy",
  description:
    "Understand how QC+AI Studio handles cookies, retention, support requests, local accounts, and first-party browser telemetry.",
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
          QC+AI Studio stores only the learner, security, support, and operational data needed to run the public
          study experience. The tables below describe the app-controlled data classes, their lifetimes, and the exact
          first-party cookies currently used on the public deployment.
        </p>
      </section>

      <section className="panel legal-copy">
        <h2>What the app stores</h2>
        <p>
          The public deployment stores only the data needed to run lessons, notes, quizzes, builder activity, project
          work, support intake, first-party local-account security, and browser performance telemetry for the public
          site. That can include an email address and password hash for local accounts, guest-linked learner activity,
          support-request details submitted by the user, and non-advertising browser metrics such as LCP or CLS.
        </p>

        <h2>Retention schedule</h2>
        <div className="panel-table-wrap">
          <table className="governance-table">
            <thead>
              <tr>
                <th scope="col">Data class</th>
                <th scope="col">What is stored</th>
                <th scope="col">Retention</th>
                <th scope="col">Removal trigger</th>
              </tr>
            </thead>
            <tbody>
              {RETENTION_SCHEDULE.map((item) => (
                <tr key={item.dataClass}>
                  <th scope="row">{item.dataClass}</th>
                  <td>{item.personalData}</td>
                  <td>{item.retention}</td>
                  <td>{item.trigger}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Provider-managed infrastructure logs may exist outside the app database. Those hosting-layer controls are not
          individually configured from this public web app surface, so the table above focuses only on app-controlled
          retention.
        </p>

        <h2>Cookie inventory</h2>
        <div className="panel-table-wrap">
          <table className="governance-table">
            <thead>
              <tr>
                <th scope="col">Cookie</th>
                <th scope="col">Purpose</th>
                <th scope="col">Lifetime</th>
                <th scope="col">Category</th>
                <th scope="col">When it is set</th>
              </tr>
            </thead>
            <tbody>
              {COOKIE_INVENTORY.map((item) => (
                <tr key={item.name}>
                  <th scope="row">{item.name}</th>
                  <td>{item.purpose}</td>
                  <td>{item.lifetime}</td>
                  <td>{item.necessary}</td>
                  <td>{item.setWhen}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>Current deployment status: the public site uses strictly necessary first-party cookies only.</p>

        <h2>How data is used</h2>
        <p>
          Stored learner activity is used to deliver progress tracking, adaptive-path recommendations, project review
          flows, builder/community surfaces, support follow-up, operational debugging, and abuse prevention. Browser
          telemetry is used to monitor page quality rather than to target ads or build cross-site marketing profiles.
        </p>

        <h2>Deletion and rights requests</h2>
        <p>
          Local-account deletion is available directly from the <Link href="/account">account page</Link>. That live
          flow removes the local account record, active sessions, and linked learner records stored under that account.
          Privacy or correction requests can also be sent through the <Link href="/support">support page</Link> or to{" "}
          <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
        </p>

        <h2>Infrastructure and subprocessors</h2>
        <p>
          The public deployment runs on Google Cloud infrastructure for hosting, storage, and managed data services.
          Optional integrations may include Auth0 for federated sign-in and OpenAI or Pinecone for grounded AI
          features when those integrations are explicitly configured. Those services are not required for every public
          page view.
        </p>

        <h2>Lawful basis and rights where applicable</h2>
        <p>
          Where privacy laws require a lawful-basis explanation, the platform relies on the processing needed to
          provide the requested learning service, maintain platform security, respond to user-initiated support
          requests, and monitor public site quality. Depending on the applicable jurisdiction, learners may have rights
          to request access, correction, deletion, or additional information.
        </p>

        <h2>Education and minors</h2>
        <p>
          QC+AI Studio is written for advanced learners and is not designed as a children&apos;s entertainment service.
          It is best suited to higher-education, graduate, professional, or supervised advanced-secondary settings.
          Learners who are minors should use the platform only with appropriate school, institution, or guardian
          oversight.
        </p>

        <h2>Implementation notes</h2>
        <ul className="compact-list">
          {PRIVACY_IMPLEMENTATION_NOTES.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>

        <h2>Contact</h2>
        <p>
          Privacy questions, rights requests, or data-handling concerns can be directed to{" "}
          <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. The public support and disclosure surfaces are also
          available on the <Link href="/support">support page</Link>, <Link href="/status">status page</Link>, and{" "}
          <Link href="/accessibility">accessibility page</Link>.
        </p>
      </section>
    </div>
  );
}

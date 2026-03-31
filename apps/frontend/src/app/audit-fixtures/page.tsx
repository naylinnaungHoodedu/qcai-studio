import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { StructuredData } from "@/components/structured-data";
import {
  AUDIT_ASSUMPTIONS,
  AUDIT_JOURNEY_CATEGORIES,
  AUDIT_ROLE_CLUSTERS,
  AUDIT_USAGE_NOTES,
  AUDIT_USER_ACCOUNTS,
  AUDIT_USER_COMMANDS,
} from "@/lib/audit-user-fixtures";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";

const ROLE_CLUSTER_LABELS: Record<string, string> = {
  guest: "Guest and anonymous",
  learner: "Learners",
  instructor_creator: "Instructors and creators",
  admin_support: "Admin and support",
  manager_guardian: "Managers and guardians",
};

const JOURNEY_LABELS: Record<string, string> = {
  onboarding_authentication: "Onboarding and authentication",
  course_discovery_enrollment_purchase: "Discovery, enrollment, and purchase",
  learning_experience: "Learning experience",
  content_creation_moderation: "Content creation and moderation",
  support_operations: "Support operations",
  data_rights_privacy: "Data rights and privacy",
  notifications_preferences: "Notifications and preferences",
  error_paths: "Error and recovery paths",
};

export const metadata: Metadata = buildPageMetadata({
  title: "Fictional Audit Users and QA Commands",
  description:
    "Review the privacy-safe fictional user accounts and realistic user-command library used for QC+AI Studio QA, demo, and audit work.",
  path: "/audit-fixtures",
  index: false,
});

export default function AuditFixturesPage() {
  const structuredData = buildBreadcrumbStructuredData([
    { name: "Home", path: "/" },
    { name: "Audit Fixtures", path: "/audit-fixtures" },
  ]);

  const totalEdgeFlags = new Set(AUDIT_USER_ACCOUNTS.flatMap((account) => account.riskFlags)).size;
  const commandCountsByCluster = AUDIT_ROLE_CLUSTERS.filter((cluster) => cluster !== "guest").map((cluster) => ({
    cluster,
    count: AUDIT_USER_COMMANDS.filter((command) => command.roleCluster === cluster).length,
  }));
  const accountsByCluster = AUDIT_ROLE_CLUSTERS.map((cluster) => ({
    cluster,
    accounts: AUDIT_USER_ACCOUNTS.filter((account) => account.roleCluster === cluster),
  }));
  const commandsByCluster = AUDIT_ROLE_CLUSTERS.filter((cluster) => cluster !== "guest").map((cluster) => ({
    cluster,
    commands: AUDIT_USER_COMMANDS.filter((command) => command.roleCluster === cluster),
  }));

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id="audit-fixtures-breadcrumb-jsonld" />

      <section className="hero">
        <div className="hero-copy">
          <Breadcrumbs
            items={[
              { label: "Home", href: "/" },
              { label: "Audit fixtures" },
            ]}
          />
          <p className="eyebrow">Audit fixtures</p>
          <h1>Fictional audit users and realistic QA commands are available on the public domain.</h1>
          <p className="hero-text">
            All records below are fictional, privacy-safe, and designed for QA, demo, and audit evidence only. They
            model realistic learners, creators, staff, managers, and guardians without using real personal data or
            production identities.
          </p>
          <div className="button-row">
            <Link className="primary-button" href="#account-catalog">
              Review account catalog
            </Link>
            <Link className="secondary-button" href="#user-commands">
              Review user commands
            </Link>
            <Link className="secondary-button" href="/support">
              Open support
            </Link>
            <Link className="secondary-button" href="/status">
              View status
            </Link>
          </div>
        </div>

        <div className="analytics-metric-grid">
          <article className="metric-card">
            <span className="eyebrow">Accounts</span>
            <strong className="about-metric-value">{AUDIT_USER_ACCOUNTS.length}</strong>
            <p>Fictional user records spanning guest, learner, creator, staff, guardian, and enterprise contexts.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Commands</span>
            <strong className="about-metric-value">{AUDIT_USER_COMMANDS.length}</strong>
            <p>Realistic user-intent scripts covering onboarding, learning, privacy, support, billing, and failure modes.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Journey types</span>
            <strong className="about-metric-value">{AUDIT_JOURNEY_CATEGORIES.length}</strong>
            <p>Every required journey class is represented in the command library.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Edge flags</span>
            <strong className="about-metric-value">{totalEdgeFlags}</strong>
            <p>Accessibility, low-bandwidth, minors, privacy-rights, suspicious-login, and billing edge cases are included.</p>
          </article>
        </div>
      </section>

      <section className="panel legal-copy">
        <h2>How to use this fixture set</h2>
        <ul className="compact-list">
          {AUDIT_USAGE_NOTES.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p>
          This route is public for audit transparency, but it is intentionally marked <strong>noindex</strong> so it can
          support QA and partner review without being treated as marketing copy. For operational context, see the{" "}
          <Link href="/status">status page</Link>, <Link href="/support">support page</Link>, and{" "}
          <Link href="/accessibility">accessibility page</Link>.
        </p>
      </section>

      <section className="two-column-grid">
        <article className="panel legal-copy">
          <h2>Role coverage</h2>
          <ul className="compact-list">
            {AUDIT_ROLE_CLUSTERS.map((cluster) => (
              <li key={cluster}>
                <strong>{ROLE_CLUSTER_LABELS[cluster]}</strong>:{" "}
                {AUDIT_USER_ACCOUNTS.filter((account) => account.roleCluster === cluster).length} accounts
              </li>
            ))}
          </ul>
        </article>
        <article className="panel legal-copy">
          <h2>Assumptions</h2>
          <ul className="compact-list">
            {AUDIT_ASSUMPTIONS.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </article>
      </section>

      <section className="panel legal-copy" id="account-catalog">
        <h2>Account catalog</h2>
        <p>
          The catalog below uses synthetic names, synthetic phone numbers, and reserved-domain email addresses. It is
          designed to support role realism, not impersonation.
        </p>
        <div className="audit-account-grid">
          {accountsByCluster.map((group) =>
            group.accounts.map((account) => (
              <article className="metric-card audit-account-card" key={account.id}>
                <span className="eyebrow">
                  {account.id} | {ROLE_CLUSTER_LABELS[group.cluster]}
                </span>
                <strong className="about-metric-value">{account.personaName}</strong>
                <p>{account.role}</p>
                <div className="audit-badge-row">
                  <span className="audit-badge">{account.accountStatus}</span>
                  {account.entitlements.map((item) => (
                    <span className="audit-badge" key={`${account.id}-${item}`}>
                      {item}
                    </span>
                  ))}
                </div>
                <ul className="compact-list">
                  {account.goals.map((goal) => (
                    <li key={goal}>{goal}</li>
                  ))}
                </ul>
                <div className="audit-detail-grid">
                  <p>
                    <strong>Device:</strong> {account.primaryDevice}
                  </p>
                  <p>
                    <strong>Connectivity:</strong> {account.connectivity}
                  </p>
                  <p>
                    <strong>Locale:</strong> {account.locale}
                  </p>
                  <p>
                    <strong>Timezone:</strong> {account.timezone}
                  </p>
                  <p>
                    <strong>Language:</strong> {account.languagePreference}
                  </p>
                  <p>
                    <strong>Org:</strong> {account.orgId ?? "none"}
                  </p>
                  <p>
                    <strong>User ID:</strong> {account.userId}
                  </p>
                  <p>
                    <strong>Email:</strong> {account.email ?? "none"}
                  </p>
                  <p>
                    <strong>Phone:</strong> {account.phone ?? "none"}
                  </p>
                </div>
                {account.accessibilityNeeds.length ? (
                  <>
                    <p className="eyebrow">Accessibility</p>
                    <div className="audit-badge-row">
                      {account.accessibilityNeeds.map((item) => (
                        <span className="audit-badge" key={`${account.id}-access-${item}`}>
                          {item}
                        </span>
                      ))}
                    </div>
                  </>
                ) : null}
                {account.enrollments.length ? (
                  <>
                    <p className="eyebrow">Enrollments</p>
                    <ul className="compact-list">
                      {account.enrollments.map((item) => (
                        <li key={`${account.id}-enrollment-${item}`}>{item}</li>
                      ))}
                    </ul>
                  </>
                ) : null}
                <p className="eyebrow">Risk flags</p>
                <div className="audit-badge-row">
                  {account.riskFlags.map((flag) => (
                    <span className="audit-badge" key={`${account.id}-risk-${flag}`}>
                      {flag}
                    </span>
                  ))}
                </div>
              </article>
            )),
          )}
        </div>
      </section>

      <section className="panel legal-copy">
        <h2>Command coverage by role cluster</h2>
        <div className="two-column-grid">
          {commandCountsByCluster.map((item) => (
            <article className="metric-card" key={item.cluster}>
              <span className="eyebrow">Command cluster</span>
              <strong className="about-metric-value">{item.count}</strong>
              <p>{ROLE_CLUSTER_LABELS[item.cluster]} commands with success and failure paths.</p>
            </article>
          ))}
        </div>
        <div className="audit-badge-row">
          {AUDIT_JOURNEY_CATEGORIES.map((category) => (
            <span className="audit-badge" key={category}>
              {JOURNEY_LABELS[category]}
            </span>
          ))}
        </div>
      </section>

      <section className="panel legal-copy" id="user-commands">
        <h2>User commands</h2>
        <p>
          Each command below is a realistic user intent with preconditions, expected outcomes, a negative or edge
          variant, and an explicit audit focus. The goal is to make walkthroughs reproducible and evidence-friendly.
        </p>
        <div className="audit-command-group">
          {commandsByCluster.map((group) => (
            <section className="stack" key={group.cluster}>
              <h3>{ROLE_CLUSTER_LABELS[group.cluster]}</h3>
              {group.commands.map((command) => (
                <details className="panel legal-copy audit-command-detail" key={command.id}>
                  <summary>
                    <span className="eyebrow">{command.id}</span>
                    <strong>{command.commandText}</strong>
                  </summary>
                  <div className="audit-detail-grid">
                    <p>
                      <strong>Accounts:</strong> {command.accountIds.join(", ")}
                    </p>
                    <p>
                      <strong>Audit focus:</strong> {command.auditFocus.join(", ")}
                    </p>
                  </div>
                  <p className="eyebrow">Journey categories</p>
                  <div className="audit-badge-row">
                    {command.categories.map((category) => (
                      <span className="audit-badge" key={`${command.id}-${category}`}>
                        {JOURNEY_LABELS[category]}
                      </span>
                    ))}
                  </div>
                  <p className="eyebrow">Preconditions</p>
                  <ul className="compact-list">
                    {command.preconditions.map((item) => (
                      <li key={`${command.id}-pre-${item}`}>{item}</li>
                    ))}
                  </ul>
                  <p className="eyebrow">Expected outcome</p>
                  <ul className="compact-list">
                    {command.expectedOutcome.map((item) => (
                      <li key={`${command.id}-expect-${item}`}>{item}</li>
                    ))}
                  </ul>
                  <p className="eyebrow">Negative or edge variant</p>
                  <p>{command.negativeVariant}</p>
                </details>
              ))}
            </section>
          ))}
        </div>
      </section>
    </div>
  );
}

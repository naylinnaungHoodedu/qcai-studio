const AUDIT_FIXTURE_USER_ID_PATTERN = /^fixture-ac-(\d{2})$/i;

export const SEEDED_DEMO_DISCLOSURE =
  "Seeded demo activity on this surface comes from fictional audit personas listed on the public audit-fixtures page. Those records are labeled so first-visit evaluation is possible without implying live user activity.";

export function isSeededAuditFixtureUserId(userId: string): boolean {
  return AUDIT_FIXTURE_USER_ID_PATTERN.test(userId.trim());
}

export function formatAuditFixtureUserLabel(userId: string): string | null {
  const match = AUDIT_FIXTURE_USER_ID_PATTERN.exec(userId.trim());
  if (!match) {
    return null;
  }
  return `Audit fixture AC-${match[1]}`;
}

export function formatBuilderFeedAuthorLabel(userId: string): string {
  const fixtureLabel = formatAuditFixtureUserLabel(userId);
  if (fixtureLabel) {
    return `${fixtureLabel} | Seeded demo`;
  }
  const suffix = userId.replace(/[^a-zA-Z0-9]/g, "").slice(-4).toUpperCase();
  return suffix ? `Learner ${suffix}` : "Learner";
}

export function formatProjectAuthorLabel(userId: string): string {
  const fixtureLabel = formatAuditFixtureUserLabel(userId);
  return fixtureLabel ? `${fixtureLabel} | Seeded demo` : userId;
}

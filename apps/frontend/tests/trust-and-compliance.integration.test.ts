import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { GET as wellKnownSecurityRoute } from "../src/app/.well-known/security.txt/route";
import { metadata as auditFixturesMetadata } from "../src/app/audit-fixtures/page";
import { metadata as supportMetadata } from "../src/app/support/page";
import { GET as securityRoute } from "../src/app/security.txt/route";
import { CONTACT_EMAIL, SITE_URL } from "../src/lib/site";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const AUDIT_FIXTURES_PAGE_SOURCE = readFileSync(
  resolve(TEST_DIR, "../src/app/audit-fixtures/page.tsx"),
  "utf8",
);
const PRIVACY_PAGE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/privacy/page.tsx"), "utf8");
const TERMS_PAGE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/terms/page.tsx"), "utf8");
const SUPPORT_PAGE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/support/page.tsx"), "utf8");
const STATUS_PAGE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/status/page.tsx"), "utf8");
const ACCESSIBILITY_PAGE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/accessibility/page.tsx"), "utf8");
const SITE_FOOTER_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/site-footer.tsx"), "utf8");
const OPERATIONS_SOURCE = readFileSync(resolve(TEST_DIR, "../src/lib/operations-governance.ts"), "utf8");
const PRIVACY_DISCLOSURE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/lib/privacy-disclosures.ts"), "utf8");

test("privacy page discloses retention, cookies, deletion, subprocessors, rights, and minors handling", () => {
  assert.match(PRIVACY_PAGE_SOURCE, /Retention schedule/);
  assert.match(PRIVACY_PAGE_SOURCE, /Cookie inventory/);
  assert.match(PRIVACY_DISCLOSURE_SOURCE, /qcai_guest_id/);
  assert.match(PRIVACY_DISCLOSURE_SOURCE, /540 days/);
  assert.match(PRIVACY_DISCLOSURE_SOURCE, /Strictly necessary/);
  assert.match(PRIVACY_PAGE_SOURCE, /Infrastructure and subprocessors/);
  assert.match(PRIVACY_PAGE_SOURCE, /Lawful basis and rights where applicable/);
  assert.match(PRIVACY_PAGE_SOURCE, /Education and minors/);
});

test("terms page clarifies public offering status, refunds, minors, and support", () => {
  assert.match(TERMS_PAGE_SOURCE, /Public offering, pricing, and refunds/);
  assert.match(TERMS_PAGE_SOURCE, /not currently a paid self-serve public offering/);
  assert.match(TERMS_PAGE_SOURCE, /Education and minors/);
  assert.match(TERMS_PAGE_SOURCE, /Operator identity and support/);
});

test("support page exposes trust and partner-facing contact details", () => {
  assert.equal(supportMetadata.title, "Support, Contact, and Trust");
  assert.match(SUPPORT_PAGE_SOURCE, /Support and trust/);
  assert.match(SUPPORT_PAGE_SOURCE, /Structured support intake/);
  assert.match(SUPPORT_PAGE_SOURCE, /Commercial and enrollment clarity/);
  assert.match(SUPPORT_PAGE_SOURCE, /The public QC\+AI Studio site currently operates as a public learning platform/);
  assert.match(SUPPORT_PAGE_SOURCE, /Open support intake/);
});

test("status and accessibility pages publish operational and WCAG tracking disclosures", () => {
  assert.match(STATUS_PAGE_SOURCE, /Browser performance governance/);
  assert.match(OPERATIONS_SOURCE, /COEP is intentionally deferred/);
  assert.match(STATUS_PAGE_SOURCE, /Support response targets/);
  assert.match(ACCESSIBILITY_PAGE_SOURCE, /Accessibility validation is tracked publicly/);
  assert.match(OPERATIONS_SOURCE, /full NVDA\/VoiceOver assistive-technology lab pass remains an explicit operational follow-up/i);
});

test("audit fixtures page publishes fictional users and commands as a noindex trust surface", () => {
  assert.equal(auditFixturesMetadata.title, "Fictional Audit Users and QA Commands");
  assert.equal(auditFixturesMetadata.robots?.index, false);
  assert.match(AUDIT_FIXTURES_PAGE_SOURCE, /All records below are fictional, privacy-safe/);
  assert.match(AUDIT_FIXTURES_PAGE_SOURCE, /Account catalog/);
  assert.match(AUDIT_FIXTURES_PAGE_SOURCE, /User commands/);
  assert.match(SUPPORT_PAGE_SOURCE, /\/audit-fixtures/);
  assert.match(STATUS_PAGE_SOURCE, /\/audit-fixtures/);
  assert.match(SITE_FOOTER_SOURCE, /\/audit-fixtures/);
});

test("security disclosure route publishes a standard security.txt file", async () => {
  const response = securityRoute();
  const body = await response.text();

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "text/plain; charset=utf-8");
  assert.match(body, new RegExp(`Contact: mailto:${CONTACT_EMAIL}`));
  assert.match(body, new RegExp(`Policy: ${SITE_URL}/support`));
  assert.match(body, new RegExp(`Canonical: ${SITE_URL}/\\.well-known/security\\.txt`));
});

test("well-known security disclosure matches the canonical security.txt payload", async () => {
  const canonical = await securityRoute().text();
  const wellKnown = await wellKnownSecurityRoute().text();

  assert.equal(wellKnown, canonical);
});

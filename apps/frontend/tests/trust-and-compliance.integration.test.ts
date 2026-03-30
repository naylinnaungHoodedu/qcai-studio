import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { GET as wellKnownSecurityRoute } from "../src/app/.well-known/security.txt/route";
import { metadata as supportMetadata } from "../src/app/support/page";
import { GET as securityRoute } from "../src/app/security.txt/route";
import { CONTACT_EMAIL, SITE_URL } from "../src/lib/site";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const PRIVACY_PAGE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/privacy/page.tsx"), "utf8");
const TERMS_PAGE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/terms/page.tsx"), "utf8");
const SUPPORT_PAGE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/support/page.tsx"), "utf8");

test("privacy page discloses retention, deletion, subprocessors, rights, and minors handling", () => {
  assert.match(PRIVACY_PAGE_SOURCE, /Retention and deletion/);
  assert.match(PRIVACY_PAGE_SOURCE, /removes the local account record/i);
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
  assert.match(SUPPORT_PAGE_SOURCE, /Commercial and enrollment clarity/);
  assert.match(SUPPORT_PAGE_SOURCE, /The public QC\+AI Studio site currently operates as a public learning platform/);
  assert.match(SUPPORT_PAGE_SOURCE, /Email-first/);
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

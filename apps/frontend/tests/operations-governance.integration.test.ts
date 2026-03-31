import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const PACKAGE_JSON = JSON.parse(
  readFileSync(resolve(TEST_DIR, "../package.json"), "utf8"),
) as { scripts: Record<string, string> };
const WEB_VITALS_REPORTER_SOURCE = readFileSync(
  resolve(TEST_DIR, "../src/components/web-vitals-reporter.tsx"),
  "utf8",
);
const LAYOUT_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/layout.tsx"), "utf8");
const LIGHTHOUSE_SCRIPT_SOURCE = readFileSync(
  resolve(TEST_DIR, "../scripts/run-lighthouse-audit.mjs"),
  "utf8",
);

test("package scripts expose browser-based Lighthouse and accessibility audits", () => {
  assert.equal(PACKAGE_JSON.scripts["test:lighthouse"], "node ./scripts/run-lighthouse-audit.mjs");
  assert.equal(
    PACKAGE_JSON.scripts["test:a11y"],
    "node ./scripts/run-lighthouse-audit.mjs --mode=a11y",
  );
});

test("web vitals reporter is wired into the root layout", () => {
  assert.match(WEB_VITALS_REPORTER_SOURCE, /useReportWebVitals/);
  assert.match(WEB_VITALS_REPORTER_SOURCE, /postPublicWebVital/);
  assert.match(LAYOUT_SOURCE, /<WebVitalsReporter \/>/);
});

test("lighthouse audit script enforces route thresholds for public governance", () => {
  assert.match(LIGHTHOUSE_SCRIPT_SOURCE, /DEFAULT_PAGES/);
  assert.match(LIGHTHOUSE_SCRIPT_SOURCE, /THRESHOLDS/);
  assert.match(LIGHTHOUSE_SCRIPT_SOURCE, /resolveMode/);
  assert.match(LIGHTHOUSE_SCRIPT_SOURCE, /mode === "a11y"/);
  assert.match(LIGHTHOUSE_SCRIPT_SOURCE, /Lighthouse audit failures/);
});

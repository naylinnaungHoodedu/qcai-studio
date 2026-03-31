import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const ACCOUNT_PAGE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/account/page.tsx"), "utf8");
const ACCOUNT_CONSOLE_SOURCE = readFileSync(
  resolve(TEST_DIR, "../src/components/account-console.tsx"),
  "utf8",
);

test("account page no longer renders the access and lifecycle intro boxes", () => {
  assert.doesNotMatch(ACCOUNT_PAGE_SOURCE, /Account access/i);
  assert.doesNotMatch(
    ACCOUNT_PAGE_SOURCE,
    /Create, sign in, sign out, and delete user accounts without leaving the live platform\./,
  );
  assert.doesNotMatch(ACCOUNT_PAGE_SOURCE, /Lifecycle/);
  assert.doesNotMatch(ACCOUNT_PAGE_SOURCE, /What this deployment supports/);
});

test("account console no longer renders the first-party account status card", () => {
  assert.doesNotMatch(ACCOUNT_CONSOLE_SOURCE, /First-party account path is active/);
});

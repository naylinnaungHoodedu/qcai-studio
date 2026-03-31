import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { AUDIT_USER_ACCOUNTS, AUDIT_USER_COMMANDS } from "../src/lib/audit-user-fixtures";

const REPORT_PATH = path.resolve(process.cwd(), "..", "..", "08_Fictional_User_Accounts_and_User_Commands.md");

const REQUIRED_HEADINGS = [
  "## 1) Executive Summary",
  "## 2) Scope & Method",
  "## 3) Assumptions",
  "## 4) Account Catalog",
  "## 5) User Commands",
  "## 6) Risks & Mitigations",
  "## 7) Acceptance Criteria",
  "## 8) Test Strategy",
] as const;

test("audit fixture report keeps the required eight-section structure in order", () => {
  const report = readFileSync(REPORT_PATH, "utf8");

  let previousIndex = -1;
  for (const heading of REQUIRED_HEADINGS) {
    const index = report.indexOf(heading);
    assert.ok(index >= 0, `missing heading ${heading}`);
    assert.ok(index > previousIndex, `heading ${heading} is out of order`);
    previousIndex = index;
  }
});

test("audit fixture report stays synchronized with the canonical account and command counts", () => {
  const report = readFileSync(REPORT_PATH, "utf8");

  assert.match(
    report,
    new RegExp(`\\*\\*${AUDIT_USER_ACCOUNTS.length} fictional user accounts\\*\\* and \\*\\*${AUDIT_USER_COMMANDS.length} realistic user commands\\*\\*`),
  );
  assert.match(report, /source of truth/i);
  assert.match(report, /apps\/frontend\/src\/lib\/audit-user-fixtures\.ts/);
  assert.match(report, /apps\/frontend\/tests\/audit-user-fixtures\.integration\.test\.ts/);
});

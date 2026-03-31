import assert from "node:assert/strict";
import test from "node:test";

import {
  AUDIT_ASSUMPTIONS,
  AUDIT_JOURNEY_CATEGORIES,
  AUDIT_ROLE_CLUSTERS,
  AUDIT_USAGE_NOTES,
  AUDIT_USER_ACCOUNTS,
  AUDIT_USER_COMMANDS,
} from "../src/lib/audit-user-fixtures";

const REQUIRED_EDGE_FLAGS = [
  "accessibility-critical",
  "low-bandwidth",
  "payment-retry-open",
  "risk-review",
  "duplicate-email-review",
  "consent-required",
  "unsubscribed-marketing",
  "gdpr-request-open",
  "shared-device",
  "minor-flagged",
] as const;

test("fictional audit accounts cover the required roles with synthetic identifiers only", () => {
  assert.ok(AUDIT_USER_ACCOUNTS.length >= 12);
  assert.ok(AUDIT_USER_ACCOUNTS.length <= 20);

  const roleClusters = new Set(AUDIT_USER_ACCOUNTS.map((account) => account.roleCluster));
  for (const cluster of AUDIT_ROLE_CLUSTERS) {
    assert.ok(roleClusters.has(cluster), `missing role cluster ${cluster}`);
  }

  const accountIds = new Set<string>();
  const userIds = new Set<string>();
  const emails = new Set<string>();

  for (const account of AUDIT_USER_ACCOUNTS) {
    assert.ok(account.id.length > 0);
    assert.ok(account.userId.length > 0);
    assert.ok(account.goals.length >= 1);
    assert.ok(account.primaryDevice.length > 0);
    assert.ok(account.connectivity.length > 0);
    assert.ok(account.locale.length > 0);
    assert.ok(account.timezone.length > 0);
    assert.ok(account.languagePreference.length > 0);
    assert.ok(account.accountStatus.length > 0);
    assert.ok(account.entitlements.length >= 1);
    assert.ok(!accountIds.has(account.id), `duplicate account id ${account.id}`);
    assert.ok(!userIds.has(account.userId), `duplicate user id ${account.userId}`);
    accountIds.add(account.id);
    userIds.add(account.userId);

    if (account.email !== null) {
      assert.match(account.email, /^[a-z0-9._-]+@(ql\.test|example\.(com|org))$/);
      assert.ok(!emails.has(account.email), `duplicate email ${account.email}`);
      emails.add(account.email);
    }

    if (account.phone !== null) {
      assert.match(account.phone, /^\+1-555-010-\d{4}$/);
    }
  }
});

test("fictional audit accounts include the required edge-case coverage", () => {
  const flags = new Set(AUDIT_USER_ACCOUNTS.flatMap((account) => account.riskFlags));

  for (const flag of REQUIRED_EDGE_FLAGS) {
    assert.ok(flags.has(flag), `missing edge-case flag ${flag}`);
  }

  assert.ok(AUDIT_ASSUMPTIONS.length >= 4);
  assert.ok(AUDIT_USAGE_NOTES.length >= 2);
});

test("fictional audit commands stay complete, traceable, and category-complete", () => {
  assert.ok(AUDIT_USER_COMMANDS.length >= 40);
  assert.ok(AUDIT_USER_COMMANDS.length <= 70);

  const accountIds = new Set(AUDIT_USER_ACCOUNTS.map((account) => account.id));
  const commandIds = new Set<string>();
  const categoryCoverage = new Set<string>();
  const clusterCounts = new Map<string, number>();
  let accessibilityCommandCount = 0;
  let privacyCommandCount = 0;

  for (const command of AUDIT_USER_COMMANDS) {
    assert.ok(!commandIds.has(command.id), `duplicate command id ${command.id}`);
    commandIds.add(command.id);

    assert.ok(command.commandText.length > 0, `${command.id} missing command text`);
    assert.ok(command.preconditions.length >= 1, `${command.id} missing preconditions`);
    assert.ok(command.expectedOutcome.length >= 1, `${command.id} missing expected outcome`);
    assert.ok(command.negativeVariant.length > 0, `${command.id} missing negative variant`);
    assert.ok(command.auditFocus.length >= 1, `${command.id} missing audit focus`);
    assert.ok(command.accountIds.length >= 1, `${command.id} missing account references`);

    for (const accountId of command.accountIds) {
      assert.ok(accountIds.has(accountId), `${command.id} references unknown account ${accountId}`);
    }

    for (const category of command.categories) {
      categoryCoverage.add(category);
    }

    clusterCounts.set(command.roleCluster, (clusterCounts.get(command.roleCluster) ?? 0) + 1);

    if (command.auditFocus.includes("accessibility") || command.auditFocus.includes("performance")) {
      accessibilityCommandCount += 1;
    }

    if (command.auditFocus.includes("privacy") || command.categories.includes("data_rights_privacy")) {
      privacyCommandCount += 1;
    }
  }

  for (const category of AUDIT_JOURNEY_CATEGORIES) {
    assert.ok(categoryCoverage.has(category), `missing journey category ${category}`);
  }

  for (const cluster of ["learner", "instructor_creator", "admin_support", "manager_guardian"] as const) {
    const count = clusterCounts.get(cluster) ?? 0;
    assert.ok(count >= 8, `${cluster} has too few commands`);
    assert.ok(count <= 15, `${cluster} has too many commands`);
  }

  assert.ok(accessibilityCommandCount >= 6);
  assert.ok(privacyCommandCount >= 10);
});

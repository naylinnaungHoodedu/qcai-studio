// AC-1-10 (plan task 1.5, Action 23): the privacy page's lists must equal the lists derived from code.
// Convention this test relies on: cookie names are `qcai_*` literals and browser-storage keys are
// `qcai-*` literals, in the frontend and in the API.
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { BROWSER_STORAGE_INVENTORY, COOKIE_INVENTORY, RETENTION_SCHEDULE } from "../src/lib/privacy-disclosures";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const FRONTEND_SRC = resolve(TEST_DIR, "../src");
const API_APP = resolve(TEST_DIR, "../../api/app");

function sourceFiles(root: string, extensions: string[]): string[] {
  return readdirSync(root).flatMap((entry) => {
    const path = join(root, entry);
    if (statSync(path).isDirectory()) {
      return entry === "__pycache__" ? [] : sourceFiles(path, extensions);
    }
    return extensions.some((extension) => entry.endsWith(extension)) ? [path] : [];
  });
}

const FRONTEND_SOURCES = sourceFiles(FRONTEND_SRC, [".ts", ".tsx"]).map((path) => readFileSync(path, "utf8"));
const API_SOURCES = sourceFiles(API_APP, [".py"]).map((path) => readFileSync(path, "utf8"));

function matches(sources: string[], pattern: RegExp): Set<string> {
  return new Set(sources.flatMap((source) => [...source.matchAll(pattern)].map((match) => match[1])));
}

function codeCookieNames(): string[] {
  return [...matches([...FRONTEND_SOURCES, ...API_SOURCES], /["'`](qcai_[a-z0-9_]+)["'`]/g)].sort();
}

function codeStorageKeys(): string[] {
  const inCalls = matches(FRONTEND_SOURCES, /(?:local|session)Storage\.(?:setItem|getItem|removeItem)\(\s*["'`](qcai-[a-z0-9-]+)["'`]/g);
  const inConstants = matches(FRONTEND_SOURCES, /const \w*STORAGE_KEY\w* = ["'`](qcai-[a-z0-9-]+)["'`]/g);
  return [...new Set([...inCalls, ...inConstants])].sort();
}

function apiConstant(file: string, name: string): number {
  const source = readFileSync(resolve(API_APP, file), "utf8");
  const expression = source.match(new RegExp(`^${name} = ([0-9 *]+)$`, "m"))?.[1];
  assert.ok(expression, `${name} not found in ${file}`);
  return expression.split("*").reduce((product, factor) => product * Number(factor.trim()), 1);
}

function retentionFor(dataClass: string): string {
  const item = RETENTION_SCHEDULE.find((entry) => entry.dataClass === dataClass);
  assert.ok(item, `no retention entry for ${dataClass}`);
  return item.retention;
}

test("every cookie the code sets or reads is in the privacy page cookie inventory, and nothing else", () => {
  assert.deepEqual([...COOKIE_INVENTORY.map((item) => item.name)].sort(), codeCookieNames());
});

test("every browser-storage key the code uses is in the privacy page storage inventory, and nothing else", () => {
  assert.deepEqual([...BROWSER_STORAGE_INVENTORY.map((item) => item.key)].sort(), codeStorageKeys());
});

test("storage writes only use keys this test can see", () => {
  // A key built at run time would escape the inventory check above.
  const writes = FRONTEND_SOURCES.flatMap((source) => [...source.matchAll(/(?:local|session)Storage\.setItem\(\s*([^,]+),/g)]);
  for (const [, keyArgument] of writes) {
    assert.match(keyArgument.trim(), /^(["'`]qcai-[a-z0-9-]+["'`]|\w*STORAGE_KEY\w*|key)$/);
  }
});

test("privacy page retention periods equal the API's retention constants", () => {
  const days = (seconds: number) => seconds / (60 * 60 * 24);
  assert.match(retentionFor("Guest-linked study activity"), new RegExp(`\\b${apiConstant("services/retention.py", "GUEST_STUDY_RETENTION_DAYS")} days`));
  assert.match(retentionFor("Public web-vitals telemetry"), new RegExp(`\\b${apiConstant("services/retention.py", "PUBLIC_WEB_VITAL_RETENTION_DAYS")} days`));
  assert.match(retentionFor("Support requests"), new RegExp(`\\b${apiConstant("services/retention.py", "SUPPORT_REQUEST_RETENTION_DAYS")} days`));
  assert.match(retentionFor("Security event log"), new RegExp(`\\b${apiConstant("services/retention.py", "SECURITY_EVENT_RETENTION_DAYS")} days`));
  assert.match(retentionFor("Local account sessions"), new RegExp(`\\b${days(apiConstant("services/local_accounts.py", "AUTH_SESSION_MAX_AGE_SECONDS"))} days`));
  assert.match(retentionFor("Guest continuity cookies"), new RegExp(`\\b${days(apiConstant("core/guest_tokens.py", "GUEST_TOKEN_MAX_AGE_SECONDS"))} days`));
});

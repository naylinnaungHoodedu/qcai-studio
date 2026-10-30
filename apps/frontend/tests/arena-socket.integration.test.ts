import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const ARENA_PANEL_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/arena-panel.tsx"), "utf8");
const API_SOURCE = readFileSync(resolve(TEST_DIR, "../src/lib/api.ts"), "utf8");

// Plan task 1.4: the API takes the player from a session ticket, so the browser never asserts an identity.
test("the arena socket offers the session ticket as a subprotocol, never in the URL", () => {
  assert.match(ARENA_PANEL_SOURCE, /ticket = await requestArenaTicket\(\)/);
  assert.match(ARENA_PANEL_SOURCE, /new WebSocket\(url, \[ticket\.protocol, ticket\.ticket\]\)/);
  assert.doesNotMatch(ARENA_PANEL_SOURCE, /searchParams\.set\("(?:player_id|ticket)"/);
  assert.match(API_SOURCE, /apiFetch<ArenaTicket>\("\/arena\/ticket", \{ method: "POST" \}\)/);
});

test("the arena panel deletes the old browser-chosen player id and reads its own profile", () => {
  assert.match(ARENA_PANEL_SOURCE, /localStorage\.removeItem\(LEGACY_PLAYER_ID_STORAGE_KEY\)/);
  assert.doesNotMatch(ARENA_PANEL_SOURCE, /localStorage\.setItem\(LEGACY_PLAYER_ID_STORAGE_KEY/);
  assert.match(ARENA_PANEL_SOURCE, /queryFn: fetchOwnArenaProfile/);
  assert.doesNotMatch(ARENA_PANEL_SOURCE, /player_id/);
});

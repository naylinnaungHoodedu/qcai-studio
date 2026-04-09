import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const VIDEO_PANEL_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/video-panel.tsx"), "utf8");

test("video panel bootstraps lesson media with a tiny byte-range request before attaching the source", () => {
  assert.match(VIDEO_PANEL_SOURCE, /await fetch\(streamUrl,\s*\{/);
  assert.match(VIDEO_PANEL_SOURCE, /method: "GET"/);
  assert.match(VIDEO_PANEL_SOURCE, /Range: "bytes=0-1023"/);
  assert.match(VIDEO_PANEL_SOURCE, /!\[200, 206\]\.includes\(response\.status\)/);
});

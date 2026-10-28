import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const GLOBALS_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/globals.css"), "utf8");
const THEME_TOGGLE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/theme-toggle.tsx"), "utf8");
const APP_SHELL_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/app-shell.tsx"), "utf8");
const LAYOUT_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/layout.tsx"), "utf8");

test("theme toggle persists the choice and flips the html data-theme attribute", () => {
  assert.match(THEME_TOGGLE_SOURCE, /"use client"/);
  assert.match(THEME_TOGGLE_SOURCE, /document\.documentElement\.dataset\.theme = next/);
  assert.match(THEME_TOGGLE_SOURCE, /localStorage\.setItem\("qcai-theme", next\)/);
  assert.match(THEME_TOGGLE_SOURCE, /aria-pressed=/);
  assert.match(THEME_TOGGLE_SOURCE, /aria-label=\{label\}/);
});

test("app shell mounts the theme toggle in the header", () => {
  assert.match(APP_SHELL_SOURCE, /import \{ ThemeToggle \}/);
  assert.match(APP_SHELL_SOURCE, /<ThemeToggle \/>/);
});

test("layout applies the saved theme before paint via a nonce'd inline script", () => {
  assert.match(LAYOUT_SOURCE, /nonce=\{nonce\}/);
  assert.match(LAYOUT_SOURCE, /qcai-theme/);
  assert.match(LAYOUT_SOURCE, /document\.documentElement\.dataset\.theme/);
});

test("dark stays the default and light is an additive opt-in theme block", () => {
  // Dark defaults live on :root with no data-theme requirement.
  assert.match(GLOBALS_SOURCE, /:root \{/);
  // Light theme is scoped so it cannot affect the default experience.
  assert.match(GLOBALS_SOURCE, /:root\[data-theme="light"\] \{/);
  assert.match(GLOBALS_SOURCE, /:root\[data-theme="light"\] body \{/);
  assert.match(GLOBALS_SOURCE, /\.theme-toggle \{/);
});

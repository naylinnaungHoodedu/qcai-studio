import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { closeOpenNavGroups } from "../src/lib/nav-disclosure";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const GLOBALS_SOURCE = readFileSync(
  resolve(TEST_DIR, "../src/app/globals.css"),
  "utf8",
);
const PRIMARY_NAV_SOURCE = readFileSync(
  resolve(TEST_DIR, "../src/components/primary-nav.tsx"),
  "utf8",
);

test("closing nav groups removes the open attribute from every expanded details element", () => {
  let selector = "";
  let removed = 0;

  closeOpenNavGroups({
    querySelectorAll(query) {
      selector = query;
      return [
        { removeAttribute(name: string) {
          assert.equal(name, "open");
          removed += 1;
        } },
        { removeAttribute(name: string) {
          assert.equal(name, "open");
          removed += 1;
        } },
      ];
    },
  });

  assert.equal(selector, "details[open]");
  assert.equal(removed, 2);
});

test("primary nav closes open groups on submenu click and pathname changes", () => {
  assert.match(PRIMARY_NAV_SOURCE, /usePathname/);
  assert.match(PRIMARY_NAV_SOURCE, /useState<string \| null>\(null\)/);
  assert.match(PRIMARY_NAV_SOURCE, /const isMenuOpen = openMenuPathname === pathname/);
  assert.match(PRIMARY_NAV_SOURCE, /ref=\{shellRef\}/);
  assert.match(PRIMARY_NAV_SOURCE, /ref=\{navRef\}/);
  assert.match(PRIMARY_NAV_SOURCE, /function handleNavAction\(\)\s*\{\s*setOpenMenuPathname\(null\);\s*closeOpenNavGroups\(navRef\.current\);/);
  assert.match(PRIMARY_NAV_SOURCE, /useEffect\(\(\) => \{\s*closeOpenNavGroups\(navRef\.current\);\s*\}, \[pathname\]\);/);
  assert.match(PRIMARY_NAV_SOURCE, /window\.addEventListener\("pointerdown", handlePointerDown\)/);
  assert.match(PRIMARY_NAV_SOURCE, /window\.addEventListener\("keydown", handleKeyDown\)/);
  assert.match(PRIMARY_NAV_SOURCE, /aria-controls="primary-navigation-panel"/);
  assert.match(PRIMARY_NAV_SOURCE, /className=\{`site-nav \$\{isMenuOpen \? "is-open" : ""\}`\}/);
  assert.match(PRIMARY_NAV_SOURCE, /onClick=\{handleNavAction\}/);
});

test("responsive navigation CSS swaps desktop pills for a controlled mobile panel", () => {
  assert.match(GLOBALS_SOURCE, /@media \(max-width: 1100px\)/);
  assert.match(GLOBALS_SOURCE, /\.site-nav-toggle\s*\{[\s\S]*display: inline-flex;/);
  assert.match(GLOBALS_SOURCE, /\.site-nav\s*\{[\s\S]*position: absolute;[\s\S]*max-width: none;[\s\S]*display: none;/);
  assert.match(GLOBALS_SOURCE, /\.site-nav\.is-open\s*\{\s*display: grid;/);
  assert.match(GLOBALS_SOURCE, /@media \(max-width: 720px\)[\s\S]*\.site-nav-shell\s*\{[\s\S]*width: 100%;/);
  assert.match(GLOBALS_SOURCE, /@media \(max-width: 720px\)[\s\S]*\.site-nav\s*\{[\s\S]*max-width: 100%;/);
});

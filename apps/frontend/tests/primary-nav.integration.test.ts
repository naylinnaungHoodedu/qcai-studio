import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { closeOpenNavGroups } from "../src/lib/nav-disclosure";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
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
  assert.match(PRIMARY_NAV_SOURCE, /ref=\{navRef\}/);
  assert.match(PRIMARY_NAV_SOURCE, /function handleNavAction\(\)\s*\{\s*closeOpenNavGroups\(navRef\.current\);/);
  assert.match(PRIMARY_NAV_SOURCE, /useEffect\(\(\) => \{\s*closeOpenNavGroups\(navRef\.current\);\s*\}, \[pathname\]\);/);
  assert.match(PRIMARY_NAV_SOURCE, /onClick=\{handleNavAction\}/);
});

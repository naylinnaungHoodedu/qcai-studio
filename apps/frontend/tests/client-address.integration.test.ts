import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { clientAddressHeaderValue } from "../src/lib/guest-session";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const PROXY_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/api/backend/[...path]/route.ts"), "utf8");
const GUEST_SESSION_SOURCE = readFileSync(resolve(TEST_DIR, "../src/lib/guest-session.ts"), "utf8");

// The same vectors are checked on the API side (apps/api/tests/test_rate_limit.py), so both ends agree.
const VECTORS: Array<[string, string]> = [
  ["198.51.100.7", "198.51.100.7 b73c021526b8923cad3bbc5d977de632"],
  ["2001:db8::7", "2001:db8::7 62d6fe6ce7efe95fe3c51eec7b70e967"],
];

function withDevelopmentSecret(run: () => void): void {
  const saved = { secret: process.env.GUEST_TOKEN_SECRET, hops: process.env.CLIENT_ADDRESS_HOPS };
  delete process.env.GUEST_TOKEN_SECRET;
  delete process.env.CLIENT_ADDRESS_HOPS;
  try {
    run();
  } finally {
    if (saved.secret !== undefined) process.env.GUEST_TOKEN_SECRET = saved.secret;
    if (saved.hops !== undefined) process.env.CLIENT_ADDRESS_HOPS = saved.hops;
  }
}

test("the proxy vouches for the rightmost forwarded address in the API's MAC format (task 1.6)", () => {
  withDevelopmentSecret(() => {
    for (const [address, expected] of VECTORS) {
      const headers = new Headers({ "x-forwarded-for": `203.0.113.250, ${address}` });
      assert.equal(clientAddressHeaderValue({ headers } as never), expected);
    }
    assert.equal(clientAddressHeaderValue({ headers: new Headers() } as never), null);
  });
});

test("the server-side legacy upgrade call vouches for the client address too", () => {
  const upgrade = GUEST_SESSION_SOURCE.slice(GUEST_SESSION_SOURCE.indexOf("export async function resolveGuestSessionWithLegacyUpgrade"));
  const call = upgrade.slice(0, upgrade.indexOf("/auth/guest-upgrade"));
  assert.match(call, /headers\.set\(CLIENT_ADDRESS_HEADER_NAME, clientAddress\)/);
});

test("the proxy drops a browser-sent client address before setting its own", () => {
  const dropped = PROXY_SOURCE.indexOf("headers.delete(CLIENT_ADDRESS_HEADER_NAME)");
  const set = PROXY_SOURCE.indexOf("headers.set(CLIENT_ADDRESS_HEADER_NAME, clientAddress)");
  assert.ok(dropped > 0 && set > dropped);
});

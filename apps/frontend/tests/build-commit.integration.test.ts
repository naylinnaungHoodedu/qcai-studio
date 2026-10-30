import assert from "node:assert/strict";
import test from "node:test";

import { GET as frontendHealthRoute } from "../src/app/health/route";

const COMMIT = "95336ed886c620d9a639ef0250daa99c1fcf1549";

// AC-1-7: /health reports the commit the image was built from, so the deployment record can be checked.
test("the frontend health route reports the image's build commit", async () => {
  const saved = process.env.GIT_SHA;
  try {
    process.env.GIT_SHA = COMMIT;
    assert.equal((await frontendHealthRoute().json()).commit, COMMIT);
    delete process.env.GIT_SHA;
    assert.equal((await frontendHealthRoute().json()).commit, "unknown");
  } finally {
    if (saved === undefined) {
      delete process.env.GIT_SHA;
    } else {
      process.env.GIT_SHA = saved;
    }
  }
});

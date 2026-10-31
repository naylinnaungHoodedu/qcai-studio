// Plan Phase 1, item I: the frontend server's logs reach the platform as JSON lines, like the API's.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { Console } from "node:console";
import { dirname, resolve } from "node:path";
import { Writable } from "node:stream";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { installJsonConsole, LOGGER, REDACTED } from "../src/lib/server-log";

const FRONTEND_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SECRET = "frontend-log-test-secret-0123456789";

type Entry = Record<string, string>;

function capture() {
  const out: string[] = [];
  const err: string[] = [];
  const discard = new Writable({ write: (_chunk, _encoding, done) => done() });
  const target = new Console(discard, discard);
  installJsonConsole(target, { write: (chunk: string) => out.push(chunk) }, { write: (chunk: string) => err.push(chunk) });
  return { target, out, err };
}

function entries(chunks: string[]): Entry[] {
  const lines = chunks.join("").split("\n").filter(Boolean);
  return lines.map((line) => JSON.parse(line) as Entry);
}

test("each console call is one JSON line with the API's keys and a severity per level", () => {
  const { target, out, err } = capture();
  target.debug("checked %d routes", 3);
  target.info("ready");
  target.log("hello %s", "world");
  target.warn("slow upstream");
  target.error("upstream failed");

  assert.deepEqual(entries(out).map((entry) => [entry.severity, entry.message]), [["DEBUG", "checked 3 routes"], ["INFO", "ready"], ["INFO", "hello world"]]);
  assert.deepEqual(entries(err).map((entry) => [entry.severity, entry.message]), [["WARNING", "slow upstream"], ["ERROR", "upstream failed"]]);
  for (const entry of [...entries(out), ...entries(err)]) {
    assert.deepEqual(Object.keys(entry).sort(), ["logger", "message", "severity", "time"]);
    assert.equal(entry.logger, LOGGER);
    assert.ok(!Number.isNaN(Date.parse(entry.time)) && entry.time.endsWith("Z"));
  }
});

test("an error and its stack stay in one entry, with Next.js's digest as a field", () => {
  const { target, err } = capture();
  target.error(Object.assign(new Error("render failed"), { digest: "2711968520" }));

  assert.equal(err.join("").split("\n").filter(Boolean).length, 1, "one line, however long the stack");
  const [entry] = entries(err);
  assert.equal(entry.severity, "ERROR");
  assert.match(entry.message, /^Error: render failed\n\s+at /);
  assert.equal(entry.digest, "2711968520");
});

test("credentials never reach the log line", () => {
  const saved = process.env.GUEST_TOKEN_SECRET;
  process.env.GUEST_TOKEN_SECRET = SECRET;
  try {
    const { target, err } = capture();
    target.error(
      `signing with ${SECRET} failed`,
      { headers: { authorization: "Bearer header.payload.signature", cookie: "session_token=s3ss10n; theme=dark" } },
      "https://api.example.test/lessons?token=t0k3n&page=2",
      new Error(`stack carries ${SECRET}`),
    );

    const line = err.join("");
    for (const leaked of [SECRET, "header.payload.signature", "s3ss10n", "t0k3n"]) {
      assert.ok(!line.includes(leaked), `${leaked} leaked: ${line}`);
    }
    assert.ok(line.includes(REDACTED) && line.includes("page=2"), "only the credentials are masked");
  } finally {
    if (saved === undefined) {
      delete process.env.GUEST_TOKEN_SECRET;
    } else {
      process.env.GUEST_TOKEN_SECRET = saved;
    }
  }
});

test("installing twice still writes one line per call", () => {
  // Next.js calls the hook once per server, but a second call must not double every line.
  const out: string[] = [];
  const discard = new Writable({ write: (_chunk, _encoding, done) => done() });
  const target = new Console(discard, discard);
  const sink = { write: (chunk: string) => out.push(chunk) };
  installJsonConsole(target, sink, sink);
  installJsonConsole(target, sink, sink);
  target.info("once");

  assert.equal(entries(out).length, 1);
});

function startServer(nodeEnv: "production" | "development") {
  // A real Node.js process runs the instrumentation hook as Next.js does at start-up, then logs.
  const instrumentation = pathToFileURL(resolve(FRONTEND_ROOT, "src/instrumentation.ts")).href;
  const script = [
    // tsx loads the module as CommonJS here, so its exports sit under `default`.
    `const loaded = await import(${JSON.stringify(instrumentation)});`,
    "const { register } = loaded.register ? loaded : loaded.default;",
    "await register();",
    'console.log("server ready");',
    'console.error(Object.assign(new Error("render failed"), { digest: "42" }));',
  ].join("\n");
  return spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "--eval", script], {
    cwd: FRONTEND_ROOT,
    encoding: "utf8",
    env: { ...process.env, NEXT_RUNTIME: "nodejs", NODE_ENV: nodeEnv },
    timeout: 60_000,
  });
}

test("the production server installs the JSON console at start-up", () => {
  const result = startServer("production");
  assert.equal(result.status, 0, result.stderr);

  const [ready] = result.stdout.split("\n").filter(Boolean).map((line) => JSON.parse(line) as Entry);
  assert.deepEqual([ready.severity, ready.message], ["INFO", "server ready"]);
  const failures = result.stderr.split("\n").filter(Boolean);
  assert.equal(failures.length, 1, result.stderr);
  const failure = JSON.parse(failures[0]) as Entry;
  assert.deepEqual([failure.severity, failure.digest], ["ERROR", "42"]);
  assert.match(failure.message, /^Error: render failed\n\s+at /);
});

test("development keeps plain console output", () => {
  const result = startServer("development");
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), "server ready");
});

// Server logs as one JSON object per line, the shape Cloud Logging reads (plan Phase 1, item I).
//
// Next.js and this app's server code log through `console`, so a server error reached the platform as one
// plain-text entry per stack line, with no severity. Installed from src/instrumentation.ts, each console call
// on the Node.js server becomes one line with `severity`, `message`, `logger` and `time`, as the API writes
// them (apps/api/app/core/structured_logging.py). A stack stays inside its entry, and Next.js's error
// `digest`, the only part of a server error it sends to the browser, becomes a field to search on.
// Credentials in the message are masked as in the API (Action 24, AC-1-8): the guest-token secrets,
// credential headers, cookie values and key-like URL parameters.
import { format } from "node:util";

export const LOGGER = "frontend";
export const REDACTED = "[REDACTED]";

type Level = "debug" | "info" | "log" | "warn" | "error";
type Sink = { write(chunk: string): unknown };

const LEVELS: readonly Level[] = ["debug", "info", "log", "warn", "error"];
const SEVERITY: Record<Level, string> = { debug: "DEBUG", info: "INFO", log: "INFO", warn: "WARNING", error: "ERROR" };
const MIN_SECRET_LENGTH = 8;
const SECRET_SETTINGS = ["GUEST_TOKEN_SECRET", "GUEST_TOKEN_PREVIOUS_SECRET"];
const QUERY_SECRET = /([?&](?:key|api_key|apikey|access_token|token)=)[^&\s'"]+/gi;
const HEADER_SECRET = /((?:x-goog-api-key|x-api-key|authorization)['"]?\s*[:=]\s*['"]?(?:bearer\s+)?)[^\s'",}]+/gi;
// Cookies carry the session and guest credentials, so the whole header value is masked.
const COOKIE_HEADER = /((?:set-)?cookie['"]?\s*[:=]\s*['"]?)[^'"\r\n}]+/gi;

export function redact(text: string): string {
  const secrets = SECRET_SETTINGS.map((name) => process.env[name]?.trim() ?? "")
    .filter((value) => value.length >= MIN_SECRET_LENGTH)
    .sort((left, right) => right.length - left.length);
  let masked = text;
  for (const secret of secrets) {
    masked = masked.split(secret).join(REDACTED);
  }
  return masked
    .replace(QUERY_SECRET, `$1${REDACTED}`)
    .replace(HEADER_SECRET, `$1${REDACTED}`)
    .replace(COOKIE_HEADER, `$1${REDACTED}`);
}

function digestOf(args: unknown[]): string | undefined {
  for (const arg of args) {
    const digest = arg instanceof Error ? (arg as Error & { digest?: unknown }).digest : undefined;
    if (typeof digest === "string") {
      return digest;
    }
  }
  return undefined;
}

export function formatEntry(level: Level, args: unknown[], now: Date = new Date()): string {
  const time = now.toISOString();
  try {
    // util.format renders arguments as console does, an Error with its stack.
    const entry: Record<string, string> = { logger: LOGGER, message: redact(format(...args)), severity: SEVERITY[level], time };
    const digest = digestOf(args);
    if (digest) {
      entry.digest = digest;
    }
    return JSON.stringify(entry);
  } catch {
    // Never let logging itself fail.
    return JSON.stringify({ logger: LOGGER, message: "[log message withheld: formatting failed]", severity: SEVERITY[level], time });
  }
}

/** Route console output through one JSON line per call. The methods are replaced, not wrapped, so installing again is harmless. */
export function installJsonConsole(target: Console = console, out: Sink = process.stdout, err: Sink = process.stderr): void {
  for (const level of LEVELS) {
    const sink = level === "warn" || level === "error" ? err : out;
    target[level] = (...args: unknown[]) => {
      sink.write(`${formatEntry(level, args)}\n`);
    };
  }
}

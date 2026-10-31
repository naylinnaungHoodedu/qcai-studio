// Runs once when a Next.js server starts, before it serves a request (plan Phase 1, item I). On the
// production Node.js server, console output becomes one JSON line per call (src/lib/server-log.ts), so the
// platform keeps each entry whole and reads its severity. Development keeps Next.js's readable output.
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME === "nodejs" && process.env.NODE_ENV === "production") {
    const { installJsonConsole } = await import("./lib/server-log");
    installJsonConsole();
  }
}

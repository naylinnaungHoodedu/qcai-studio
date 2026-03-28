import { readFileSync } from "node:fs";
import { join } from "node:path";

const manifestPath = join(process.cwd(), ".next", "server", "app-paths-manifest.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));

if (!manifest["/account/page"]) {
  console.error("The /account route is missing from the Next.js build manifest.");
  process.exit(1);
}

console.log("Verified /account route in build manifest.");

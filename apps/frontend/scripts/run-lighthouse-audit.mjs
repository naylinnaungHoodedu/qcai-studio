import { URL } from "node:url";

import lighthouse from "lighthouse";
import * as chromeLauncher from "chrome-launcher";

const DEFAULT_BASE_URL = process.env.LIGHTHOUSE_BASE_URL || "http://127.0.0.1:3000";
const DEFAULT_PAGES = [
  "/",
  "/modules",
  "/lessons/nisq-reality-overview",
  "/builder",
  "/account",
  "/support",
];

const THRESHOLDS = {
  "/": { performance: 0.8, accessibility: 0.95, "best-practices": 0.9, seo: 0.9 },
  "/modules": { performance: 0.8, accessibility: 0.95, "best-practices": 0.9, seo: 0.9 },
  "/lessons/nisq-reality-overview": { performance: 0.75, accessibility: 0.95, "best-practices": 0.9, seo: null },
  "/builder": { performance: 0.7, accessibility: 0.95, "best-practices": 0.9, seo: null },
  "/account": { performance: 0.8, accessibility: 0.95, "best-practices": 0.9, seo: null },
  "/support": { performance: 0.8, accessibility: 0.95, "best-practices": 0.9, seo: 0.9 },
};

function readArg(flag) {
  const inline = process.argv.find((value) => value.startsWith(`${flag}=`));
  if (inline) {
    return inline.slice(flag.length + 1);
  }
  const index = process.argv.indexOf(flag);
  if (index === -1 || index === process.argv.length - 1) {
    return null;
  }
  return process.argv[index + 1];
}

function resolveMode() {
  return readArg("--mode") || "full";
}

function resolveBaseUrl() {
  return readArg("--baseUrl") || DEFAULT_BASE_URL;
}

function formatScore(value) {
  return Math.round(value * 100);
}

async function main() {
  const mode = resolveMode();
  const baseUrl = resolveBaseUrl();
  const categories = mode === "a11y" ? ["accessibility"] : ["performance", "accessibility", "best-practices", "seo"];
  const failures = [];
  const chrome = await chromeLauncher.launch({
    chromeFlags: ["--headless=new", "--disable-gpu", "--no-sandbox"],
  });

  try {
    for (const page of DEFAULT_PAGES) {
      const targetUrl = new URL(page, baseUrl).toString();
      const runnerResult = await lighthouse(
        targetUrl,
        {
          port: chrome.port,
          logLevel: "error",
          onlyCategories: categories,
        },
      );

      if (!runnerResult) {
        failures.push(`${page}: Lighthouse did not return a result.`);
        continue;
      }

      const expected = THRESHOLDS[page];
      const measured = runnerResult.lhr.categories;

      for (const category of categories) {
        const actualScore = measured[category]?.score ?? 0;
        const expectedScore = expected?.[category];
        if (typeof expectedScore !== "number") {
          continue;
        }
        if (actualScore < expectedScore) {
          failures.push(
            `${page}: ${category} ${formatScore(actualScore)} fell below ${formatScore(expectedScore)}.`,
          );
        }
      }

      const summary = categories
        .map((category) => `${category} ${formatScore(measured[category]?.score ?? 0)}`)
        .join(" | ");
      console.log(`${page}: ${summary}`);
    }
  } finally {
    await chrome.kill();
  }

  if (failures.length) {
    console.error("\nLighthouse audit failures:");
    for (const failure of failures) {
      console.error(`- ${failure}`);
    }
    process.exit(1);
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});

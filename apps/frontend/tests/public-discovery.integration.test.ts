import assert from "node:assert/strict";
import test from "node:test";

import nextConfig from "../next.config";
import { metadata as homeMetadata } from "../src/app/page";
import { metadata as simulationsMetadata } from "../src/app/simulations/page";
import { metadata as whatsNewMetadata } from "../src/app/whats-new/page";
import robots from "../src/app/robots";
import sitemap from "../src/app/sitemap";
import { SITE_URL } from "../src/lib/site";

test("sitemap publishes public study and simulations routes", () => {
  const entries = sitemap();
  const urls = new Set(entries.map((entry) => entry.url));

  assert.ok(urls.has(`${SITE_URL}/about`));
  assert.ok(urls.has(`${SITE_URL}/modules`));
  assert.ok(urls.has(`${SITE_URL}/simulations`));
  assert.ok(urls.has(`${SITE_URL}/whats-new`));
  assert.ok(urls.has(`${SITE_URL}/lessons/clinical-and-kernel-qcai-systems`));
  assert.ok(urls.has(`${SITE_URL}/flashcards/clinical-and-kernel-qcai-systems`));
  assert.ok(urls.has(`${SITE_URL}/quiz/clinical-and-kernel-qcai-systems`));
});

test("sitemap lastmod values reflect curated content updates instead of a single build timestamp", () => {
  const entries = sitemap();
  const lastModifiedValues = new Set(
    entries.map((entry) => new Date(entry.lastModified ?? 0).toISOString().slice(0, 10)),
  );

  assert.ok(lastModifiedValues.has("2026-03-28"));
  assert.ok(lastModifiedValues.has("2026-03-29"));
  assert.ok(lastModifiedValues.size >= 2);
});

test("robots keeps the about page public while private surfaces stay blocked", () => {
  const metadata = robots();
  const rule = Array.isArray(metadata.rules) ? metadata.rules[0] : metadata.rules;
  const disallow = Array.isArray(rule.disallow) ? rule.disallow : [rule.disallow].filter(Boolean);

  assert.equal(rule.allow, "/");
  assert.ok(disallow.includes("/account"));
  assert.ok(disallow.includes("/dashboard"));
  assert.ok(!disallow.includes("/about"));
  assert.ok(!disallow.includes("/modules"));
  assert.equal(metadata.sitemap, `${SITE_URL}/sitemap.xml`);
});

test("homepage metadata exposes a real title and social image", () => {
  assert.equal(homeMetadata.title, "Quantum Computing and AI Course");
  assert.ok(homeMetadata.openGraph?.images);
  assert.ok(homeMetadata.twitter?.images);
});

test("simulations metadata exposes a descriptive title and social image", () => {
  assert.equal(simulationsMetadata.title, "Quantum Computing and AI Simulations");
  assert.ok(simulationsMetadata.openGraph?.images);
  assert.ok(simulationsMetadata.twitter?.images);
});

test("what's new metadata exposes a descriptive title and social image", () => {
  assert.equal(whatsNewMetadata.title, "What's New and Product Roadmap");
  assert.ok(whatsNewMetadata.openGraph?.images);
  assert.ok(whatsNewMetadata.twitter?.images);
});

test("public routes advertise revalidation-friendly cache headers", async () => {
  const routes = (await nextConfig.headers?.()) ?? [];
  const homeHeaders = routes.find((route) => route.source === "/");
  const whatsNewHeaders = routes.find((route) => route.source === "/whats-new");

  assert.ok(homeHeaders);
  assert.ok(whatsNewHeaders);
  assert.equal(homeHeaders.headers[0]?.key, "Cache-Control");
  assert.equal(
    homeHeaders.headers[0]?.value,
    "public, max-age=0, s-maxage=300, stale-while-revalidate=86400",
  );
});

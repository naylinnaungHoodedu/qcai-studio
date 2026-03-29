import assert from "node:assert/strict";
import test from "node:test";

import { metadata as homeMetadata } from "../src/app/page";
import { metadata as simulationsMetadata } from "../src/app/simulations/page";
import robots from "../src/app/robots";
import sitemap from "../src/app/sitemap";
import { SITE_URL } from "../src/lib/site";

test("sitemap publishes public study and simulations routes", () => {
  const entries = sitemap();
  const urls = new Set(entries.map((entry) => entry.url));

  assert.ok(urls.has(`${SITE_URL}/about`));
  assert.ok(urls.has(`${SITE_URL}/modules`));
  assert.ok(urls.has(`${SITE_URL}/simulations`));
  assert.ok(urls.has(`${SITE_URL}/lessons/clinical-and-kernel-qcai-systems`));
  assert.ok(urls.has(`${SITE_URL}/flashcards/clinical-and-kernel-qcai-systems`));
  assert.ok(urls.has(`${SITE_URL}/quiz/clinical-and-kernel-qcai-systems`));
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

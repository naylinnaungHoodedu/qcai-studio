import assert from "node:assert/strict";
import test from "node:test";

import nextConfig from "../next.config";
import { metadata as homeMetadata } from "../src/app/page";
import {
  generateMetadata as generateAcademySimulationMetadata,
  generateStaticParams as generateAcademySimulationStaticParams,
} from "../src/app/simulations/subjects/[subjectSlug]/[simulationSlug]/page";
import {
  generateMetadata as generateAcademySubjectMetadata,
  generateStaticParams as generateAcademySubjectStaticParams,
} from "../src/app/simulations/subjects/[subjectSlug]/page";
import {
  generateMetadata as generateSimulationMetadata,
  generateStaticParams as generateSimulationStaticParams,
} from "../src/app/simulations/[slug]/page";
import { metadata as simulationsMetadata } from "../src/app/simulations/page";
import { metadata as whatsNewMetadata } from "../src/app/whats-new/page";
import robots from "../src/app/robots";
import sitemap from "../src/app/sitemap";
import {
  ACADEMY_SIMULATION_RECORDS,
  ACADEMY_SUBJECT_RECORDS,
} from "../src/lib/academy-simulations";
import { SIMULATION_SLUGS } from "../src/lib/simulations";
import { SITE_URL } from "../src/lib/site";

test("sitemap publishes public study and simulations routes", () => {
  const entries = sitemap();
  const urls = new Set(entries.map((entry) => entry.url));

  assert.ok(urls.has(`${SITE_URL}/about`));
  assert.ok(urls.has(`${SITE_URL}/support`));
  assert.ok(urls.has(`${SITE_URL}/modules`));
  assert.ok(urls.has(`${SITE_URL}/simulations`));
  assert.ok(urls.has(`${SITE_URL}/simulations/the-nisq-fidelity-cliff`));
  assert.ok(urls.has(`${SITE_URL}/simulations/subjects/quantum-mechanics-and-information`));
  assert.ok(
    urls.has(
      `${SITE_URL}/simulations/subjects/quantum-mechanics-and-information/bloch-sphere-visualizer`,
    ),
  );
  assert.ok(urls.has(`${SITE_URL}/whats-new`));
  assert.ok(urls.has(`${SITE_URL}/modules/hardware-constrained-models`));
  assert.ok(urls.has(`${SITE_URL}/lessons/hardware-constrained-qcai-models`));
  assert.ok(urls.has(`${SITE_URL}/lessons/clinical-and-kernel-qcai-systems`));
  assert.ok(urls.has(`${SITE_URL}/flashcards/clinical-and-kernel-qcai-systems`));
  assert.ok(urls.has(`${SITE_URL}/quiz/clinical-and-kernel-qcai-systems`));
  assert.equal(
    SIMULATION_SLUGS.filter((slug) => urls.has(`${SITE_URL}/simulations/${slug}`)).length,
    SIMULATION_SLUGS.length,
  );
  assert.equal(
    ACADEMY_SUBJECT_RECORDS.filter((subject) => urls.has(`${SITE_URL}${subject.href}`)).length,
    ACADEMY_SUBJECT_RECORDS.length,
  );
  assert.equal(
    ACADEMY_SIMULATION_RECORDS.filter((simulation) => urls.has(`${SITE_URL}${simulation.href}`)).length,
    ACADEMY_SIMULATION_RECORDS.length,
  );
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

test("simulation detail routes publish static params for all separated labs", () => {
  const params = generateSimulationStaticParams();

  assert.equal(params.length, SIMULATION_SLUGS.length);
  assert.ok(params.some((entry) => entry.slug === "the-nisq-fidelity-cliff"));
  assert.ok(params.some((entry) => entry.slug === "post-quantum-cryptography-migration-simulator"));
});

test("academy subject routes publish static params for all five subjects", () => {
  const params = generateAcademySubjectStaticParams();

  assert.equal(params.length, ACADEMY_SUBJECT_RECORDS.length);
  assert.ok(params.some((entry) => entry.subjectSlug === "quantum-algorithms"));
  assert.ok(params.some((entry) => entry.subjectSlug === "quantum-finance-and-optimization"));
});

test("academy simulation routes publish static params for all additional labs", () => {
  const params = generateAcademySimulationStaticParams();

  assert.equal(params.length, ACADEMY_SIMULATION_RECORDS.length);
  assert.ok(
    params.some(
      (entry) =>
        entry.subjectSlug === "quantum-mechanics-and-information" &&
        entry.simulationSlug === "bloch-sphere-visualizer",
    ),
  );
  assert.ok(
    params.some(
      (entry) =>
        entry.subjectSlug === "quantum-finance-and-optimization" &&
        entry.simulationSlug === "quantum-monte-carlo-option-pricing-lab",
    ),
  );
});

test("simulation detail metadata exposes per-lab title and social image", async () => {
  const metadata = await generateSimulationMetadata({
    params: Promise.resolve({ slug: "the-nisq-fidelity-cliff" }),
  });

  assert.equal(metadata.title, "The NISQ Fidelity Cliff");
  assert.ok(metadata.openGraph?.images);
  assert.ok(metadata.twitter?.images);
});

test("academy subject metadata exposes per-subject titles and social image", async () => {
  const metadata = await generateAcademySubjectMetadata({
    params: Promise.resolve({ subjectSlug: "quantum-mechanics-and-information" }),
  });

  assert.equal(metadata.title, "Quantum Mechanics & Information");
  assert.ok(metadata.openGraph?.images);
  assert.ok(metadata.twitter?.images);
});

test("academy simulation metadata exposes per-lab title and social image", async () => {
  const metadata = await generateAcademySimulationMetadata({
    params: Promise.resolve({
      subjectSlug: "quantum-mechanics-and-information",
      simulationSlug: "bloch-sphere-visualizer",
    }),
  });

  assert.equal(metadata.title, "Bloch Sphere Visualizer");
  assert.ok(metadata.openGraph?.images);
  assert.ok(metadata.twitter?.images);
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
  const securityHeaders = routes.find((route) => route.source === "/:path*");
  const supportHeaders = routes.find((route) => route.source === "/support");

  assert.ok(homeHeaders);
  assert.ok(whatsNewHeaders);
  assert.ok(securityHeaders);
  assert.ok(supportHeaders);
  assert.equal(homeHeaders.headers[0]?.key, "Cache-Control");
  assert.equal(
    homeHeaders.headers[0]?.value,
    "public, max-age=0, s-maxage=300, stale-while-revalidate=86400",
  );
  assert.ok(
    securityHeaders.headers.some(
      (header) => header.key === "Cross-Origin-Opener-Policy" && header.value === "same-origin",
    ),
  );
  assert.ok(
    securityHeaders.headers.some(
      (header) => header.key === "Cross-Origin-Resource-Policy" && header.value === "same-site",
    ),
  );
  assert.equal(
    supportHeaders.headers[0]?.value,
    "public, max-age=0, s-maxage=300, stale-while-revalidate=86400",
  );
});

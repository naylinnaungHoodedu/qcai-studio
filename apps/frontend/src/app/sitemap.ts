import type { MetadataRoute } from "next";

import {
  ACADEMY_SIMULATION_RECORDS,
  ACADEMY_SIMULATION_ROUTE_LASTMOD,
  ACADEMY_SUBJECT_RECORDS,
  ACADEMY_SUBJECT_ROUTE_LASTMOD,
} from "@/lib/academy-simulations";
import {
  LESSON_ROUTE_LASTMOD,
  LESSON_SLUGS,
  MODULE_ROUTE_LASTMOD,
  MODULE_SLUGS,
  SITE_URL,
  STATIC_ROUTE_LASTMOD,
} from "@/lib/site";
import { SIMULATION_ROUTE_LASTMOD, SIMULATION_SLUGS } from "@/lib/simulations";

const STATIC_ROUTES: Array<{ path: string; priority: number }> = [
  { path: "/", priority: 1 },
  { path: "/modules", priority: 0.9 },
  { path: "/simulations", priority: 0.85 },
  { path: "/about", priority: 0.7 },
  { path: "/whats-new", priority: 0.65 },
  { path: "/syllabus", priority: 0.8 },
  { path: "/privacy", priority: 0.3 },
  { path: "/terms", priority: 0.3 },
  { path: "/attribution", priority: 0.3 },
];

export default function sitemap(): MetadataRoute.Sitemap {
  const staticEntries: MetadataRoute.Sitemap = STATIC_ROUTES.map((route) => ({
    url: `${SITE_URL}${route.path}`,
    lastModified: new Date(STATIC_ROUTE_LASTMOD[route.path] ?? "2026-03-27T00:00:00Z"),
    changeFrequency: "weekly",
    priority: route.priority,
  }));
  const moduleEntries: MetadataRoute.Sitemap = MODULE_SLUGS.map((slug) => ({
    url: `${SITE_URL}/modules/${slug}`,
    lastModified: new Date(MODULE_ROUTE_LASTMOD[slug] ?? "2026-03-27T00:00:00Z"),
    changeFrequency: "weekly",
    priority: 0.7,
  }));
  const simulationEntries: MetadataRoute.Sitemap = SIMULATION_SLUGS.map((slug) => ({
    url: `${SITE_URL}/simulations/${slug}`,
    lastModified: new Date(SIMULATION_ROUTE_LASTMOD[slug] ?? "2026-03-30T00:00:00Z"),
    changeFrequency: "weekly",
    priority: 0.75,
  }));
  const academySubjectEntries: MetadataRoute.Sitemap = ACADEMY_SUBJECT_RECORDS.map((subject) => ({
    url: `${SITE_URL}${subject.href}`,
    lastModified: new Date(
      ACADEMY_SUBJECT_ROUTE_LASTMOD[subject.slug] ?? "2026-03-30T00:00:00Z",
    ),
    changeFrequency: "weekly",
    priority: 0.78,
  }));
  const academySimulationEntries: MetadataRoute.Sitemap = ACADEMY_SIMULATION_RECORDS.map(
    (simulation) => ({
      url: `${SITE_URL}${simulation.href}`,
      lastModified: new Date(
        ACADEMY_SIMULATION_ROUTE_LASTMOD[`${simulation.subjectSlug}/${simulation.slug}`] ??
          "2026-03-30T00:00:00Z",
      ),
      changeFrequency: "weekly",
      priority: 0.74,
    }),
  );
  const lessonEntries: MetadataRoute.Sitemap = LESSON_SLUGS.map((slug) => ({
    url: `${SITE_URL}/lessons/${slug}`,
    lastModified: new Date(LESSON_ROUTE_LASTMOD[slug] ?? "2026-03-27T00:00:00Z"),
    changeFrequency: "weekly",
    priority: 0.8,
  }));
  const flashcardEntries: MetadataRoute.Sitemap = LESSON_SLUGS.map((slug) => ({
    url: `${SITE_URL}/flashcards/${slug}`,
    lastModified: new Date(LESSON_ROUTE_LASTMOD[slug] ?? "2026-03-27T00:00:00Z"),
    changeFrequency: "weekly",
    priority: 0.55,
  }));
  const quizEntries: MetadataRoute.Sitemap = LESSON_SLUGS.map((slug) => ({
    url: `${SITE_URL}/quiz/${slug}`,
    lastModified: new Date(LESSON_ROUTE_LASTMOD[slug] ?? "2026-03-27T00:00:00Z"),
    changeFrequency: "weekly",
    priority: 0.55,
  }));
  return [
    ...staticEntries,
    ...moduleEntries,
    ...simulationEntries,
    ...academySubjectEntries,
    ...academySimulationEntries,
    ...lessonEntries,
    ...flashcardEntries,
    ...quizEntries,
  ];
}

import type { MetadataRoute } from "next";

import { LESSON_SLUGS, MODULE_SLUGS, SITE_URL } from "@/lib/site";

const STATIC_ROUTES: Array<{ path: string; priority: number }> = [
  { path: "/", priority: 1 },
  { path: "/syllabus", priority: 0.8 },
  { path: "/privacy", priority: 0.3 },
  { path: "/terms", priority: 0.3 },
  { path: "/attribution", priority: 0.3 },
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const staticEntries: MetadataRoute.Sitemap = STATIC_ROUTES.map((route) => ({
    url: `${SITE_URL}${route.path}`,
    lastModified: now,
    changeFrequency: "weekly",
    priority: route.priority,
  }));
  const moduleEntries: MetadataRoute.Sitemap = MODULE_SLUGS.map((slug) => ({
    url: `${SITE_URL}/modules/${slug}`,
    lastModified: now,
    changeFrequency: "weekly",
    priority: 0.7,
  }));
  const lessonEntries: MetadataRoute.Sitemap = LESSON_SLUGS.map((slug) => ({
    url: `${SITE_URL}/lessons/${slug}`,
    lastModified: now,
    changeFrequency: "weekly",
    priority: 0.8,
  }));
  const flashcardEntries: MetadataRoute.Sitemap = LESSON_SLUGS.map((slug) => ({
    url: `${SITE_URL}/flashcards/${slug}`,
    lastModified: now,
    changeFrequency: "weekly",
    priority: 0.55,
  }));
  const quizEntries: MetadataRoute.Sitemap = LESSON_SLUGS.map((slug) => ({
    url: `${SITE_URL}/quiz/${slug}`,
    lastModified: now,
    changeFrequency: "weekly",
    priority: 0.55,
  }));
  return [...staticEntries, ...moduleEntries, ...lessonEntries, ...flashcardEntries, ...quizEntries];
}

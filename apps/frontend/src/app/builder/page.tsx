import type { Metadata } from "next";

import { BuilderStudio } from "@/components/builder-studio";
import { fetchBuilderFeed, fetchBuilderProfile, fetchBuilderScenarios } from "@/lib/api";
import { buildPageMetadata } from "@/lib/metadata";
import { BuilderFeedItem, BuilderProfile, BuilderScenario } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = buildPageMetadata({
  title: "Microlearning Builder",
  description:
    "Private drag-and-drop QC+AI dependency builder for scenario sequencing, scoring, and shared learning maps.",
  path: "/builder",
  index: false,
});

export default async function BuilderPage() {
  const [scenariosResult, profileResult, feedResult] = await Promise.allSettled([
    fetchBuilderScenarios(),
    fetchBuilderProfile(),
    fetchBuilderFeed(),
  ]);
  const initialScenarios: BuilderScenario[] =
    scenariosResult.status === "fulfilled" ? scenariosResult.value : [];
  const initialProfile: BuilderProfile | null =
    profileResult.status === "fulfilled" ? profileResult.value : null;
  const initialFeed: BuilderFeedItem[] =
    feedResult.status === "fulfilled" ? feedResult.value : [];

  return (
    <BuilderStudio
      initialFeed={initialFeed}
      initialProfile={initialProfile}
      initialScenarios={initialScenarios}
    />
  );
}

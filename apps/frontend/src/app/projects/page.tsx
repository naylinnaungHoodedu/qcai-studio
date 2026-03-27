import type { Metadata } from "next";

import { PageErrorState } from "@/components/page-state";
import { ProjectsStudio } from "@/components/projects-studio";
import { fetchMyProjectSubmissions, fetchProjectCatalog, fetchProjectReviewQueue } from "@/lib/api";
import { buildPageMetadata } from "@/lib/metadata";

export const dynamic = "force-dynamic";
export const metadata: Metadata = buildPageMetadata({
  title: "Project Studio",
  description:
    "Private QC+AI project workspace for submissions, peer review, and live drafting feedback.",
  path: "/projects",
  index: false,
});

export default async function ProjectsPage() {
  const data = await Promise.all([
    fetchProjectCatalog(),
    fetchMyProjectSubmissions(),
    fetchProjectReviewQueue(),
  ]).catch(() => null);

  if (!data) {
    return (
      <PageErrorState
        title="The project studio could not be loaded"
        detail="Project catalog, submissions, or review queue data failed to load for this request."
      />
    );
  }
  const [catalog, submissions, queue] = data;

  return <ProjectsStudio initialCatalog={catalog} initialSubmissions={submissions} initialQueue={queue} />;
}

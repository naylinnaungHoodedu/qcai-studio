import type { Metadata } from "next";

import { BuilderStudio } from "@/components/builder-studio";
import { buildPageMetadata } from "@/lib/metadata";

export const metadata: Metadata = buildPageMetadata({
  title: "Microlearning Builder",
  description:
    "Private drag-and-drop QC+AI dependency builder for scenario sequencing, scoring, and shared learning maps.",
  path: "/builder",
  index: false,
});

export default function BuilderPage() {
  return <BuilderStudio />;
}

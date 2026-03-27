import type { Metadata } from "next";

import { SearchPageView } from "@/components/search-page";
import { buildPageMetadata } from "@/lib/metadata";

export const metadata: Metadata = buildPageMetadata({
  title: "Grounded Search",
  description:
    "Search the QC+AI corpus for source-grounded sections, lesson links, and curated chapter evidence.",
  path: "/search",
  index: false,
});

export default function SearchPage() {
  return <SearchPageView />;
}

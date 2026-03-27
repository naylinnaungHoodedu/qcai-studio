import type { Metadata } from "next";

import { ArenaPanel } from "@/components/arena-panel";
import { getApiBaseUrl } from "@/lib/api";
import { buildPageMetadata } from "@/lib/metadata";

export const dynamic = "force-dynamic";
export const metadata: Metadata = buildPageMetadata({
  title: "AI & Quantum Arena",
  description:
    "Private competitive practice space for real-time QC+AI challenge rounds, leaderboards, and adaptive play.",
  path: "/arena",
  index: false,
});

export default function ArenaPage() {
  const browserApiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || getApiBaseUrl();
  return <ArenaPanel apiBaseUrl={browserApiBaseUrl} />;
}

import type { Metadata } from "next";

import { ArenaPanel } from "@/components/arena-panel";
import { fetchArenaLeaderboard, fetchArenaStatus, getApiBaseUrl } from "@/lib/api";
import { buildPageMetadata } from "@/lib/metadata";
import { ArenaLeaderboardEntry, ArenaStatus } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = buildPageMetadata({
  title: "AI & Quantum Arena",
  description:
    "Private competitive practice space for real-time QC+AI challenge rounds, leaderboards, and adaptive play.",
  path: "/arena",
  index: false,
});

export default async function ArenaPage() {
  const browserApiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || getApiBaseUrl();
  const [leaderboardResult, statusResult] = await Promise.allSettled([
    fetchArenaLeaderboard(),
    fetchArenaStatus(),
  ]);
  const initialLeaderboard: ArenaLeaderboardEntry[] =
    leaderboardResult.status === "fulfilled" ? leaderboardResult.value : [];
  const initialStatus: ArenaStatus | null =
    statusResult.status === "fulfilled" ? statusResult.value : null;

  return (
    <ArenaPanel
      apiBaseUrl={browserApiBaseUrl}
      initialLeaderboard={initialLeaderboard}
      initialStatus={initialStatus}
    />
  );
}

import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { V3ReviewConsole } from "@/components/v3-review-console";
import { getApiBaseUrl } from "@/lib/api";
import { buildPageMetadata } from "@/lib/metadata";
import { reviewerUiEnabled, v3ModeFromReady } from "@/lib/v3-review";

// The V3 reviewer console (plan Phase 6 F; docs/architecture/phase6-implementation-spec.md section 11). It renders only
// where the frontend runs outside production and the API's /ready reports V3 in shadow or on; otherwise it is a 404.
// No navigation links here, and it is not indexed. Reviewers are synthetic demo identities while D-18 is open. The root
// layout's app shell already renders the page's one main landmark, so this page renders a section inside it.
export const dynamic = "force-dynamic";

export const metadata: Metadata = buildPageMetadata({
  title: "V3 review console",
  description: "Development-only adjudication of V3 queue items by synthetic reviewers.",
  path: "/review",
  index: false,
});

async function apiV3Mode(): Promise<string> {
  try {
    const response = await fetch(`${getApiBaseUrl()}/ready`, { cache: "no-store", signal: AbortSignal.timeout(2000) });
    return v3ModeFromReady(await response.json());
  } catch {
    return "off";
  }
}

export default async function ReviewPage() {
  if (!reviewerUiEnabled(process.env)) {
    notFound();
  }
  if ((await apiV3Mode()) === "off") {
    notFound();
  }
  return (
    <section aria-labelledby="v3-review-title" className="mx-auto max-w-5xl px-4 py-8">
      <h1 id="v3-review-title" className="text-2xl font-semibold">
        V3 review console
      </h1>
      <p className="mt-2 text-sm">
        Development only. Synthetic reviewers adjudicate queue items; an adjudication changes no answer and releases nothing.
      </p>
      <V3ReviewConsole />
    </section>
  );
}

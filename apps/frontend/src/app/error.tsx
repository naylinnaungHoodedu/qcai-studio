"use client";

import { useEffect } from "react";

import { PageErrorState } from "@/components/page-state";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="page-stack">
      <PageErrorState
        title="The page could not be loaded"
        detail="A rendering or data-loading error interrupted this view. Retry the page to request fresh data."
      />
      <section className="section-block">
        <button className="primary-button" onClick={reset} type="button">
          Retry
        </button>
      </section>
    </div>
  );
}

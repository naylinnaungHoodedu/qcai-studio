"use client";

import { startTransition } from "react";
import { usePathname } from "next/navigation";
import { useReportWebVitals } from "next/web-vitals";

import { postPublicWebVital } from "@/lib/api";

type BrowserNavigator = Navigator & {
  connection?: {
    effectiveType?: string;
  };
};

export function WebVitalsReporter() {
  const pathname = usePathname();

  useReportWebVitals((metric) => {
    const navigationType =
      (metric as { navigationType?: string }).navigationType ??
      (performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined)?.type ??
      "navigate";
    const connectionType =
      typeof navigator !== "undefined" ? (navigator as BrowserNavigator).connection?.effectiveType ?? null : null;
    const path =
      pathname ||
      (typeof window !== "undefined" ? window.location.pathname || "/" : "/");

    startTransition(() => {
      void postPublicWebVital({
        metric_id: metric.id,
        metric_name: metric.name,
        path,
        value: Number(metric.value.toFixed(2)),
        delta:
          typeof (metric as { delta?: number }).delta === "number"
            ? Number((metric as { delta?: number }).delta?.toFixed(2))
            : null,
        rating: (metric as { rating?: string }).rating ?? "good",
        navigation_type: navigationType,
        connection_type: connectionType,
      });
    });
  });

  return null;
}

import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { StructuredData } from "@/components/structured-data";
import { fetchPublicWebVitalsSummary, fetchServiceHealth } from "@/lib/api";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";
import {
  PERFORMANCE_THRESHOLDS,
  SECURITY_HARDENING_DECISIONS,
  STATUS_CHANNELS,
  SUPPORT_RESPONSE_TARGETS,
} from "@/lib/operations-governance";
import { FEATURE_AVAILABILITY, RECENT_UPDATES } from "@/lib/public-status";

export const metadata: Metadata = buildPageMetadata({
  title: "Public Status and Operations",
  description:
    "Review current QC+AI Studio service health, support operations, browser monitoring, and security-hardening decisions.",
  path: "/status",
});

export default async function StatusPage() {
  const structuredData = buildBreadcrumbStructuredData([
    { name: "Home", path: "/" },
    { name: "Status", path: "/status" },
  ]);

  const [healthResult, vitalsResult] = await Promise.allSettled([
    fetchServiceHealth(),
    fetchPublicWebVitalsSummary(),
  ]);

  const health = healthResult.status === "fulfilled" ? healthResult.value : null;
  const vitals = vitalsResult.status === "fulfilled" ? vitalsResult.value : null;

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id="status-breadcrumb-jsonld" />
      <section className="hero">
        <div className="hero-copy">
          <Breadcrumbs
            items={[
              { label: "Home", href: "/" },
              { label: "Status" },
            ]}
          />
          <p className="eyebrow">Operations</p>
          <h1>Public service health, support operations, and browser governance are visible.</h1>
          <p className="hero-text">
            This page is the public operational surface for QC+AI Studio. It shows live health signals, response
            targets, performance-monitoring coverage, and the remaining CSP/COEP decisions that still require
            follow-through.
          </p>
          <div className="button-row">
            <Link className="primary-button" href="/support">
              Open support
            </Link>
            <Link className="secondary-button" href="/accessibility">
              Review accessibility
            </Link>
          </div>
        </div>

        <div className="analytics-metric-grid">
          <article className="metric-card">
            <span className="eyebrow">API health</span>
            <strong className="about-metric-value">{health?.status ?? "Unavailable"}</strong>
            <p>{health ? `${health.app} responded successfully during the current status render.` : "Health check could not be confirmed during this render."}</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Vitals samples</span>
            <strong className="about-metric-value">{vitals?.total_samples ?? 0}</strong>
            <p>
              {vitals?.last_sample_at
                ? `Latest browser sample recorded at ${new Date(vitals.last_sample_at).toLocaleString()}.`
                : "Browser telemetry endpoint is live; no recent samples were available during this render."}
            </p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Support targets</span>
            <strong className="about-metric-value">2-5 days</strong>
            <p>Product/privacy requests target 2 business days; partnership and security follow-up target 5.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Hardening note</span>
            <strong className="about-metric-value">COEP deferred</strong>
            <p>The remaining browser-isolation decision is documented publicly rather than left implicit.</p>
          </article>
        </div>
      </section>

      <section className="two-column-grid">
        {STATUS_CHANNELS.map((item) => (
          <article className="panel legal-copy" key={item.title}>
            <p className="eyebrow">{item.status}</p>
            <h2>{item.title}</h2>
            <p>{item.detail}</p>
          </article>
        ))}
      </section>

      <section className="panel legal-copy">
        <h2>Support response targets</h2>
        <div className="two-column-grid">
          {SUPPORT_RESPONSE_TARGETS.map((item) => (
            <article className="metric-card" key={item.title}>
              <span className="eyebrow">{item.title}</span>
              <strong className="about-metric-value">{item.target}</strong>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="panel legal-copy">
        <h2>Browser performance governance</h2>
        <p>
          Lighthouse-based browser checks now cover the public route set named below, and browser-originated Core Web
          Vitals are posted to a first-party endpoint so the public deployment can be monitored without introducing ad
          trackers.
        </p>
        <div className="panel-table-wrap">
          <table className="governance-table">
            <thead>
              <tr>
                <th scope="col">Route</th>
                <th scope="col">Performance</th>
                <th scope="col">Accessibility</th>
                <th scope="col">Best practices</th>
                <th scope="col">SEO</th>
              </tr>
            </thead>
            <tbody>
              {PERFORMANCE_THRESHOLDS.map((item) => (
                <tr key={item.page}>
                  <th scope="row">{item.page}</th>
                  <td>{item.performance}</td>
                  <td>{item.accessibility}</td>
                  <td>{item.bestPractices}</td>
                  <td>{typeof item.seo === "number" ? item.seo : "Not enforced"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {vitals?.metrics?.length ? (
          <>
            <h2>Recent public web-vitals summary</h2>
            <div className="panel-table-wrap">
              <table className="governance-table">
                <thead>
                  <tr>
                    <th scope="col">Metric</th>
                    <th scope="col">Samples</th>
                    <th scope="col">Average</th>
                    <th scope="col">P75</th>
                    <th scope="col">Good rate</th>
                  </tr>
                </thead>
                <tbody>
                  {vitals.metrics.map((metric) => (
                    <tr key={metric.metric_name}>
                      <th scope="row">{metric.metric_name}</th>
                      <td>{metric.sample_count}</td>
                      <td>{metric.average_value}</td>
                      <td>{metric.p75_value}</td>
                      <td>{metric.good_rate_percent}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </section>

      <section className="panel legal-copy">
        <h2>Current hardening decisions</h2>
        <div className="two-column-grid">
          {SECURITY_HARDENING_DECISIONS.map((item) => (
            <article className="metric-card" key={item.title}>
              <span className="eyebrow">Security</span>
              <strong className="about-metric-value">{item.title}</strong>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="panel legal-copy">
        <h2>Current public availability</h2>
        <div className="two-column-grid">
          {FEATURE_AVAILABILITY.map((item) => (
            <article className="metric-card" key={item.title}>
              <span className="eyebrow">{item.status}</span>
              <strong className="about-metric-value">{item.title}</strong>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="panel legal-copy">
        <h2>Recent updates</h2>
        <div className="stack">
          {RECENT_UPDATES.map((item) => (
            <article className="metric-card" key={`${item.date}-${item.title}`}>
              <span className="eyebrow">{item.date}</span>
              <strong className="about-metric-value">{item.title}</strong>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

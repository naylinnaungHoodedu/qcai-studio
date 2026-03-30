import type { NextConfig } from "next";

const IS_PRODUCTION = process.env.NODE_ENV === "production";
const PUBLIC_PAGE_CACHE_CONTROL = "public, max-age=0, s-maxage=300, stale-while-revalidate=86400";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    const securityHeaders = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "X-XSS-Protection", value: "1; mode=block" },
      { key: "Referrer-Policy", value: "same-origin" },
      { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
      { key: "Cross-Origin-Resource-Policy", value: "same-site" },
      {
        key: "Permissions-Policy",
        value: "accelerometer=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()",
      },
    ];
    if (IS_PRODUCTION) {
      securityHeaders.push({
        key: "Strict-Transport-Security",
        value: "max-age=31536000; includeSubDomains; preload",
      });
    }
    const publicCacheHeaders = [{ key: "Cache-Control", value: PUBLIC_PAGE_CACHE_CONTROL }];
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
      {
        source: "/",
        headers: publicCacheHeaders,
      },
      {
        source: "/about",
        headers: publicCacheHeaders,
      },
      {
        source: "/attribution",
        headers: publicCacheHeaders,
      },
      {
        source: "/modules",
        headers: publicCacheHeaders,
      },
      {
        source: "/modules/:path*",
        headers: publicCacheHeaders,
      },
      {
        source: "/lessons/:path*",
        headers: publicCacheHeaders,
      },
      {
        source: "/simulations",
        headers: publicCacheHeaders,
      },
      {
        source: "/syllabus",
        headers: publicCacheHeaders,
      },
      {
        source: "/privacy",
        headers: publicCacheHeaders,
      },
      {
        source: "/terms",
        headers: publicCacheHeaders,
      },
      {
        source: "/support",
        headers: publicCacheHeaders,
      },
      {
        source: "/whats-new",
        headers: publicCacheHeaders,
      },
      {
        source: "/security.txt",
        headers: publicCacheHeaders,
      },
      {
        source: "/.well-known/security.txt",
        headers: publicCacheHeaders,
      },
      {
        source: "/robots.txt",
        headers: publicCacheHeaders,
      },
      {
        source: "/sitemap.xml",
        headers: publicCacheHeaders,
      },
    ];
  },
};

export default nextConfig;

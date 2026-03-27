import type { NextConfig } from "next";

const IS_PRODUCTION = process.env.NODE_ENV === "production";

function buildConnectSources(): string {
  const connectSources = new Set(["'self'"]);
  if (!IS_PRODUCTION) {
    connectSources.add("http://127.0.0.1:*");
    connectSources.add("http://localhost:*");
  }
  const apiBaseUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL;

  if (apiBaseUrl) {
    try {
      const parsed = new URL(apiBaseUrl);
      connectSources.add(parsed.origin);
      connectSources.add(`${parsed.protocol === "https:" ? "wss:" : "ws:"}//${parsed.host}`);
    } catch {
      // Ignore invalid deployment-time API URLs and keep the local defaults.
    }
  }

  return Array.from(connectSources).join(" ");
}

function buildContentSecurityPolicy(): string {
  const scriptSources = ["'self'", "'unsafe-inline'"];
  if (!IS_PRODUCTION) {
    scriptSources.push("'unsafe-eval'");
  }
  return [
    "default-src 'self'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "object-src 'none'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "style-src 'self' 'unsafe-inline'",
    `script-src ${scriptSources.join(" ")}`,
    `connect-src ${buildConnectSources()}`,
  ].join("; ");
}

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    const securityHeaders = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Referrer-Policy", value: "same-origin" },
      {
        key: "Permissions-Policy",
        value: "accelerometer=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()",
      },
      {
        key: "Content-Security-Policy",
        value: buildContentSecurityPolicy(),
      },
    ];
    if (IS_PRODUCTION) {
      securityHeaders.push({
        key: "Strict-Transport-Security",
        value: "max-age=31536000; includeSubDomains; preload",
      });
    }
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;

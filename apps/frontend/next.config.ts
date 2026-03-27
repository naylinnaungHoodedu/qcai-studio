import type { NextConfig } from "next";

function buildConnectSources(): string {
  const connectSources = new Set(["'self'", "http://127.0.0.1:*", "http://localhost:*"]);
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

const nextConfig: NextConfig = {
  async headers() {
    const connectSources = buildConnectSources();
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "same-origin" },
          {
            key: "Content-Security-Policy",
            value:
              `default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; connect-src ${connectSources};`,
          },
        ],
      },
    ];
  },
};

export default nextConfig;

import { buildSecurityDisclosureText } from "@/lib/security-disclosure";

export function GET() {
  return new Response(buildSecurityDisclosureText(), {
    status: 200,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=0, s-maxage=300, stale-while-revalidate=86400",
    },
  });
}

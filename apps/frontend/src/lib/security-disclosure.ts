import { CONTACT_EMAIL, SITE_URL } from "@/lib/site";

function getSecurityDisclosureExpiry(): string {
  const expiry = new Date("2027-03-31T00:00:00.000Z");
  return expiry.toISOString();
}

export function buildSecurityDisclosureText(): string {
  return [
    `Contact: mailto:${CONTACT_EMAIL}`,
    `Expires: ${getSecurityDisclosureExpiry()}`,
    "Preferred-Languages: en",
    `Canonical: ${SITE_URL}/.well-known/security.txt`,
    `Policy: ${SITE_URL}/support`,
  ].join("\n");
}

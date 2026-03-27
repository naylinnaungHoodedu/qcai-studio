import { ArenaPanel } from "@/components/arena-panel";
import { getApiBaseUrl } from "@/lib/api";

export const dynamic = "force-dynamic";

export default function ArenaPage() {
  const browserApiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || getApiBaseUrl();
  return <ArenaPanel apiBaseUrl={browserApiBaseUrl} />;
}

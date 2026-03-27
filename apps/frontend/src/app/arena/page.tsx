import { ArenaPanel } from "@/components/arena-panel";
import { getApiBaseUrl } from "@/lib/api";

export const dynamic = "force-dynamic";

export default function ArenaPage() {
  return <ArenaPanel apiBaseUrl={getApiBaseUrl()} />;
}

import { endpoint } from "@/lib/server/api";
import { identity } from "@/lib/server/auth";
import { hasSupabase, isDemo } from "@/lib/server/config";

export async function GET() {
  return endpoint(async () => {
    try {
      return {
        user: await identity(true),
        configured: hasSupabase,
        demo: isDemo,
      };
    } catch {
      return { user: null, configured: hasSupabase, demo: isDemo };
    }
  });
}

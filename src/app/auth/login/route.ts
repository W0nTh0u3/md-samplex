import { NextResponse } from "next/server";
import { supabaseAuth } from "@/lib/server/auth";
import { hasSupabase } from "@/lib/server/config";

export async function GET(request: Request) {
  const origin = process.env.APP_ORIGIN || new URL(request.url).origin;
  if (!hasSupabase)
    return NextResponse.redirect(new URL("/?auth=unconfigured", origin));
  const client = await supabaseAuth();
  const { data, error } = await client.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: `${origin}/auth/callback` },
  });
  if (error || !data.url)
    return NextResponse.redirect(new URL("/?auth=error", origin));
  return NextResponse.redirect(data.url);
}

import { NextResponse } from "next/server";
import { supabaseAuth } from "@/lib/server/auth";
import { hasSupabase } from "@/lib/server/config";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const origin = process.env.APP_ORIGIN || url.origin;
  const code = url.searchParams.get("code");
  if (hasSupabase && code) {
    const client = await supabaseAuth();
    const { error } = await client.auth.exchangeCodeForSession(code);
    if (!error) return NextResponse.redirect(new URL("/", origin));
  }
  return NextResponse.redirect(new URL("/?auth=error", origin));
}

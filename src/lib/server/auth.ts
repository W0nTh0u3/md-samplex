import "server-only";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { AppError } from "../engine";
import { hasSupabase, isDemo } from "./config";

export async function supabaseAuth() {
  const jar = await cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll: () => jar.getAll(),
        setAll: (values) =>
          values.forEach(({ name, value, options }) =>
            jar.set(name, value, options),
          ),
      },
    },
  );
}

export async function identity(createDemo = false) {
  if (isDemo) {
    const jar = await cookies();
    let token = jar.get("ple-preview")?.value;
    if (!token && createDemo) {
      token = crypto.randomUUID();
      jar.set("ple-preview", token, {
        httpOnly: true,
        sameSite: "strict",
        secure: process.env.APP_ORIGIN?.startsWith("https://"),
        path: "/",
        maxAge: 60 * 60 * 24 * 30,
      });
    }
    if (!token || !/^[0-9a-f-]{36}$/.test(token))
      throw new AppError("Please reopen the dashboard.", 401);
    return { id: token, name: "Future physician", demo: true };
  }
  if (!hasSupabase)
    throw new AppError(
      "Google sign-in needs a configured Supabase project.",
      503,
    );
  const client = await supabaseAuth();
  const {
    data: { user },
    error,
  } = await client.auth.getUser();
  if (error || !user)
    throw new AppError(
      "Sign in to continue. Your local draft is retained.",
      401,
    );
  if (
    user.app_metadata.provider !== "google" &&
    !user.app_metadata.providers?.includes("google")
  )
    throw new AppError("Please sign in with Google.", 403);
  return {
    id: user.id,
    name: String(user.user_metadata.full_name ?? "Future physician"),
    demo: false,
  };
}

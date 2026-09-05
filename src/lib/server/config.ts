import "server-only";

export const hasSupabase = Boolean(
  process.env.NEXT_PUBLIC_SUPABASE_URL &&
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY &&
  process.env.SUPABASE_SECRET_KEY,
);
export const isDemo =
  !hasSupabase &&
  (process.env.PLE_DEMO_MODE === "true" ||
    process.env.NODE_ENV === "development");

import { cookies } from "next/headers";
import { endpoint, readMutation } from "@/lib/server/api";
import { supabaseAuth } from "@/lib/server/auth";
import { isDemo } from "@/lib/server/config";
import { AppError } from "@/lib/engine";

export async function POST(request: Request) {
  return endpoint(async () => {
    await readMutation(request);
    if (isDemo) (await cookies()).delete("ple-preview");
    else {
      const client = await supabaseAuth();
      const { error } = await client.auth.signOut();
      if (error)
        throw new AppError("Sign-out did not complete. Please retry.", 503);
    }
    return { ok: true };
  });
}

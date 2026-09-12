import "server-only";
import { NextResponse } from "next/server";
import { z } from "zod";
import { AppError } from "../engine";
import { BANKS } from "@/data/question-bank";

export function bankFor(version: string) {
  if (!(version in BANKS))
    throw new AppError(
      "The original question-bank version is unavailable.",
      503,
    );
  return BANKS[version as keyof typeof BANKS];
}

export function response(value: unknown, status = 200) {
  return NextResponse.json(value, {
    status,
    headers: { "Cache-Control": "private, no-store" },
  });
}

export async function endpoint(work: () => Promise<unknown>) {
  try {
    return response(await work());
  } catch (error) {
    if (error instanceof AppError)
      return response({ error: error.message }, error.status);
    if (error instanceof z.ZodError || error instanceof SyntaxError)
      return response({ error: "The request is invalid." }, 400);
    console.error(
      "API failure:",
      error instanceof Error ? error.message : "Unknown error",
    );
    return response(
      {
        error:
          "Something went wrong. Your local progress is retained; please retry.",
      },
      500,
    );
  }
}

export async function readMutation(request: Request) {
  const origin = request.headers.get("origin");
  const expected = process.env.APP_ORIGIN || new URL(request.url).origin;
  if (
    !origin ||
    origin !== expected ||
    request.headers.get("sec-fetch-site") === "cross-site"
  )
    throw new AppError("Request origin is not permitted.", 403);
  if (!request.headers.get("content-type")?.includes("application/json"))
    throw new AppError("Expected JSON.", 415);
  // Bound the streamed body too; Content-Length alone is not trustworthy.
  const reader = request.body?.getReader();
  if (!reader) throw new AppError("Missing request body.");
  const chunks: Uint8Array[] = [];
  let length = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.byteLength;
    if (length > 65536) {
      await reader.cancel();
      throw new AppError("Request is too large.", 413);
    }
    chunks.push(value);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

const answerLabel = z.string().regex(/^[A-E]$/);

export const editsSchema = z
  .object({
    answers: z.record(
      z.string().max(100),
      z.union([answerLabel, z.array(answerLabel).min(1).max(5)]),
    ),
    flags: z.array(z.string().max(100)).max(100),
    position: z.number().int().min(0).max(99),
    remainingMs: z.number().finite().min(0).nullable(),
    elapsedMs: z.number().finite().min(0),
    status: z.enum(["running", "paused"]),
  })
  .strict();

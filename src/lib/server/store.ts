import "server-only";
import { createClient } from "@supabase/supabase-js";
import { mkdir, readFile, writeFile, rename } from "node:fs/promises";
import path from "node:path";
import type { Attempt } from "../types";
import { AppError } from "../engine";
import { isDemo } from "./config";

function admin() {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { auth: { persistSession: false, autoRefreshToken: false } },
  );
}

// Local preview has a single server writer; atomic rename survives interrupted writes.
// Production uses Postgres compare-and-swap. Never deploy the preview across replicas.
const previewRoot = path.join(process.cwd(), ".local", "attempts");
// Share the queue across route bundles and development module reloads.
const previewProcess = globalThis as typeof globalThis & {
  plePreviewWrites?: Promise<unknown>;
};
async function serialized<T>(operation: () => Promise<T>): Promise<T> {
  const task = (previewProcess.plePreviewWrites ?? Promise.resolve()).then(
    operation,
    operation,
  );
  previewProcess.plePreviewWrites = task.catch(() => undefined);
  return task;
}
async function previewRead(owner: string): Promise<Attempt[]> {
  try {
    return JSON.parse(
      await readFile(path.join(previewRoot, `${owner}.json`), "utf8"),
    );
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}
async function previewWrite(owner: string, values: Attempt[]) {
  await mkdir(previewRoot, { recursive: true });
  const target = path.join(previewRoot, `${owner}.json`);
  await writeFile(`${target}.tmp`, JSON.stringify(values), { mode: 0o600 });
  await rename(`${target}.tmp`, target);
}

export async function listAttempts(owner: string): Promise<Attempt[]> {
  if (isDemo)
    return (await previewRead(owner)).sort((a, b) =>
      b.updatedAt.localeCompare(a.updatedAt),
    );
  const attempts: Attempt[] = [];
  const client = admin();
  for (let offset = 0; ; offset += 1000) {
    const { data, error } = await client
      .from("attempts")
      .select("payload")
      .eq("owner_id", owner)
      .order("updated_at", { ascending: false })
      .order("id")
      .range(offset, offset + 999);
    if (error)
      throw new AppError("Could not load saved sessions. Please retry.", 503);
    attempts.push(...data.map((row) => row.payload as Attempt));
    if (data.length < 1000) return attempts;
  }
}

export async function getAttempt(owner: string, id: string): Promise<Attempt> {
  if (isDemo) {
    const attempt = (await previewRead(owner)).find((a) => a.id === id);
    if (!attempt) throw new AppError("Session not found.", 404);
    return attempt;
  }
  const { data, error } = await admin()
    .from("attempts")
    .select("payload")
    .eq("owner_id", owner)
    .eq("id", id)
    .maybeSingle();
  if (error)
    throw new AppError("Could not load this session. Please retry.", 503);
  if (!data) throw new AppError("Session not found.", 404);
  return data.payload as Attempt;
}

export async function insertAttempt(attempt: Attempt) {
  if (isDemo)
    return serialized(async () =>
      previewWrite(attempt.ownerId, [
        ...(await previewRead(attempt.ownerId)),
        attempt,
      ]),
    );
  const { error } = await admin().from("attempts").insert({
    id: attempt.id,
    owner_id: attempt.ownerId,
    bank_version: attempt.bankVersion,
    revision: attempt.revision,
    editor_id: attempt.editorId,
    payload: attempt,
    updated_at: attempt.updatedAt,
  });
  if (error)
    throw new AppError("Could not create a session. Please retry.", 503);
}

export async function replaceAttempt(
  previous: Attempt,
  next: Attempt,
): Promise<Attempt> {
  const updated = {
    ...next,
    revision: previous.revision + 1,
    updatedAt: new Date().toISOString(),
  };
  if (isDemo)
    return serialized(async () => {
      const records = await previewRead(previous.ownerId);
      const index = records.findIndex((a) => a.id === previous.id);
      if (
        index < 0 ||
        records[index].revision !== previous.revision ||
        records[index].editorId !== previous.editorId
      )
        throw new AppError(
          "Another editor saved this session. Your local draft has been kept.",
          409,
        );
      records[index] = updated;
      await previewWrite(previous.ownerId, records);
      return updated;
    });
  const { data, error } = await admin()
    .from("attempts")
    .update({
      payload: updated,
      revision: updated.revision,
      editor_id: updated.editorId,
      updated_at: updated.updatedAt,
    })
    .eq("id", previous.id)
    .eq("owner_id", previous.ownerId)
    .eq("revision", previous.revision)
    .eq("editor_id", previous.editorId)
    .select("id");
  if (error) throw new AppError("Progress is awaiting retry.", 503);
  if (!data.length)
    throw new AppError(
      "Another editor saved this session. Your local draft has been kept.",
      409,
    );
  return updated;
}

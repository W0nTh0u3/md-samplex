import { z } from "zod";
import {
  AppError,
  applyEdits,
  checkAnswer,
  publicView,
  submitAttempt,
} from "@/lib/engine";
import { bankFor, editsSchema, endpoint, readMutation } from "@/lib/server/api";
import { identity } from "@/lib/server/auth";
import { getAttempt, replaceAttempt } from "@/lib/server/store";

type Context = { params: Promise<{ id: string }> };
const schema = z
  .object({
    action: z.enum(["claim", "save", "check", "submit"]),
    editorId: z.string().uuid(),
    revision: z.number().int().min(0),
    takeover: z.boolean().optional(),
    questionId: z.string().max(100).optional(),
    edits: editsSchema.optional(),
  })
  .strict();
export async function GET(_request: Request, context: Context) {
  return endpoint(async () => {
    const user = await identity();
    const { id } = await context.params;
    const attempt = await getAttempt(user.id, z.string().uuid().parse(id));
    return publicView(attempt, bankFor(attempt.bankVersion));
  });
}
export async function POST(request: Request, context: Context) {
  return endpoint(async () => {
    const user = await identity();
    const { id } = await context.params;
    const input = schema.parse(await readMutation(request));
    const current = await getAttempt(user.id, z.string().uuid().parse(id));
    const bank = bankFor(current.bankVersion);
    // Repeating submission is harmless; never grade twice or mutate a final result.
    if (input.action === "submit" && current.status === "submitted")
      return publicView(current, bank);
    if (current.revision !== input.revision)
      throw new AppError(
        "A newer save exists. Your local draft is retained.",
        409,
      );
    let next = current;
    if (input.action === "claim") {
      if (current.status === "submitted") return publicView(current, bank);
      if (current.editorId !== input.editorId && !input.takeover)
        throw new AppError(
          "This session is open in another tab or device. Take over to continue here.",
          409,
        );
      next = { ...current, status: "paused", editorId: input.editorId };
    } else {
      if (current.editorId !== input.editorId)
        throw new AppError(
          "Another tab or device is editing this session. Your draft is retained.",
          409,
        );
      if (!input.edits) throw new AppError("Missing progress checkpoint.");
      next = applyEdits(current, input.edits, bank);
      if (input.action === "check")
        next = checkAnswer(next, input.questionId ?? "");
      if (input.action === "submit" || next.remainingMs === 0)
        next = submitAttempt(next, bank);
    }
    return publicView(await replaceAttempt(current, next), bank);
  });
}

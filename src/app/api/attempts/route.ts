import { z } from "zod";
import { BANK_VERSION, questionBank } from "@/data/question-bank";
import { createAttempt, publicView } from "@/lib/engine";
import { SUBJECTS } from "@/lib/types";
import { endpoint, readMutation } from "@/lib/server/api";
import { identity } from "@/lib/server/auth";
import { insertAttempt } from "@/lib/server/store";

const schema = z
  .object({
    subject: z.enum(SUBJECTS.map((s) => s.id)),
    mode: z.enum(["practice", "ple", "topnotch"]),
    count: z.union([z.literal(25), z.literal(50), z.literal(100)]),
    editorId: z.string().uuid(),
  })
  .strict();
export async function POST(request: Request) {
  return endpoint(async () => {
    const user = await identity();
    const input = schema.parse(await readMutation(request));
    const attempt = createAttempt(
      user.id,
      input.editorId,
      BANK_VERSION,
      questionBank,
      input.subject,
      input.mode,
      input.count,
    );
    await insertAttempt(attempt);
    return publicView(attempt, questionBank);
  });
}

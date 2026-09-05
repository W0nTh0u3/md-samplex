import { questionBank, BANK_VERSION } from "@/data/question-bank";
import { SUBJECTS } from "@/lib/types";
import { selectQuestions } from "@/lib/engine";
import { identity } from "@/lib/server/auth";
import { endpoint } from "@/lib/server/api";
import { listAttempts } from "@/lib/server/store";

export async function GET() {
  return endpoint(async () => {
    const user = await identity();
    const attempts = await listAttempts(user.id);
    const subjects = SUBJECTS.map((subject) => {
      const results = attempts.filter(
        (a) => a.subject === subject.id && a.status === "submitted",
      );
      const sizes = [25, 50, 100].filter((n) => {
        try {
          selectQuestions(questionBank, subject.id, n, () => 0.5);
          return true;
        } catch {
          return false;
        }
      });
      return {
        ...subject,
        available: questionBank.filter(
          (q) => q.subject === subject.id && q.status === "validated",
        ).length,
        sizes,
        answered: results.reduce((n, a) => n + a.questionIds.length, 0),
        correct: results.reduce((n, a) => n + (a.score ?? 0), 0),
      };
    });
    return { subjects, attempts, bankVersion: BANK_VERSION };
  });
}

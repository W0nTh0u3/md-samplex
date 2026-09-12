import type {
  Answer,
  AnswerMode,
  Feedback,
  Attempt,
  PublicQuestion,
  Question,
} from "./types";

export function answerMode(question: Pick<Question, "answerMode">): AnswerMode {
  return question.answerMode ?? "single";
}

export function answerLabels(answer: Answer | undefined): string[] {
  if (Array.isArray(answer)) return [...answer];
  return answer ? [answer] : [];
}

export function hasAnswer(answer: Answer | undefined): boolean {
  return answerLabels(answer).length > 0;
}

export function answerSetsEqual(
  left: Answer | undefined,
  right: Answer | undefined,
): boolean {
  const a = new Set(answerLabels(left));
  const b = new Set(answerLabels(right));
  return a.size === b.size && [...a].every((label) => b.has(label));
}

export function normalizeAnswer(
  question: Pick<Question, "answerMode">,
  answer: Answer | undefined,
): Answer | undefined {
  if (answer === undefined) return undefined;
  const mode = answerMode(question);
  if (mode === "single" && Array.isArray(answer) && answer.length === 1)
    return answer[0];
  if (mode === "multiple" && typeof answer === "string") return [answer];
  if (mode === "multiple" && Array.isArray(answer)) return [...answer];
  return answer;
}

export function normalizeAnswersForQuestions(
  answers: Attempt["answers"],
  questions: PublicQuestion[],
): Attempt["answers"] {
  const index = new Map(questions.map((question) => [question.id, question]));
  return Object.fromEntries(
    Object.entries(answers).map(([id, answer]) => {
      const question = index.get(id);
      return [
        id,
        question ? (normalizeAnswer(question, answer) ?? answer) : answer,
      ];
    }),
  );
}

export function correctLabels(
  question: Pick<Question, "answerMode" | "correctChoice" | "correctChoices">,
): string[] {
  return answerMode(question) === "multiple"
    ? [...(question.correctChoices ?? [])]
    : question.correctChoice
      ? [question.correctChoice]
      : [];
}

export function feedbackAnswerMode(
  feedback: Pick<Feedback, "answerMode" | "correctChoices">,
): AnswerMode {
  return (
    feedback.answerMode ??
    (feedback.correctChoices === undefined ? "single" : "multiple")
  );
}

export function feedbackCorrectLabels(feedback: Feedback): string[] {
  return feedbackAnswerMode(feedback) === "multiple"
    ? [...(feedback.correctChoices ?? [])]
    : feedback.correctChoice
      ? [feedback.correctChoice]
      : [];
}

export function answerIsCorrect(
  question: Pick<Question, "answerMode" | "correctChoice" | "correctChoices">,
  answer: Answer | undefined,
): boolean {
  const selected = answerLabels(answer);
  const keyed = correctLabels(question);
  return (
    selected.length > 0 &&
    selected.length === keyed.length &&
    new Set(selected).size === selected.length &&
    selected.every((label) => keyed.includes(label))
  );
}

export function feedbackAnswerIsCorrect(
  feedback: Feedback,
  answer: Answer | undefined,
): boolean {
  const selected = answerLabels(answer);
  const keyed = feedbackCorrectLabels(feedback);
  return (
    selected.length > 0 &&
    selected.length === keyed.length &&
    new Set(selected).size === selected.length &&
    selected.every((label) => keyed.includes(label))
  );
}

export function countAnswered(answers: Record<string, Answer>): number {
  return Object.values(answers).filter(hasAnswer).length;
}

export function formatAnswer(answer: Answer | undefined): string {
  const labels = answerLabels(answer);
  return labels.length ? labels.join(", ") : "unanswered";
}

export function isValidAnswer(
  question: Pick<Question, "answerMode" | "choices">,
  answer: Answer | undefined,
): boolean {
  if (answer === undefined) return false;
  const labels = answerLabels(answer);
  const valid = new Set(question.choices.map((choice) => choice.label));
  if (answerMode(question) === "single")
    return (
      typeof answer === "string" && labels.length === 1 && valid.has(answer)
    );
  return (
    Array.isArray(answer) &&
    labels.length > 0 &&
    new Set(labels).size === labels.length &&
    labels.every((label) => valid.has(label))
  );
}

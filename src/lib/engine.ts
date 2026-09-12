import {
  answerIsCorrect,
  answerMode,
  answerSetsEqual,
  hasAnswer,
  isValidAnswer,
  normalizeAnswer,
} from "./answers";
import {
  MODES,
  type Attempt,
  type AttemptView,
  type Edits,
  type Mode,
  type Question,
  type SubjectId,
} from "./types";

export class AppError extends Error {
  constructor(
    message: string,
    public status = 400,
  ) {
    super(message);
  }
}

export function duration(mode: Mode, count: number) {
  return mode === "practice" ? null : MODES[mode].seconds * count * 1000;
}

export function tick<T extends Edits>(state: T, deltaMs: number): T {
  if (state.status !== "running") return state;
  const delta = Math.max(0, deltaMs);
  const active =
    state.remainingMs === null ? delta : Math.min(delta, state.remainingMs);
  return {
    ...state,
    elapsedMs: state.elapsedMs + active,
    remainingMs:
      state.remainingMs === null
        ? null
        : Math.max(0, state.remainingMs - active),
  };
}

// Shuffle groups, then solve exact size without ever splitting a clinical case.
export function selectQuestions(
  bank: Question[],
  subject: SubjectId,
  count: number,
  random = Math.random,
): Question[] {
  const allGroups = new Map<string, Question[]>();
  for (const q of bank.filter((q) => q.subject === subject)) {
    const id = q.sharedCase?.id ?? q.id;
    allGroups.set(id, [...(allGroups.get(id) ?? []), q]);
  }
  const groups = [...allGroups.values()].filter((g) =>
    g.every((q) => q.status === "validated"),
  );
  for (let i = groups.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [groups[i], groups[j]] = [groups[j], groups[i]];
  }
  const reachable = new Map<number, Question[][]>([[0, []]]);
  for (const group of groups) {
    for (const [size, picked] of [...reachable.entries()].sort(
      (a, b) => b[0] - a[0],
    )) {
      const next = size + group.length;
      if (next <= count && !reachable.has(next))
        reachable.set(next, [...picked, group]);
    }
    if (reachable.has(count)) return reachable.get(count)!.flat();
  }
  throw new AppError("This subject cannot supply that session size yet.");
}

export function createAttempt(
  ownerId: string,
  editorId: string,
  bankVersion: string,
  bank: Question[],
  subject: SubjectId,
  mode: Mode,
  count: number,
): Attempt {
  if (![25, 50, 100].includes(count))
    throw new AppError("Choose 25, 50, or 100 questions.");
  const selected = selectQuestions(bank, subject, count);
  const now = new Date().toISOString();
  return {
    id: crypto.randomUUID(),
    ownerId,
    bankVersion,
    subject,
    mode,
    questionIds: selected.map((q) => q.id),
    answers: {},
    checked: [],
    flags: [],
    position: 0,
    remainingMs: duration(mode, count),
    elapsedMs: 0,
    status: "paused",
    revision: 0,
    editorId,
    createdAt: now,
    updatedAt: now,
  };
}

export function questionsFor(attempt: Attempt, bank: Question[]): Question[] {
  const index = new Map(bank.map((q) => [q.id, q]));
  return attempt.questionIds.map((id) => {
    const q = index.get(id);
    if (!q || q.status !== "validated")
      throw new AppError("The saved question bank is unavailable.", 503);
    const labels = new Set(q.choices.map((choice) => choice.label));
    const mode = answerMode(q);
    const validLabels =
      mode === "multiple"
        ? (q.correctChoices ?? [])
        : q.correctChoice
          ? [q.correctChoice]
          : [];
    if (
      (mode !== "single" && mode !== "multiple") ||
      labels.size !== q.choices.length ||
      q.choices.some((choice) => !/^[A-E]$/.test(choice.label)) ||
      validLabels.length === 0 ||
      new Set(validLabels).size !== validLabels.length ||
      validLabels.some((label) => !labels.has(label)) ||
      (mode === "single" && q.correctChoice === null) ||
      (mode === "single" && q.correctChoices !== undefined) ||
      (mode === "multiple" && q.correctChoice !== null)
    )
      throw new AppError("The saved question bank is unavailable.", 503);
    return q;
  });
}

function validateAnswerMap(answers: Attempt["answers"], questions: Question[]) {
  const questionIndex = new Map(
    questions.map((question) => [question.id, question]),
  );
  for (const [id, answer] of Object.entries(answers)) {
    const question = questionIndex.get(id);
    if (!question) throw new AppError("An answer does not match this session.");
    if (!isValidAnswer(question, answer)) {
      if (answerMode(question) === "multiple")
        throw new AppError(
          "Multiple-response answers must be a non-empty array of unique choices.",
        );
      throw new AppError(
        "Single-answer questions require exactly one valid choice.",
      );
    }
  }
}

/**
 * Saved attempts before multiple-response support contain string answers. Keep
 * those attempts readable while normalizing the representation at the engine
 * boundary. New multiple-response edits still have to use an array and are
 * validated by applyEdits.
 */
export function normalizeAttemptAnswers(
  attempt: Attempt,
  bank: Question[],
): Attempt {
  const index = new Map(bank.map((q) => [q.id, q]));
  let changed = false;
  const answers = Object.fromEntries(
    Object.entries(attempt.answers).map(([id, answer]) => {
      const question = index.get(id);
      const normalized = question
        ? (normalizeAnswer(question, answer) ?? answer)
        : answer;
      if (normalized !== answer) changed = true;
      return [id, normalized];
    }),
  );
  return changed ? { ...attempt, answers } : attempt;
}

function publicVisuals(visuals: Question["visuals"], revealFeedback: boolean) {
  const visible = visuals?.filter(
    (visual) => revealFeedback || visual.visibility === "question",
  );
  return visible?.length ? visible : undefined;
}

export function publicView(attempt: Attempt, bank: Question[]): AttemptView {
  const normalized = normalizeAttemptAnswers(attempt, bank);
  return {
    attempt: normalized,
    questions: questionsFor(normalized, bank).map((q) => ({
      id: q.id,
      stem: q.stem,
      choices: q.choices,
      originalNumber: q.originalNumber,
      answerMode: answerMode(q),
      sharedCase: q.sharedCase
        ? {
            ...q.sharedCase,
            visuals: publicVisuals(
              q.sharedCase.visuals,
              normalized.status === "submitted" ||
                normalized.checked.includes(q.id),
            ),
          }
        : undefined,
      visuals: publicVisuals(
        q.visuals,
        normalized.status === "submitted" || normalized.checked.includes(q.id),
      ),
      ...(normalized.status === "submitted" || normalized.checked.includes(q.id)
        ? {
            feedback: {
              answerMode: answerMode(q),
              correctChoice: q.correctChoice,
              ...(answerMode(q) === "multiple"
                ? { correctChoices: q.correctChoices }
                : {}),
              explanation:
                q.explanation ||
                (q.correctChoice
                  ? q.choiceRationales?.[q.correctChoice]
                  : q.correctChoices
                      ?.map((label) => q.choiceRationales?.[label])
                      .filter(Boolean)
                      .join(" ")) ||
                "",
              ...(q.choiceRationales
                ? { choiceRationales: q.choiceRationales }
                : {}),
              sources: q.sources,
            },
          }
        : {}),
    })),
  };
}

export function applyEdits(
  attempt: Attempt,
  edits: Edits,
  bank: Question[],
): Attempt {
  const normalizedAttempt = normalizeAttemptAnswers(attempt, bank);
  if (normalizedAttempt.status === "submitted")
    throw new AppError("This session has already been submitted.", 409);
  if (!["running", "paused"].includes(edits.status))
    throw new AppError("Use the submit operation to finish.");
  const qs = questionsFor(normalizedAttempt, bank);
  validateAnswerMap(edits.answers, qs);
  for (const id of normalizedAttempt.checked) {
    if (
      !(id in edits.answers) ||
      !answerSetsEqual(edits.answers[id], normalizedAttempt.answers[id])
    )
      throw new AppError("Checked practice answers are locked.");
  }
  if (edits.flags.some((id) => !normalizedAttempt.questionIds.includes(id)))
    throw new AppError("Invalid review flag.");
  if (
    !Number.isInteger(edits.position) ||
    edits.position < 0 ||
    edits.position >= qs.length
  )
    throw new AppError("Invalid question position.");
  if (
    !Number.isFinite(edits.elapsedMs) ||
    edits.elapsedMs < normalizedAttempt.elapsedMs
  )
    throw new AppError("Active time cannot move backwards.");
  if (normalizedAttempt.remainingMs === null) {
    if (edits.remainingMs !== null)
      throw new AppError("Practice sessions are untimed.");
  } else {
    if (
      edits.remainingMs === null ||
      !Number.isFinite(edits.remainingMs) ||
      edits.remainingMs < 0 ||
      edits.remainingMs > normalizedAttempt.remainingMs
    )
      throw new AppError("The timer cannot be extended.");
    if (
      Math.abs(
        edits.elapsedMs +
          edits.remainingMs -
          duration(normalizedAttempt.mode, qs.length)!,
      ) > 5
    )
      throw new AppError("Timer checkpoint is inconsistent.");
  }
  return {
    ...normalizedAttempt,
    ...edits,
    flags: [...new Set(edits.flags)],
  };
}

export function checkAnswer(attempt: Attempt, questionId: string): Attempt {
  if (attempt.status === "submitted" || attempt.mode !== "practice")
    throw new AppError("Feedback is only available during practice.");
  if (
    !attempt.questionIds.includes(questionId) ||
    !hasAnswer(attempt.answers[questionId])
  )
    throw new AppError("Choose an answer first.");
  if (attempt.checked.includes(questionId)) return attempt;
  return {
    ...attempt,
    checked: [...attempt.checked, questionId],
  };
}

export function submitAttempt(attempt: Attempt, bank: Question[]): Attempt {
  if (attempt.status === "submitted") return attempt;
  const normalized = normalizeAttemptAnswers(attempt, bank);
  const questions = questionsFor(normalized, bank);
  validateAnswerMap(normalized.answers, questions);
  const score = questions.filter((q) =>
    answerIsCorrect(q, normalized.answers[q.id]),
  ).length;
  return {
    ...normalized,
    status: "submitted",
    score,
    submittedAt: new Date().toISOString(),
  };
}

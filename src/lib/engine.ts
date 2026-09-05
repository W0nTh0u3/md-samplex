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
    if (!q || q.status !== "validated" || !q.correctChoice)
      throw new AppError("The saved question bank is unavailable.", 503);
    return q;
  });
}

export function publicView(attempt: Attempt, bank: Question[]): AttemptView {
  return {
    attempt,
    questions: questionsFor(attempt, bank).map((q) => ({
      id: q.id,
      stem: q.stem,
      choices: q.choices,
      originalNumber: q.originalNumber,
      sharedCase: q.sharedCase,
      figures: q.figures,
      ...(attempt.status === "submitted" || attempt.checked.includes(q.id)
        ? {
            feedback: {
              correctChoice: q.correctChoice!,
              explanation: q.explanation,
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
  if (attempt.status === "submitted")
    throw new AppError("This session has already been submitted.", 409);
  if (!["running", "paused"].includes(edits.status))
    throw new AppError("Use the submit operation to finish.");
  const qs = questionsFor(attempt, bank);
  if (
    Object.keys(edits.answers).some(
      (id) =>
        !qs.some(
          (q) =>
            q.id === id && q.choices.some((c) => c.label === edits.answers[id]),
        ),
    )
  )
    throw new AppError("An answer does not match this session.");
  if (attempt.checked.some((id) => edits.answers[id] !== attempt.answers[id]))
    throw new AppError("Checked practice answers are locked.");
  if (edits.flags.some((id) => !attempt.questionIds.includes(id)))
    throw new AppError("Invalid review flag.");
  if (
    !Number.isInteger(edits.position) ||
    edits.position < 0 ||
    edits.position >= qs.length
  )
    throw new AppError("Invalid question position.");
  if (!Number.isFinite(edits.elapsedMs) || edits.elapsedMs < attempt.elapsedMs)
    throw new AppError("Active time cannot move backwards.");
  if (attempt.remainingMs === null) {
    if (edits.remainingMs !== null)
      throw new AppError("Practice sessions are untimed.");
  } else {
    if (
      edits.remainingMs === null ||
      !Number.isFinite(edits.remainingMs) ||
      edits.remainingMs < 0 ||
      edits.remainingMs > attempt.remainingMs
    )
      throw new AppError("The timer cannot be extended.");
    if (
      Math.abs(
        edits.elapsedMs +
          edits.remainingMs -
          duration(attempt.mode, qs.length)!,
      ) > 5
    )
      throw new AppError("Timer checkpoint is inconsistent.");
  }
  return { ...attempt, ...edits, flags: [...new Set(edits.flags)] };
}

export function checkAnswer(attempt: Attempt, questionId: string): Attempt {
  if (attempt.status === "submitted" || attempt.mode !== "practice")
    throw new AppError("Feedback is only available during practice.");
  if (!attempt.questionIds.includes(questionId) || !attempt.answers[questionId])
    throw new AppError("Choose an answer first.");
  if (attempt.checked.includes(questionId)) return attempt;
  return {
    ...attempt,
    checked: [...attempt.checked, questionId],
  };
}

export function submitAttempt(attempt: Attempt, bank: Question[]): Attempt {
  if (attempt.status === "submitted") return attempt;
  const score = questionsFor(attempt, bank).filter(
    (q) => attempt.answers[q.id] === q.correctChoice,
  ).length;
  return {
    ...attempt,
    status: "submitted",
    score,
    submittedAt: new Date().toISOString(),
  };
}

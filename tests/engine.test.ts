import { test } from "node:test";
import assert from "node:assert/strict";
import {
  applyEdits,
  checkAnswer,
  createAttempt,
  duration,
  normalizeAttemptAnswers,
  publicView,
  selectQuestions,
  submitAttempt,
  tick,
} from "../src/lib/engine";
import type { Edits, Question } from "../src/lib/types";

const bank: Question[] = Array.from({ length: 100 }, (_, i) => ({
  id: `q${i}`,
  subject: "biochemistry",
  originalNumber: i + 1,
  stem: `Source question ${i + 1}`,
  choices: [
    { label: "A", text: "First" },
    { label: "B", text: "Second" },
    { label: "C", text: "Third" },
    { label: "D", text: "Fourth" },
  ],
  correctChoice: "B",
  explanation: "Source explanation.",
  sources: [{ filename: "fixture.pdf", pages: [1] }],
  status: "validated",
  issues: [],
}));
const create = (mode: "practice" | "ple" | "topnotch" = "practice") =>
  createAttempt("owner", "editor", "v1", bank, "biochemistry", mode, 25);
const edits = (a: ReturnType<typeof create>): Edits => ({
  answers: a.answers,
  flags: a.flags,
  position: a.position,
  elapsedMs: a.elapsedMs,
  remainingMs: a.remainingMs,
  status: a.status,
});
const multipleQuestion: Question = {
  ...bank[0],
  id: "multiple-q",
  answerMode: "multiple",
  correctChoice: null,
  correctChoices: ["A", "C"],
};
const multipleBank: Question[] = [multipleQuestion, ...bank.slice(1)];
const createMultiple = (mode: "practice" | "ple" | "topnotch" = "practice") => {
  const attempt = createAttempt(
    "owner",
    "editor",
    "v1",
    multipleBank,
    "biochemistry",
    mode,
    25,
  );
  return {
    ...attempt,
    questionIds: [multipleQuestion.id, ...bank.slice(1, 25).map((q) => q.id)],
    answers: {},
  };
};
const editsWithAnswers = (
  a: ReturnType<typeof create>,
  answers: Edits["answers"],
): Edits => ({ ...edits(a), answers });

test("pacing is proportional and elapsed-time checkpoints clamp at zero", () => {
  assert.equal(duration("ple", 25), 30 * 60 * 1000);
  assert.equal(duration("topnotch", 50), 45 * 60 * 1000);
  assert.equal(duration("practice", 100), null);
  const start = { ...create("ple"), status: "running" as const };
  const stepped = tick(start, 3478);
  assert.equal(stepped.remainingMs, start.remainingMs! - 3478);
  assert.equal(
    tick({ ...stepped, status: "paused" }, 9999).remainingMs,
    stepped.remainingMs,
  );
  const expired = tick(start, 99999999);
  assert.equal(expired.remainingMs, 0);
  assert.equal(expired.elapsedMs, duration("ple", 25));
  assert.equal(tick(start, -100).elapsedMs, 0);
});

test("practice check reveals only the checked answer and locks it", () => {
  let a = create();
  const id = a.questionIds[0];
  assert.ok(publicView(a, bank).questions.every((q) => !("feedback" in q)));
  assert.throws(() => checkAnswer(a, id), /Choose an answer/);
  a = applyEdits(a, { ...edits(a), answers: { [id]: "B" } }, bank);
  a = checkAnswer(a, id);
  assert.equal(a.position, 0);
  assert.equal(publicView(a, bank).questions[0].feedback?.correctChoice, "B");
  assert.equal(publicView(a, bank).questions[1].feedback, undefined);
  assert.throws(
    () => applyEdits(a, { ...edits(a), answers: { [id]: "A" } }, bank),
    /locked/,
  );
  assert.throws(
    () => applyEdits(a, { ...edits(a), answers: {} }, bank),
    /locked/,
  );
  assert.equal(checkAnswer(a, id).checked.length, 1);
});

test("choice rationales stay secret until feedback and fall back to the keyed rationale", () => {
  const rationaleBank = bank.map((question, index) =>
    index === 0
      ? {
          ...question,
          explanation: "",
          choiceRationales: {
            A: "A is not the source answer.",
            B: "B is the source answer.",
            C: "C is not the source answer.",
            D: "D is not the source answer.",
          },
        }
      : question,
  );
  let a = createAttempt(
    "owner",
    "editor",
    "v1",
    rationaleBank,
    "biochemistry",
    "practice",
    100,
  );
  const id = "q0";
  assert.equal(
    JSON.stringify(publicView(a, rationaleBank)).includes("rationale"),
    false,
  );
  a = applyEdits(a, { ...edits(a), answers: { [id]: "A" } }, rationaleBank);
  a = checkAnswer(a, id);
  const feedback = publicView(a, rationaleBank).questions.find(
    (q) => q.id === id,
  )!.feedback!;
  assert.equal(feedback.explanation, "B is the source answer.");
  assert.deepEqual(feedback.choiceRationales?.B, "B is the source answer.");
  assert.deepEqual(feedback.sources, [{ filename: "fixture.pdf", pages: [1] }]);
});

test("timed answers remain editable and reveal nothing until server submission", () => {
  let a = create("ple");
  const id = a.questionIds[0];
  a = applyEdits(a, { ...edits(a), answers: { [id]: "A" } }, bank);
  a = applyEdits(a, { ...edits(a), answers: { [id]: "B" } }, bank);
  assert.throws(() => checkAnswer(a, id), /practice/);
  assert.equal(
    JSON.stringify(publicView(a, bank)).includes("correctChoice"),
    false,
  );
  const final = submitAttempt(a, bank);
  assert.equal(final.score, 1);
  assert.ok(publicView(final, bank).questions.every((q) => q.feedback));
  assert.strictEqual(submitAttempt(final, bank), final);
  assert.throws(() => applyEdits(final, edits(a), bank), /submitted/);
});

test("multiple-response answers use exact sets and preserve legacy strings", () => {
  const id = multipleQuestion.id;
  const answer = (value: string | string[]) => {
    const attempt = createMultiple();
    return applyEdits(
      attempt,
      editsWithAnswers(attempt, { [id]: value }),
      multipleBank,
    );
  };

  const partial = answer(["A"]);
  assert.equal(submitAttempt(partial, multipleBank).score, 0);
  const extra = answer(["A", "B", "C"]);
  assert.equal(submitAttempt(extra, multipleBank).score, 0);

  const exact = answer(["C", "A"]);
  assert.equal(submitAttempt(exact, multipleBank).score, 1);
  const feedback = publicView(submitAttempt(exact, multipleBank), multipleBank)
    .questions[0].feedback!;
  assert.equal(feedback.answerMode, "multiple");
  assert.equal(feedback.correctChoice, null);
  assert.deepEqual(feedback.correctChoices, ["A", "C"]);

  for (const invalid of [["A", "A"], [], ["A", "E"]]) {
    assert.throws(
      () => answer(invalid),
      /Multiple-response answers must be a non-empty array of unique choices/,
    );
  }
  assert.throws(
    () => answer("A"),
    /Multiple-response answers must be a non-empty array of unique choices/,
  );

  const legacy = {
    ...createMultiple(),
    answers: { [id]: "A" },
  };
  assert.deepEqual(normalizeAttemptAnswers(legacy, multipleBank).answers[id], [
    "A",
  ]);
  assert.deepEqual(publicView(legacy, multipleBank).attempt.answers[id], ["A"]);
  assert.equal(submitAttempt(legacy, multipleBank).score, 0);

  const single = createMultiple();
  const singleId = single.questionIds[1];
  assert.throws(
    () =>
      applyEdits(
        single,
        editsWithAnswers(single, { [singleId]: ["B"] }),
        multipleBank,
      ),
    /Single-answer questions require exactly one valid choice/,
  );
});

test("multiple-response practice feedback locks the selected set and keeps rationales secret", () => {
  const id = multipleQuestion.id;
  const rationaleBank = multipleBank.map((question) =>
    question.id === id
      ? {
          ...question,
          explanation: "",
          choiceRationales: {
            A: "A is supported.",
            B: "B is not supported.",
            C: "C is supported.",
            D: "D is not supported.",
          },
        }
      : question,
  );
  let a = createAttempt(
    "owner",
    "editor",
    "v1",
    rationaleBank,
    "biochemistry",
    "practice",
    25,
  );
  a = { ...a, questionIds: [id, ...bank.slice(1, 25).map((q) => q.id)] };
  assert.equal(publicView(a, rationaleBank).questions[0].feedback, undefined);
  a = applyEdits(a, editsWithAnswers(a, { [id]: ["A", "C"] }), rationaleBank);
  a = checkAnswer(a, id);
  const checked = publicView(a, rationaleBank).questions[0];
  assert.deepEqual(checked.feedback?.correctChoices, ["A", "C"]);
  assert.equal(
    checked.feedback?.explanation,
    "A is supported. C is supported.",
  );
  assert.equal(checked.feedback?.choiceRationales?.B, "B is not supported.");
  assert.deepEqual(
    applyEdits(a, editsWithAnswers(a, { [id]: ["C", "A"] }), rationaleBank)
      .answers[id],
    ["C", "A"],
  );
  assert.throws(
    () => applyEdits(a, editsWithAnswers(a, { [id]: ["A"] }), rationaleBank),
    /locked/,
  );
});

test("question and shared-case visuals stay answer-neutral until feedback", () => {
  const visual = (id: string, visibility: "question" | "feedback") => ({
    id,
    path: `/assets/${id}.png`,
    sha256: "a".repeat(64),
    kind: "diagram" as const,
    alt: `Verified ${id} diagram`,
    visibility,
  });
  const visualBank = bank.map((question, index) =>
    index === 0
      ? {
          ...question,
          visuals: [
            visual("question-context", "question"),
            visual("marked-answer", "feedback"),
          ],
          sharedCase: {
            id: "visual-case",
            text: "A verified shared case.",
            visuals: [visual("case-answer", "feedback")],
          },
        }
      : question,
  );
  let attempt = createAttempt(
    "owner",
    "editor",
    "v1",
    visualBank,
    "biochemistry",
    "practice",
    25,
  );
  attempt = {
    ...attempt,
    questionIds: ["q0", ...bank.slice(1, 25).map((q) => q.id)],
  };

  const before = publicView(attempt, visualBank).questions[0];
  assert.deepEqual(
    before.visuals?.map((item) => item.id),
    ["question-context"],
  );
  assert.deepEqual(before.sharedCase?.visuals, undefined);

  attempt = applyEdits(
    attempt,
    editsWithAnswers(attempt, { q0: "B" }),
    visualBank,
  );
  attempt = checkAnswer(attempt, "q0");
  const after = publicView(attempt, visualBank).questions[0];
  assert.deepEqual(
    after.visuals?.map((item) => item.id),
    ["question-context", "marked-answer"],
  );
  assert.deepEqual(
    after.sharedCase?.visuals?.map((item) => item.id),
    ["case-answer"],
  );
});

test("invalid answers, navigation, flags and extended clocks are rejected", () => {
  const a = create("ple");
  assert.throws(() =>
    applyEdits(a, { ...edits(a), answers: { unrelated: "B" } }, bank),
  );
  assert.throws(() =>
    applyEdits(a, { ...edits(a), answers: { [a.questionIds[0]]: "E" } }, bank),
  );
  assert.throws(() => applyEdits(a, { ...edits(a), position: 25 }, bank));
  assert.throws(() =>
    applyEdits(a, { ...edits(a), flags: ["unrelated"] }, bank),
  );
  assert.throws(() =>
    applyEdits(a, { ...edits(a), remainingMs: a.remainingMs! + 100 }, bank),
  );
  assert.throws(
    () => applyEdits(a, { ...edits(a), remainingMs: 1 }, bank),
    /inconsistent/,
  );
  assert.throws(() => applyEdits(a, { ...edits(a), elapsedMs: NaN }, bank));
});

test("selection preserves option order and whole cases, including ineligible siblings", () => {
  const grouped = bank.slice(0, 30).map((q) => structuredClone(q));
  for (let i = 0; i < 6; i++)
    grouped[i].sharedCase = {
      id: `case-${Math.floor(i / 3)}`,
      text: "A linked clinical case",
    };
  const selected = selectQuestions(grouped, "biochemistry", 25, () => 0.42);
  assert.equal(selected.length, 25);
  assert.equal(new Set(selected.map((q) => q.id)).size, 25);
  for (const group of ["case-0", "case-1"])
    assert.ok(
      [0, 3].includes(
        selected.filter((q) => q.sharedCase?.id === group).length,
      ),
    );
  assert.deepEqual(
    selected[0].choices.map((c) => c.label),
    ["A", "B", "C", "D"],
  );
  grouped[0].status = "needs_review";
  const next = selectQuestions(grouped, "biochemistry", 25, () => 0.42);
  assert.equal(
    next.some((q) => q.sharedCase?.id === "case-0"),
    false,
  );
  assert.throws(() => selectQuestions(grouped.slice(0, 6), "biochemistry", 2));
});

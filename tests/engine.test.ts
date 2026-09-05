import { test } from "node:test";
import assert from "node:assert/strict";
import {
  applyEdits,
  checkAnswer,
  createAttempt,
  duration,
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

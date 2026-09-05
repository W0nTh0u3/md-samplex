import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import type { Question } from "../src/lib/types";

test("complete bank has unique IDs, valid source keys, original options and explicit exclusions", async () => {
  const registry = await readFile("src/data/question-bank.ts", "utf8");
  const version = registry.match(/BANK_VERSION\s*=\s*["']([^"']+)/)![1];
  const { questions }: { questions: Question[] } = await import(
    `../src/data/versions/${version}/index.ts`
  );
  const report = JSON.parse(
    await readFile(`src/data/versions/${version}/report.json`, "utf8"),
  );
  assert.equal(new Set(questions.map((q) => q.id)).size, questions.length);
  assert.equal(report.total, questions.length);
  assert.equal(report.validated + report.needsReview, questions.length);
  assert.equal(report.files.length, 9);
  assert.deepEqual(report.unparsedPages, []);
  assert.deepEqual(report.unparsedRows, []);
  // All 8,400 Superexam and 150 Avillo source numbers are accounted for,
  // including records consolidated at different original numbers.
  assert.equal(
    questions.length +
      report.duplicates.filter(
        (d: { method: string }) => d.method === "identical_content",
      ).length,
    8550,
  );
  const reviews = new Set(report.review.map((q: Question) => q.id));
  for (const q of questions) {
    assert.ok(q.sources.length > 0, q.id);
    assert.ok(
      q.sources.every(
        (s) =>
          s.pages.length > 0 &&
          s.pages.every((p) => Number.isInteger(p) && p > 0),
      ),
      q.id,
    );
    if (q.status === "validated") {
      assert.equal(q.issues.length, 0, q.id);
      assert.ok(q.explanation.length > 0 && q.stem.length >= 15, q.id);
      assert.ok(
        q.choices.some((c) => c.label === q.correctChoice),
        q.id,
      );
      assert.ok(
        ["ABCD", "ABCDE"].includes(q.choices.map((c) => c.label).join("")),
        q.id,
      );
      assert.ok(
        q.sources.some((s) => s.answerPages?.length),
        q.id,
      );
      assert.equal(reviews.has(q.id), false, q.id);
    } else {
      assert.ok(q.issues.length > 0 && reviews.has(q.id), q.id);
    }
  }
  const first = questions.find((q) => q.id === "superexam-biochemistry-0001")!;
  assert.equal(first.correctChoice, "D");
  assert.equal(first.status, "needs_review"); // The original has a merged D/E marker.
  const continuation = questions.find(
    (q) => q.id === "superexam-biochemistry-0006",
  )!;
  assert.deepEqual(continuation.sources[0].pages, [1, 2]);
  assert.ok(continuation.explanation.includes("Her’s disease"));
});

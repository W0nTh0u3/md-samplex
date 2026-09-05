import { test, expect, type Page } from "@playwright/test";
import type { AttemptView } from "../../src/lib/types";

const origin = `http://localhost:${process.env.PLE_TEST_PORT ?? 3100}`;
const headers = { Origin: origin };
async function create(page: Page, mode = "practice") {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your next step, doctor." }),
  ).toBeVisible();
  const editorId = await page.evaluate(() => {
    const id = crypto.randomUUID();
    sessionStorage.setItem("ple-editor", id);
    return id;
  });
  const response = await page.request.post("/api/attempts", {
    headers,
    data: { subject: "biochemistry", mode, count: 25, editorId },
  });
  expect(response.ok()).toBeTruthy();
  const view: AttemptView = await response.json();
  await page.goto(`/?attempt=${view.attempt.id}`);
  await expect(
    page.getByRole("button", { name: "Resume session", exact: true }),
  ).toBeVisible();
  return view;
}

test("dashboard setup, keyboard answers, practice locking, refresh and results", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Explore your subjects" }),
  ).toBeVisible();
  await page.screenshot({
    path: ".local/dashboard-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Start a session" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Let’s begin" }).click();
  await page
    .getByRole("button", { name: "Resume session", exact: true })
    .click();
  const first = page.locator(".choices input").first();
  await first.focus();
  await page.keyboard.press("Space");
  await expect(first).toBeChecked();
  await page.route("**/api/attempts/*", async (route) => {
    if (
      route.request().method() === "POST" &&
      route.request().postDataJSON()?.action === "check"
    ) {
      await new Promise((resolve) => setTimeout(resolve, 1400));
    }
    await route.continue();
  });
  await page.getByRole("button", { name: "Check answer", exact: true }).click();
  await expect(page.locator(".question-toolbar").first()).toContainText(
    "Question 1",
  );
  await expect(page.locator(".question-grid button").first()).toHaveClass(
    /checked-(correct|incorrect)/,
  );
  await expect(page.locator(".feedback")).toBeVisible();
  await expect(page.locator(".feedback-verdict h2")).toBeFocused();
  await expect(page.getByTestId("feedback-explanation")).toHaveCSS(
    "white-space",
    "normal",
  );
  const sourcePages = page.locator("details").filter({
    hasText: "View source pages",
  });
  const sourceFiles = page.locator("details").filter({
    hasText: "Show source files",
  });
  await expect(sourcePages).toBeVisible();
  await expect(sourceFiles).toBeVisible();
  await expect(sourceFiles.locator("strong").first()).toBeHidden();
  await sourcePages.locator("summary").click();
  await expect(
    sourcePages.getByText(/Question \/ explanation: pages/).first(),
  ).toBeVisible();
  await sourceFiles.locator("summary").click();
  await expect(sourceFiles.locator("strong").first()).toBeVisible();
  await expect(first).toBeDisabled();
  await page.getByRole("button", { name: "Flag for review" }).click();
  await page
    .getByRole("button", { name: "Next question", exact: true })
    .click();
  await expect(page.locator(".question-toolbar").first()).toContainText(
    "Question 2",
  );
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Resume session", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Resume session", exact: true })
    .click();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.locator(".feedback")).toBeVisible();
  await expect(page.locator(".choices input").first()).toBeChecked();
  await page
    .getByRole("button", { name: "Submit session", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("24 unanswered");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Submit session", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Progress starts with practice." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Flagged", exact: true }).click();
  await expect(page.locator(".result-question")).toHaveCount(1);
});

test("server rejects stale saves, answer leakage, cross-account access and CSRF", async ({
  page,
  browser,
}) => {
  const initial = await create(page, "ple");
  const id = initial.attempt.id;
  let view: AttemptView = await (
    await page.request.get(`/api/attempts/${id}`)
  ).json();
  expect(view.questions.every((q) => q.feedback === undefined)).toBeTruthy();
  const a = view.attempt;
  const edits = {
    answers: { [a.questionIds[0]]: "A" },
    flags: [],
    position: 0,
    remainingMs: a.remainingMs,
    elapsedMs: 0,
    status: "paused",
  };
  const body = {
    action: "save",
    editorId: a.editorId,
    revision: a.revision,
    edits,
  };
  const saves = await Promise.all([
    page.request.post(`/api/attempts/${id}`, { headers, data: body }),
    page.request.post(`/api/attempts/${id}`, { headers, data: body }),
  ]);
  expect(saves.map((r) => r.status()).sort()).toEqual([200, 409]);
  expect(
    (
      await page.request.post(`/api/attempts/${id}`, {
        headers: { Origin: "https://foreign.example" },
        data: body,
      })
    ).status(),
  ).toBe(403);
  const other = await browser.newContext();
  await other.request.get(`${origin}/api/session`);
  expect(
    (await other.request.get(`${origin}/api/attempts/${id}`)).status(),
  ).toBe(404);
  expect(
    (
      await other.request.post(`${origin}/api/attempts/${id}`, {
        headers,
        data: body,
      })
    ).status(),
  ).toBe(404);
  await other.close();
  view = await (await page.request.get(`/api/attempts/${id}`)).json();
  const submit = { ...body, action: "submit", revision: view.attempt.revision };
  const first: AttemptView = await (
    await page.request.post(`/api/attempts/${id}`, { headers, data: submit })
  ).json();
  const repeated: AttemptView = await (
    await page.request.post(`/api/attempts/${id}`, { headers, data: submit })
  ).json();
  expect(repeated.attempt).toEqual(first.attempt);
  expect(first.questions.every((q) => q.feedback)).toBeTruthy();
  const created = await Promise.all(
    Array.from({ length: 3 }, () =>
      page.request.post("/api/attempts", {
        headers,
        data: {
          subject: "biochemistry",
          mode: "practice",
          count: 25,
          editorId: a.editorId,
        },
      }),
    ),
  );
  expect(created.every((r) => r.status() === 200)).toBeTruthy();
  const dashboard = await (await page.request.get("/api/dashboard")).json();
  expect(dashboard.attempts).toHaveLength(4);
});

test("offline edits survive refresh and competing tabs require explicit takeover", async ({
  page,
  context,
}) => {
  const initial = await create(page);
  await page
    .getByRole("button", { name: "Resume session", exact: true })
    .click();
  await context.setOffline(true);
  await page.locator(".choices input").first().check();
  await expect(page.getByRole("status")).toContainText("Awaiting retry");
  await context.setOffline(false);
  await page.reload();
  await page
    .getByRole("button", { name: "Resume session", exact: true })
    .click();
  await expect(page.locator(".choices input").first()).toBeChecked();
  const second = await context.newPage();
  await second.goto(`/?attempt=${initial.attempt.id}`);
  await expect(
    second.getByRole("button", { name: "Take over session" }),
  ).toBeVisible();
  await second.getByRole("button", { name: "Take over session" }).click();
  await second
    .getByRole("button", { name: "Resume session", exact: true })
    .click();
  // The old editor receives a conflict even if it was already paused on visibility loss.
  const stale = initial.attempt;
  const response = await page.request.post(`/api/attempts/${stale.id}`, {
    headers,
    data: {
      action: "save",
      editorId: stale.editorId,
      revision: stale.revision,
      edits: {
        answers: {},
        flags: [],
        position: 0,
        remainingMs: null,
        elapsedMs: 0,
        status: "paused",
      },
    },
  });
  expect(response.status()).toBe(409);
  await second.close();
});

test("timer pauses when hidden, restores paused, and submits at zero", async ({
  page,
}) => {
  await create(page, "ple");
  await page.clock.install();
  await page
    .getByRole("button", { name: "Resume session", exact: true })
    .click();
  await page.clock.fastForward(5000);
  await expect(page.getByRole("status")).toContainText("Saved to preview");
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(
    page.getByRole("heading", { name: "Take a breath. You’re in control." }),
  ).toBeVisible();
  const paused = await page.locator(".timer span").innerText();
  await expect(page.getByRole("status")).toContainText("Saved to preview");
  await page.clock.fastForward(60000);
  await expect(page.locator(".timer span")).toHaveText(paused);
  await page.evaluate(() =>
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    }),
  );
  await page
    .getByRole("button", { name: "Resume session", exact: true })
    .click();
  await page.clock.runFor(600);
  await expect(page.getByRole("status")).toContainText("Saved to preview");
  await page.clock.fastForward(1800001);
  await expect(
    page.getByRole("heading", { name: "Progress starts with practice." }),
  ).toBeVisible();
});

test("mobile layout, question navigator, focus and reduced motion", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Explore your subjects" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open navigation menu" }).click();
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Question bank", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Build your knowledge." }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: ".local/dashboard-mobile.png",
    fullPage: true,
  });
  await page
    .getByRole("textbox", { name: "Find a subject" })
    .fill("physiology");
  await expect(page.locator(".subject-card")).toHaveCount(1);
  await page.locator(".subject-card").click();
  await page.getByRole("radio", { name: /PLE pace/ }).check();
  await expect(page.getByRole("dialog")).toContainText("30 minutes");
  await page.getByRole("button", { name: "Let’s begin" }).click();
  await page
    .getByRole("button", { name: "Resume session", exact: true })
    .click();
  await page.keyboard.press("Tab");
  await page.locator(".choices input").first().focus();
  expect(
    await page
      .locator(".choice")
      .first()
      .evaluate((el) => getComputedStyle(el).outlineStyle),
  ).toBe("solid");
  await page.keyboard.press("Space");
  await page.getByRole("button", { name: "Show question navigator" }).click();
  await page
    .getByRole("button", { name: "Question 2, unanswered", exact: true })
    .click();
  await expect(page.locator(".question-toolbar").first()).toContainText(
    "Question 2",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({ path: ".local/exam-mobile.png", fullPage: true });
});

test("closure retains a disconnected draft and offers explicit recovery", async ({
  page,
  context,
}) => {
  const initial = await create(page);
  await page
    .getByRole("button", { name: "Resume session", exact: true })
    .click();
  await context.setOffline(true);
  await page.locator(".choices input").nth(1).check();
  await expect(page.getByRole("status")).toContainText("Awaiting retry");
  await page.close();
  await context.setOffline(false);
  const restored = await context.newPage();
  await restored.goto(`/?attempt=${initial.attempt.id}`);
  await restored.getByRole("button", { name: "Take over session" }).click();
  await restored.getByRole("button", { name: "Review draft" }).click();
  await expect(restored.getByRole("dialog")).toContainText("draft B");
  await restored
    .getByRole("button", { name: "Restore draft", exact: true })
    .click();
  await restored
    .getByRole("button", { name: "Resume session", exact: true })
    .click();
  await expect(restored.locator(".choices input").nth(1)).toBeChecked();
  await restored.close();
});

test("expired identity hides the attempt and an account switch cannot expose drafts", async ({
  page,
  context,
}) => {
  const initial = await create(page);
  await page
    .getByRole("button", { name: "Resume session", exact: true })
    .click();
  await context.clearCookies();
  await page.locator(".choices input").first().check();
  await expect(
    page.getByRole("heading", { name: "Sign in to continue" }),
  ).toBeVisible();
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your next step, doctor." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Continue session" }),
  ).toHaveCount(0);
  await page.goto(`/?attempt=${initial.attempt.id}`);
  await expect(
    page.getByRole("heading", { name: "Sign in to continue" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Review draft" })).toHaveCount(
    0,
  );
});

test("offline submission stays locked locally and retries to one final result", async ({
  page,
  context,
}) => {
  await create(page, "topnotch");
  await page
    .getByRole("button", { name: "Resume session", exact: true })
    .click();
  await page.locator(".choices input").first().check();
  await context.setOffline(true);
  await page
    .getByRole("button", { name: "Submit session", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Submit session", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Your submission is queued." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Resume", exact: true }),
  ).toBeDisabled();
  await context.setOffline(false);
  await expect(
    page.getByRole("heading", { name: "Progress starts with practice." }),
  ).toBeVisible();
});

test("a committed save with a lost response preserves a usable takeover and recovery path", async ({
  page,
}) => {
  await create(page, "ple");
  let dropNextSave = true;
  await page.route("**/api/attempts/*", async (route) => {
    if (
      dropNextSave &&
      route.request().method() === "POST" &&
      route.request().postDataJSON()?.action === "save"
    ) {
      dropNextSave = false;
      await route.fetch();
      await route.abort("connectionreset");
    } else await route.continue();
  });
  await page
    .getByRole("button", { name: "Resume session", exact: true })
    .click();
  await page.locator(".choices input").first().check();
  await expect(page.getByRole("status")).toContainText("Awaiting retry");
  await page
    .getByRole("button", { name: "Submit session", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Submit session", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Take over session" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Retry submission" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Take over session" }).click();
  await page.getByRole("button", { name: "Review draft" }).click();
  await page
    .getByRole("button", { name: "Restore draft", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Submit session", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Submit session", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Progress starts with practice." }),
  ).toBeVisible();
});

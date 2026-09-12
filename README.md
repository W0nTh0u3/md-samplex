# PLE Practice

A responsive Philippine Physicians Licensure Examination study app built with Next.js App Router, TypeScript, Tailwind CSS, and Supabase Auth/Postgres.

The original implementation proposal is saved in [`docs/MVP_PLAN.md`](docs/MVP_PLAN.md). See [`docs/VERIFICATION.md`](docs/VERIFICATION.md) for verified behavior and remaining acceptance checks, and [`docs/EXTRACTION_REPORT.md`](docs/EXTRACTION_REPORT.md) for current bank counts.

The interface follows the visual system in [`DESIGN.md`](DESIGN.md): a warm paper canvas, white hairline cards, Notion blue actions, a single indigo study hero, and restrained CSS sticker accents. The dashboard uses a responsive top navigation; exam and results screens keep a focused task layout.

## Run locally

Requires Node.js 22+ and npm. The generated question bank is included; Python is only needed to regenerate it.

```bash
npm ci
npm run dev
```

Open http://localhost:3000. With no Supabase credentials, development opens a **local preview** automatically. Preview accounts use an opaque browser cookie, server-side JSON files in `.local/attempts/`, and IndexedDB recovery. They are for local evaluation; they do not provide Google sign-in or cross-device identity. Clearing the preview cookie creates a new preview account. Do not deploy the file store across multiple processes or replicas.

Run the local binary through npm (`npm run dev`), rather than calling `next` directly. If you switch between WSL and a normal Windows terminal, install dependencies once for the environment you are using; WSL and Windows create different `node_modules/.bin` launchers. From Windows, run `npm ci` in the project directory, then `npm run dev`. Do not share one `node_modules` directory between the two runtimes.

Production disables preview unless `PLE_DEMO_MODE=true` is explicitly set. Missing production credentials show the setup screen instead of silently using a demo account.

## Connect Google and persistent accounts

1. Create a Supabase project. Copy `.env.example` to `.env.local` and set `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, and `APP_ORIGIN`. The secret key must remain server-only. Use the exact browser origin, with no trailing slash, for `APP_ORIGIN`.
2. Run [`supabase/migrations/202609050001_attempts.sql`](supabase/migrations/202609050001_attempts.sql) in the project's SQL editor, or apply it using your normal Supabase migration workflow.
3. In Google Cloud, create an OAuth web client. Set its authorized redirect URI to `https://YOUR_PROJECT_REF.supabase.co/auth/v1/callback`.
4. Enable **Google** in Supabase Authentication → Providers and supply the Google client ID/secret. Disable other sign-in providers for this app.
5. In Supabase Authentication → URL Configuration, set your Site URL and allow `http://localhost:3000/auth/callback` for local development plus your deployed `https://YOUR_DOMAIN/auth/callback` URL.
6. Set `PLE_DEMO_MODE=false`, restart Next.js, and use **Continue with Google**. Set production environment variables on the server hosting the app and use HTTPS.

Auth uses cookie-based PKCE through `@supabase/ssr`. The proxy refreshes sessions; each endpoint verifies the user independently. The callback always returns to the configured origin. No arbitrary return URL is accepted.

Implementation references: [Supabase SSR](https://supabase.com/docs/guides/auth/server-side/creating-a-client), [Google provider setup](https://supabase.com/docs/guides/auth/social-login/auth-google), [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [Next.js route handlers](https://nextjs.org/docs/app/getting-started/route-handlers).

## Study behavior

Choose one subject and 25, 50, or 100 questions. Only sizes the eligible bank can supply are offered. Questions are shuffled as groups; original choice order stays fixed.

| Mode          | Active time for 25 / 50 / 100 questions | Feedback                                                                   |
| ------------- | --------------------------------------- | -------------------------------------------------------------------------- |
| Practice      | Untimed                                 | Check locks the response and shows the explanation on the current question |
| PLE pace      | 30 / 60 / 120 minutes                   | After submission                                                           |
| Topnotch pace | 22.5 / 45 / 90 minutes                  | After submission                                                           |

In practice mode, checked correct answers are green in the navigator, incorrect answers are red, and merely selected answers are neutral. The last question stays in place after checking. Nothing auto-submits in untimed practice. Sources that provide a rationale below every option show a choice-by-choice review after checking or submission; older overall explanations keep the existing feedback layout.

Multiple-response questions show accessible checkboxes and use exact-set scoring: every keyed choice must be selected and no extra choice may be selected. Legacy saved string answers are normalized when a session is opened; malformed or mode-mismatched answers are rejected by the server.

PLE pace follows the two-hour subject allocation in the [October 2026 PRC program](https://www.prc.gov.ph/sites/default/files/October%202026%20PLE%20Program%20of%20Exam.pdf). Topnotch pace follows the supplied Superexam instructions. These app modes measure **active study time**: hiding the tab, leaving the exam, or explicitly pausing stops the clock. Opening an interrupted session restores it paused.

Timed sessions submit at zero; early submission confirms the unanswered count. Results include score, correct/incorrect/unanswered counts, source explanations and mistake/flag filters. Accuracy includes unanswered questions in the denominator.

## Persistence and conflicts

- Answers, flags and navigation go immediately to account-scoped IndexedDB. The running timer checkpoints locally each second using elapsed time, and remotely every five seconds. Edits also trigger a debounced save; pausing adds a checkpoint.
- Save status distinguishes local storage, syncing, synced, and awaiting retry. A brief disconnect preserves changes in an already loaded session. Reopening the app requires connectivity; this is not an offline installation.
- Each tab has an editor UUID. A Web Lock detects duplicated tab identifiers. The database permits updates only when owner, revision and editor match. Taking over is explicit and invalidates the previous editor's saves.
- A recoverable local draft is restored automatically when its base revision matches. Divergent drafts are archived, with a review/download/restore interface. Restoring cannot change checked answers or extend the clock.
- A queued offline submission stays paused until it can be sent. Repeated submission returns the same final attempt. No answer keys are sent before checking/submission.
- Account changes clear the displayed session. Local drafts are only loaded after verifying the corresponding signed-in account. IndexedDB is scoped by account but is not an encrypted vault against someone with local browser/devtools access.
- Another device restores the last successful cloud save. Sudden process or power loss can lose time/changes since the latest completed checkpoint; exact crash-time recovery is not promised.

The production table allows students to select only their own rows through RLS. Direct client mutations are revoked. Validated server endpoints use the service role and always constrain owner, revision, and editor. Historical answer keys live only in the server-side versioned TypeScript bank, never in browser bundles or the attempts table.

## Extract and review content

Keep the supplied filenames in `raw pdfs/`. [`scripts/source-manifest.json`](scripts/source-manifest.json) is the opt-in source inventory; adding a PDF locally does not change a bank until it is explicitly enabled. The parser uses PyMuPDF tables and coordinates, joins page/column continuations, matches subject/original-number keys, compares standalone/merged sources, and consolidates exact duplicates. It never supplies missing answers or rewrites clinical explanations.

```bash
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt
npm run extract
npm run validate:bank
```

`extract` creates content-addressed immutable modules under `src/data/versions/bank-*/` and updates `src/data/question-bank.ts`. `validate:bank` re-extracts the enabled sources and compares generated bytes with the current version. Preserve old bank directories while attempts reference them.

Every version includes `report.json`: input SHA-256 hashes, source/page inventory, duplicate mappings, conflicts, issue counts, and every excluded record with its raw text. `needs_review` records cannot enter scored sessions. Unresolved diagrams/tables remain in the original PDFs and are quarantined; the MVP does not flatten uncertain figures into scored text questions. Explicitly reviewed case groups retain shared context; unresolved dependencies are excluded.

Notion content can be imported into the canonical bank from a local HTML/Markdown export or from the verified public snapshot source. A Notion export may be one file or a directory of page files. For one file, add its path, `subject`, and canonical URL to the disabled Notion entry in the source manifest. For a directory, add a `subjects` map keyed by each relative HTML/Markdown filename, or use subject-named filenames. Then enable the entry and run `npm run extract`. Before enabling it, inspect a local page with `npm run extract:notion -- path/to/page.html --subject biochemistry --url https://... --output .local/notion-review.json`. Explicit answer keys or one unambiguous highlighted choice are required; multiple-response, matching, fill-in, figure-dependent, malformed, conflicting, and incomplete records remain `needs_review`. `With Ratio` and `For Revision` are retained as source metadata, never used as a substitute for parsed rationale content. Per-option rationales are optional at the type boundary and the validated correct-choice rationale fills the legacy overall explanation only when the overall field is absent.

Verified local visuals and reviewed multiple-response overrides are opt-in through [`scripts/visual-manifest.json`](scripts/visual-manifest.json). Store immutable files under `public/assets/` and record each asset’s SHA-256, kind, alt text, source locator, and visibility. A dependent question is eligible only when its required asset and answer key are independently verified; answer-marked captures are feedback-only and cannot satisfy a question visual. The checked-in manifest is intentionally empty, so the current unresolved visual and multiple-response records remain excluded until review.

If an export is unavailable, `npm run extract:notion-public` can make a read-only snapshot of the public [PLE QBank](https://plereviewhub.notion.site/5534be59f2684365b4c4d9be5a70af86) through its public page API. It hydrates the lazy option-rationale blocks and writes `.local/notion-public-snapshot.json` plus `.local/notion-public-qbank.json`. The observed green answer background is represented by Notion's `teal_background` block color on the expanded rationale, and is accepted only as an explicit source annotation. The snapshot source is enabled in the manifest only after that mapping is verified; run `npm run extract` to create a new immutable bank version. Records with missing/ambiguous highlights, visual dependencies, malformed choices, or other review issues remain excluded from scored sessions; no answer is inferred from clinical prose or rationale text.

The scanned PLE PDF is intentionally disabled in the manifest. Install Tesseract on the host and run the representative sample workflow without publishing its output:

```bash
.venv/bin/pip install -r scripts/requirements.txt
.venv/bin/python scripts/ocr_pdf.py "raw pdfs/821551629-Ple-Test-Bank-compressed.pdf" \
  --layout --pages 1-10,216-225,426-435 --output .local/ocr-ple-layout-sample.json
```

The layout pass retains Tesseract TSV word coordinates and separates the left
question/options cell from the right answer/rationale cells. Every OCR page is
still recorded with the source hash, page number, configuration, and
`needs_review` status. Answer highlights, option boundaries, column splits, and
OCR text must be manually verified before any page can contribute to a new
immutable bank version.

After the representative review, run the same adapter across the complete scanned source when a full review artifact is needed:

```bash
.venv/bin/python scripts/ocr_pdf.py "raw pdfs/821551629-Ple-Test-Bank-compressed.pdf" \
  --layout --pages 1-435 --output .local/ocr-ple-layout-full.json
```

The full-pass JSON is a local, review-only artifact; it does not enable the
source or modify the generated bank. The plain-text report remains available
as `.local/ocr-ple-full.json` for comparison/audit.

Build conservative question-and-answer candidates from that report with
`npm run extract:ocr`. The command preserves each raw OCR block, coordinate
layout, and source page locator. Every candidate remains `needs_review` because
OCR cannot prove the answer highlight, clinical text, or ambiguous boundaries.

The completed representative-page review and quarantined source findings are recorded in [`docs/OCR_SAMPLE_REVIEW.md`](docs/OCR_SAMPLE_REVIEW.md).

```bash
.venv/bin/python scripts/review_page.py 608745822-Karl-Avillo-Microbiology.pdf 1
```

This renders `.local/source-review.png` for inspection. See [`docs/CONTENT_REVIEW.md`](docs/CONTENT_REVIEW.md) for the visual audit and review limits. “Validated” means structurally checked extraction and source-key pairing, not independent clinical validation of historical medical material.

## Project map

| Location               | Responsibility                                               |
| ---------------------- | ------------------------------------------------------------ |
| `src/components/`      | Dashboard, setup, exam, results, recovery                    |
| `src/lib/engine.ts`    | Selection, clocks, locked answers, scoring                   |
| `src/lib/answers.ts`   | Answer-mode normalization, validation, set comparison        |
| `src/lib/client/`      | IndexedDB, serialized synchronization, editor identity       |
| `src/lib/server/`      | Auth, request validation, ownership and CAS storage          |
| `src/app/api/`         | Session/dashboard/create/load/claim/save/check/submit/logout |
| `src/app/auth/`        | Google login and PKCE callback                               |
| `src/data/`            | Immutable generated question bank; server-only entry point   |
| `scripts/`             | Manifested PDF/Notion extraction, OCR sampling, and source review |
| `supabase/migrations/` | Postgres schema and RLS                                      |
| `tests/`               | Engine, database, bank, and Playwright tests                 |

`POST /api/attempts/[id]` takes `action`, `editorId`, `revision`, and an `edits` checkpoint for save/check/submit. Claim additionally accepts an explicit `takeover`; check takes `questionId`. All mutations require a same-origin JSON request. See the route schemas for exact fields.

## Checks and production build

```bash
npm run typecheck
npm run lint
npm test
npm run audit:styles
npx playwright install --with-deps chromium
npm run test:browser
npm run build
npm start
```

Browser tests launch an isolated local preview on port 3100 automatically (`PLE_TEST_PORT` overrides it), with cloud storage disabled. Your development app can keep running on port 3000. The database tests use embedded PostgreSQL to exercise the actual migration and RLS, without a live Supabase project. Live Google OAuth and real cross-device/cloud acceptance checks are listed separately in `docs/VERIFICATION.md`.

To run the same browser suite against the production build, use `PLE_TEST_PRODUCTION=true npm run test:browser` after `npm run build`.

Full offline installation, payments, admin tooling, and a four-day exam scheduler remain outside this MVP.

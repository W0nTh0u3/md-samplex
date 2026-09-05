# Philippine PLE Practice App MVP

This is the proposed plan supplied for implementation. It records intended scope; see `../README.md` and `VERIFICATION.md` for setup, delivered behavior, and verification limits.

## 1. Product and framework

Build a responsive study app for the Philippine Physicians Licensure Examination, with Google sign-in, subject-based practice, timed sessions, results, and progress that follows students across devices.

Use **Next.js App Router + TypeScript**, Tailwind CSS, and **Supabase Auth + Postgres**. Next.js provides the React interface and server endpoints for saving attempts and grading; Supabase handles accounts and persistent data. This is the recommended stack for the cross-device version. [Next.js documentation](https://nextjs.org/docs/app/getting-started), [Supabase integration](https://supabase.com/docs/guides/auth/server-side/nextjs)

The merged PDF contains all 12 subject sections, with answer numbering reaching 700 in each. The separate microbiology document reaches 150. These are inventory observations; the final usable count will come from extraction, duplicate detection, and validation.

## 2. Extract the PDFs into TypeScript

- Build a repeatable extraction command using Python and PyMuPDF’s text coordinates and table support. Handle the Superexam question/explanation tables and the microbiology document’s two-column layout separately. [PyMuPDF extraction documentation](https://pymupdf.readthedocs.io/en/latest/recipes-text.html)
- Generate subject-level TypeScript modules with a single entry point at `src/data/question-bank.ts`. PDF processing happens during content preparation; the application consumes the generated bank.
- Define question records containing a stable ID, subject, original question number, stem, labeled choices, correct choice, source explanation, source filename/page references, and optional shared-case or figure references.
- Preserve questions and explanations that continue across pages, clinically meaningful symbols and units, tables, and required diagrams. Keep original choice order because options sometimes refer to other letters.
- Match questions to answer keys by subject and original number. Preserve linked clinical cases and select their questions together.
- Compare the standalone volumes with the merged volume. Consolidate matching duplicates while retaining their source references; flag conflicting versions.
- Produce an extraction report accounting for imported questions, duplicates, missing answers, invalid keys, incomplete text, and missing figures. Preserve unresolved records as `needs_review` and exclude them from scored sessions. Never invent missing answers or explanations.
- Keep generated bank versions immutable so saved attempts remain attached to the questions and answers they originally used.

## 3. Study experience and timing

PRC’s October 2026 program allocates **two hours per subject**. For a 100-question block, that provides an average pacing budget of **72 seconds per question**. The supplied Topnotch instructions instead recommend **90 minutes per 100 questions**, averaging **54 seconds**. The app will time the whole block; these averages are pacing guidance. [PRC exam program](https://www.prc.gov.ph/sites/default/files/October%202026%20PLE%20Program%20of%20Exam.pdf)

| Mode          | Timing                        | Answer feedback                     |
| ------------- | ----------------------------- | ----------------------------------- |
| Practice      | Untimed                       | After explicitly checking an answer |
| PLE pace      | 120 minutes per 100 questions | After submission                    |
| Topnotch pace | 90 minutes per 100 questions  | After submission                    |

- Support one subject per attempt, with 25, 50, or 100 questions. Scale shorter timed sessions proportionally and only offer sizes the validated bank can supply. Randomize questions while preserving shared-case groups and original option order.
- Provide a dashboard with subject availability, resumable attempts, recent results, and accuracy by subject.
- Provide an exam screen with one question at a time, previous/next navigation, a question navigator, review flags, progress, timer, and save status.
- In practice mode, checking an answer locks that response and reveals the source answer and explanation. Timed responses remain editable until submission.
- Following the user's preference, **pause timed sessions when the exam becomes hidden, students navigate away, or they explicitly pause**. Restore interrupted attempts in a paused state with a Resume button. These modes measure active study time.
- Use elapsed-time calculations rather than decrementing a counter. Submit once at zero remaining time, and confirm early submission with an unanswered-question count.
- Results show score, correct/incorrect/unanswered counts, and source explanations, with filters for mistakes and flagged questions.

Use the dark palette, surfaces, and controls from `DESIGN.md`. Update `AGENTS.md` with the project’s extraction and persistence requirements and chosen `gpt-taste` exceptions: focused study layouts, functional question numbering, readable content, and restrained motion. Continue invoking the skill and its applicable preflight checks.

## 4. Accounts, interfaces, and saved progress

- Use Google-only authentication through Supabase, with persistent sessions managed through its Next.js integration. Protect each student’s records with ownership checks and database row-level security. [Google sign-in](https://supabase.com/docs/guides/auth/social-login/auth-google), [row-level security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- Define an `Attempt` containing its owner, bank version, fixed question order, answers, checked questions, review flags, current position, mode, remaining active time, status, and save revision.
- Add authenticated operations for listing subjects/history and creating, loading, saving, resuming, checking practice answers, and submitting attempts. Grade on the server; question responses omit correct answers and explanations until feedback is allowed.
- Save answer changes and navigation locally immediately, then sync them to Supabase. Checkpoint the running timer every second locally and every five seconds remotely, with an additional save when pausing.
- Use **IndexedDB** for durable local recovery and pending changes. Reserve `localStorage` for small preferences. `sessionStorage` clears when its tab/window closes, so it is unsuitable as the progress store. [IndexedDB](https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API), [sessionStorage](https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage)
- Show whether progress is saved locally, syncing, synced, or awaiting retry. An already loaded attempt can retain edits during a brief disconnect; another device restores the latest successful cloud save.
- Permit one active editor per attempt, with explicit takeover on another tab/device. Reject stale saves using ownership and revision checks, and preserve conflicting local drafts for recovery instead of silently overwriting progress.
- Recover sudden crashes from the latest completed checkpoint. Exact crash-time recovery cannot be guaranteed. Scope local drafts to the signed-in account and prevent their exposure after switching accounts.

## 5. Verification and delivery defaults

- Validate the complete extracted bank: stable IDs, correct key-to-question pairing, actual choice labels, shared cases, figures, and explicit accounting for every excluded item. Visually check representative source pages and all flagged extraction anomalies. Confirm regeneration is deterministic.
- Test scoring, practice feedback locking, question order preservation, timer calculations, pause/resume, zero-time submission, and repeated submission.
- Test refresh, accidental closure, crash recovery, interrupted saves, expired authentication, cross-device resume, and competing tabs. Verify one account cannot access another account’s attempts.
- Run type checking, linting, production build, and focused browser tests covering mobile layouts, keyboard navigation, focus visibility, and reduced motion.
- Provide environment templates, database migrations, and setup instructions. Live Google sign-in and cross-device acceptance testing require a configured Supabase project and Google OAuth credentials.
- Use “PLE Practice” as the working name. Deliver a locally runnable MVP with source-attributed explanations; full offline installation, payments, administration tools, and a four-day exam scheduler are deferred.

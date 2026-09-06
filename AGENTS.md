# Repository instructions

## Engineering standards

These standards apply to all repository work.

- Apply the judgment, rigor, and ownership expected of a principal software engineer with 20+ years of experience.
- Understand the existing architecture and follow repository conventions before making changes.
- Prefer simple, readable, maintainable solutions. Avoid unnecessary abstractions, dependencies, and unrelated refactors.
- Apply best practices appropriate to the task, considering correctness, security, accessibility, and performance.
- Address root causes, handle relevant edge cases and errors, and preserve existing user changes.
- Verify changes using appropriate tests and available project checks. Clearly report verification results and any remaining limitations.
- Explain significant technical tradeoffs and flag assumptions that could materially affect the outcome.

## UI and frontend work

- Before making UI or frontend decisions, read [`DESIGN.md`](./DESIGN.md). Treat it as the source of truth for the visual theme, colors, typography, components, layout, responsive behavior, and interaction styling.
- For every UI or frontend task—including pages, components, styling, layout, responsive behavior, motion, and interactions—use the [`gpt-taste` skill](./.agents/skills/gpt-taste/SKILL.md). Read and follow it before implementation.
- Follow all requirements in `gpt-taste`, including its mandatory `<design_plan>` preflight before writing React or other UI code. Do not replace the skill with generic UI guidance.
- If explicit user requirements conflict with the design guidance, follow the user requirements. Otherwise, resolve UI decisions using `DESIGN.md` together with `gpt-taste`.
- Keep these requirements scoped to UI and frontend work; they do not apply to unrelated backend, documentation, or tooling tasks.

### SCSS architecture

- Component-specific styles belong in colocated `*.module.scss` files; use CSS Module class maps in the owning component.
- Reserve `src/styles/globals.scss` for true global behavior, design tokens, resets, accessibility rules, Tailwind utilities, and genuinely shared primitives.
- Use Sass `@use` and `@forward`; do not add Sass `@import` statements. Keep the Tailwind vendor import in `src/styles/tailwind.css`.
- Keep `DESIGN.md` as the visual source of truth.
- Preserve focus visibility, mobile density, natural clinical-text wrapping, and reduced-motion behavior.
- Run the styling and browser checks after visual changes.

### Component maintainability

- Split components by feature responsibility, not arbitrary line counts. Use file size as a review signal rather than enforcing a rigid maximum.
- Keep stateful orchestration thin and move presentational feature sections into focused components with clear ownership.
- Keep component-specific styles colocated in the owning CSS Module.
- Extract shared components only when reuse or a clear shared responsibility exists.
- Treat generated data and immutable artifacts as intentional exceptions to ordinary file-size and refactoring guidance.
- Avoid duplicate markup, duplicated responsive rules, and parallel implementations of the same state.
- Preserve public entrypoints and behavior during structural refactors.
- After UI refactors, run formatting, typecheck, lint, unit/database, build, style, and browser checks.

## PLE Practice project requirements

- `docs/MVP_PLAN.md` records the approved product scope. Keep setup and verification status in `README.md` and `docs/VERIFICATION.md`.
- Generate the bank using `scripts/extract.py`; never fabricate keys, explanations, missing clinical text, or diagrams. Retain source filenames and page references. Quarantine unresolved content as `needs_review` and exclude it from scored sessions.
- Bank versions are immutable. Retain every version referenced by saved attempts. Preserve option order and select shared-case groups together.
- Grade on the server and withhold keys/explanations until practice checking or submission. Ownership, editor identity, and revision checks must guard every mutation; maintain database RLS.
- Persist local recovery in account-scoped IndexedDB, with explicit conflict recovery. Timed modes measure active study time and pause on visibility loss/navigation. Never silently overwrite another editor.

### Approved gpt-taste exceptions for study screens

- Use focused dashboard, session, and results layouts instead of marketing AIDA sections, randomized hero/component architectures, decorative imagery, and large cinematic spacing.
- Functional question numbering, source numbers, progress counts, and concise section labels are allowed.
- Follow `DESIGN.md` typography/fallbacks; clinical prose may use a readable 1.6 line height and wrap naturally. Headings remain compact and wide.
- Use restrained CSS transitions with reduced-motion support instead of GSAP pinning, scrubbing, stacking, or moving study content.
- Keep the mandatory `<design_plan>` preflight, adapting its RNG/AIDA/motion checks to these explicitly approved exceptions. Check responsive density, contrast, focus, and heading wrapping before implementation.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

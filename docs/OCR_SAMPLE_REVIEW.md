# Scanned PLE OCR sample review

Source: `raw pdfs/821551629-Ple-Test-Bank-compressed.pdf`  
SHA-256: `71030beb06aa33b61e712ba066cbaf3f7f416040afd4e28fc256e4601c3d8a0d`

The representative OCR pass covered pages `1–10`, `216–225`, and `426–435`.
All 30 rendered source pages were visually inspected against the coordinate
report `.local/ocr-ple-layout-sample.json` using Tesseract 5.3.4 / English /
300-DPI / PSM 6. The layout report retains TSV word coordinates and separates
the question/options cell from the answer/rationale cells at x=`1130`.

| Pages | Source section | Candidate range | Review result |
|---|---|---:|---|
| 1–3 | Cover, contents, and section heading | — | Not question records; excluded |
| 4–10 | Biochemistry | 1–21 | Table layout and explicit answer column visible; page continuations retained for review |
| 216–225 | Internal Medicine | 28–58 | Mostly readable; source corrections, tables, and the incomplete page-225 continuation remain quarantined |
| 426–435 | Preventive Medicine | 79–100 | Mostly readable; explanation tables and cross-page continuations remain quarantined |

Specific records requiring follow-up:

- Question 50 contains a source explanation that corrects one of its own option
  values; it is not safe to normalize automatically.
- Question 52 has answer-column key `A`, while the explanation heading says
  `C. Hypomagnesemia`; the source discrepancy is retained for adjudication.
- Questions 47, 80, and 97 include explanatory tables whose visual structure
  must be preserved or explicitly reviewed before import.
- Question 58 begins at the bottom of page 225 and continues beyond the sample
  range, so its stem and rationale are incomplete in this pass.
- Several records span adjacent sampled pages (including 31, 34, 37, 41, 44,
  54, 91, and 94); their combined page references must be retained during
  structured transcription.

No answer key, explanation, option boundary, or missing clinical text was
inferred. The scanned source remains disabled in
`scripts/source-manifest.json`; no OCR record was admitted to a bank version.

## Full-page OCR pass

After the representative review, the coordinate-aware OCR adapter was run
across all 435 source pages in four deterministic ranges and merged only after
validating identical source/configuration metadata. The review-only report is
available locally at `.local/ocr-ple-layout-full.json` and records the same
source SHA-256 above, Tesseract 5.3.4, English, 300 DPI, PSM 6, TSV layout, and
the x=`1130` column split. It contains exactly one page entry for each page,
with all 435 entries still marked `needs_review`; no records were promoted into
the immutable bank.

The review-only Q&A candidate pass is generated with `npm run extract:ocr` and
is available locally at `.local/ocr-ple-qbank.json`. It contains 1,200 numbered
records: 1,161 records with recoverable OCR question blocks and 39 explicit
empty boundary placeholders. All 1,200 remain `needs_review`; each candidate
also retains its raw OCR block, PDF page locator, source hash, OCR
configuration, and layout-review issues for manual correction.

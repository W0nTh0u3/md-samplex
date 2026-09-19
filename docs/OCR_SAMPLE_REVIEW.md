# Scanned PLE OCR sample review

Source: `raw pdfs/821551629-Ple-Test-Bank-compressed.pdf`  
SHA-256: `71030beb06aa33b61e712ba066cbaf3f7f416040afd4e28fc256e4601c3d8a0d`

The representative OCR pass covered pages `1–10`, `216–225`, and `426–435`.
All 30 rendered source pages were visually inspected against the coordinate
report `.local/ocr-ple-layout-sample.json` using Tesseract 5.3.4 / English /
300-DPI / PSM 6 as the historical baseline. A follow-up comparison using PSM
4 recovered more complete option rows on the same pages without improving the
answer-presence rate, so PSM 4 is now the default for new review passes. The
layout report retains TSV word coordinates and separates the question/options
cell from the answer/rationale cells at x=`1130`.

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
validating identical source/configuration metadata. The review-only baseline is
available locally at `.local/ocr-ple-layout-full.json` and records the same
source SHA-256 above, Tesseract 5.3.4, English, 300 DPI, PSM 6, TSV layout, and
the x=`1130` column split. New runs use PSM 4 by default; pass `--psm 6` to
reproduce the baseline. Both configurations contain exactly one page entry
for each page, with all entries still marked `needs_review`; no records were
promoted into the immutable bank.

The local full report currently records a targeted page-7 hybrid override:
PSM 4 supplies the question/options column and PSM 6 supplies the
answer/rationale column. The alternate layout is retained with the page so
the correction is reproducible and auditable.

The review-only Q&A candidate pass is generated with `npm run extract:ocr` and
is available locally at `.local/ocr-ple-qbank.json`. With the current importer
the PSM 6 baseline plus the page-7 hybrid yields 1,200 numbered records: 1,168 records with
recoverable OCR question blocks and 32 explicit empty boundary placeholders.
Seven comma-separated OCR question boundaries are retained with an explicit
boundary-review issue. All 1,200 remain `needs_review`; each candidate also
retains its raw OCR block, PDF page locator, source hash, OCR configuration,
and layout-review issues for manual correction.

For the OCR review queue, `npm run review:ocr` renders the answer/explanation
column directly from the source PDF for every recoverable candidate. The local
`.local/ocr-ple-explanation-manifest.json` records content hashes, source
locators, crop coordinates, and feedback-only visibility; the associated
`.local/ocr-ple-source-audit.json` checks all 1,200 question slots against the
reconstructed OCR blocks. In the current artifact, 1,168 candidates have at
least one source crop and 32 boundary placeholders have no crop by design.
The audit is structural evidence only: it does not replace independent visual
transcription or clinical review, and none of these unverified crops are in
`public/assets` or the scored bank.

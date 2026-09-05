# Content review and release boundary

The scored bank is structurally validated against the supplied historical PDFs. It is not a medical editorial review or confirmation that historical clinical/legal guidance is current.

## Source inspection performed

| Source / page | Observation and handling |
|---|---|
| Merged / 1, biochemistry 1 | D and E are merged in the source (`pIE. pH`). Retained verbatim and excluded; no guessed option split. |
| Merged / 1–2, biochemistry 6 | Explanation continues in the unnumbered top row on page 2. Appended to item 6 with both page references. |
| Merged / 96, anatomy 26 | Explanation cell is visibly blank. Missing explanation is genuine source content, not dropped extraction. Record remains excluded. |
| Merged / 91–92 and other subject key pages | The first key page may say “KEY ANSWER” or just “ANSWER”; continuation pages may have no table heading. Number/key pairs are read from the key regions, not inferred from explanations. |
| Avillo / 1 | Two independent question columns with vertically centered numbers. Column-clipped table cells recover stems and option labels without shifts. |
| Avillo / 11 | Independent answer/explanation columns, including an explanation continuing from left to right. Keys 1–7 are E, A, B, B, B, D, E; key 10 is D and 11–13 are C, C, A. |
| Avillo / 1 and 11 | The gray diagonal URL watermark is vector art. Its observed color, dimensions and diagonal position are ignored by the figure detector only for this source. Other images and non-grid vector art remain flagged. |
| Avillo / 1, items 3–7 and 10–13 | Visually confirmed case clusters. Shared context comes directly from the first stem; selection preserves the group. Any unresolved member excludes its entire group. |

## Automated complete-bank checks

The extraction report accounts for all 8,550 original question numbers before content deduplication, all nine input files, merged/standalone duplicates, invalid or missing keys, malformed choices, missing explanations, potential figures, shared cases and source corrections. The tests enforce unique IDs, original ordered choice labels, source-page references, score eligibility, and explicit review records for every excluded item.

Each bank version includes its detailed `report.json`. The raw text of unresolved records is retained there; the original PDFs preserve tables, symbols, diagrams and exact visual layout. Use `scripts/review_page.py` to render any flagged source page. Do not promote a record by removing a flag without checking its source and creating a new bank version.

## Remaining review

The audit above is representative, not a claim that every excluded record was visually adjudicated. All unresolved records remain excluded from scoring. Exhaustive visual adjudication of the review queue and independent medical/legal currency review remain future content work. Ambiguous figure/table records are not rendered as scored text-only questions. Unresolved case bounds are not guessed.

Source wording, typos and historical answers are preserved. In particular, a source explanation can itself be inaccurate or refer to neighboring content. The app identifies explanations as historical source material; it does not endorse their use as current patient-care guidance.

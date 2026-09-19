"""Build review-only question candidates from the scanned-PDF OCR report.

The scanned source is a three-column table (question, answer, explanation),
and Tesseract's plain-text output interleaves those columns.  This adapter
therefore extracts conservative candidates and keeps the lossless OCR block
with every record.  It never promotes a candidate to ``validated`` and it
never repairs an OCR key, option, question number, or clinical statement.

Use this after ``scripts/ocr_pdf.py --layout`` has produced a full-page JSON
report:

    .venv/bin/python scripts/ocr_import.py .local/ocr-ple-layout-full.json \
        --output .local/ocr-ple-qbank.json

The result is a draft artifact for manual transcription/adjudication.  It is
not a bank version and is intentionally not wired into scored sessions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]

# The page boundaries are visible in the source contents/section headers.  A
# boundary page is included with the preceding subject when it contains the
# final record's continuation, and the next subject starts at its question
# table.  These ranges are source-specific and remain review metadata.
SECTION_RANGES: tuple[tuple[str, int, int], ...] = (
    ("biochemistry", 4, 36),
    ("anatomy", 38, 67),
    ("physiology", 69, 96),
    ("microbiology", 98, 134),
    ("pathology", 135, 167),
    ("pharmacology", 169, 202),
    ("internal-medicine", 205, 242),
    ("pediatrics", 244, 282),
    ("obstetrics-gynecology", 284, 325),
    ("surgery", 327, 360),
    ("legal-medicine", 362, 390),
    ("preventive-medicine", 392, 435),
)

QUESTION_RE = re.compile(
    # Commas are a common scan substitution for the source period (for
    # example, ``44, Which ...``).  Keep this permissive only for OCR
    # candidates; every resulting record remains needs_review.
    r"^\s*[^A-Za-z0-9]{0,4}(?P<number>\d{1,3})\s*"
    r"(?P<separator>[.),])\s+(?P<text>.+)$"
)
OPTION_MARKER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<label>[A-Ea-e0])\s*[.)>:,]\s*"
)
ANSWER_PAIR_RE = re.compile(
    r"(?<![A-Za-z])(?P<key>[A-Ea-e])(?:[a-e])?\s+"
    r"(?P<label>[A-Ea-e])\s*[.)>:,]\s*"
)
RIGHT_ANSWER_RE = re.compile(
    r"^\s*(?P<key>[A-Ea-e])\s*[.)>:,]\s*(?P<answer>.*)$"
)
RIGHT_ANSWER_WITH_LABEL_RE = re.compile(
    r"^\s*(?P<key>[A-Ea-e])c?\s+(?P<label>[A-Ea-e])\s*[.)>:,]\s*(?P<answer>.*)$"
)
REFERENCE_START_RE = re.compile(
    r"(?i)^(?:amsterdam|mcgraw|lippincott|w\.?\s*b\.?\b|new york|"
    r"elsevier|garcia|publishing|education|wilkins|p\.?\s*\d|"
    r"pp\.?\s*\d|ed\.?\b)"
)
QUESTION_WORDS_RE = re.compile(
    r"(?i)^(?:which|what|why|how|who|where|when|is|are|does|do|can|"
    r"will|in|a |an |the |this |these |following|during|according|"
    r"if |to |at |on |for |all |among )"
)
REFERENCE_LINE_RE = re.compile(
    r"(?i)^(?:references?|reference\s*:|source\s*:|https?://)"
)
FOOTER_RE = re.compile(r"^\s*\d{1,3}(?:\s+\d{1,3})?\s*$")


def clean(value: str | None) -> str:
    """Normalize whitespace without correcting OCR spelling or symbols."""

    text = (value or "").replace("\u00a0", " ")
    return "\n".join(
        re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()
    ).strip()


def normalized(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _position_key(position: tuple[int, int]) -> tuple[int, int]:
    return position


def _is_before(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return _position_key(left) < _position_key(right)


def _page_lines(page_rows: dict[int, dict[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for page in range(start, end + 1):
        row = page_rows[page]
        layout = row.get("layout")
        layout_lines = layout.get("lines") if isinstance(layout, dict) else None
        if isinstance(layout_lines, list):
            for line_number, layout_line in enumerate(layout_lines):
                if not isinstance(layout_line, dict):
                    continue
                left_text = clean(str(layout_line.get("leftText", "")))
                right_text = clean(str(layout_line.get("rightText", "")))
                full_text = clean(str(layout_line.get("text", "")))
                if not (left_text or right_text or full_text):
                    continue
                lines.append(
                    {
                        "page": page,
                        "line": line_number,
                        "text": left_text,
                        "leftText": left_text,
                        "rightText": right_text,
                        "fullText": full_text,
                        "words": layout_line.get("words", []),
                        "columnSplitX": layout.get("columnSplitX"),
                        "ocr": row.get("ocr"),
                        "layout": True,
                    }
                )
            continue
        for line_number, text in enumerate(str(row.get("text", "")).splitlines()):
            lines.append(
                {
                    "page": page,
                    "line": line_number,
                    "text": text,
                    "leftText": text,
                    "rightText": "",
                    "fullText": text,
                    "ocr": row.get("ocr"),
                    "layout": False,
                }
            )
    return lines


def _is_candidate_start(lines: list[dict[str, Any]], index: int, text: str) -> bool:
    stripped = text.strip()
    if REFERENCE_START_RE.match(stripped.lstrip(". ")):
        return False
    window = " ".join(
        clean(item["text"]) for item in lines[index : min(len(lines), index + 8)]
    )
    return bool(
        OPTION_MARKER_RE.search(stripped)
        or "?" in window
        or ":" in stripped
        or QUESTION_WORDS_RE.match(stripped)
    )


def _question_candidates(
    page_rows: dict[int, dict[str, Any]], start_page: int, end_page: int
) -> list[dict[str, Any]]:
    lines = _page_lines(page_rows, start_page, end_page)
    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(lines):
        match = QUESTION_RE.match(item["text"])
        if not match:
            continue
        number = int(match.group("number"))
        text = match.group("text").strip()
        # A numbered row in the recovered left table column is a stronger
        # boundary signal than punctuation heuristics. Plain OCR still uses
        # the conservative heuristic because its columns are interleaved.
        layout_boundary = bool(item.get("layout")) and bool(text)
        if not 1 <= number <= 100 or (
            not layout_boundary and not _is_candidate_start(lines, index, text)
        ):
            continue
        candidates.append(
            {
                "index": index,
                "page": item["page"],
                "line": item["line"],
                "rawNumber": number,
                "separator": match.group("separator"),
                "text": text,
            }
        )
    return candidates


def _select_question_starts(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[int]]:
    """Select the physical 1..100 sequence without trusting OCR numbering.

    A large number jump immediately followed by the next sequential number is
    treated as an OCR number mismatch (for example, source ``12`` read as
    ``42``).  A one-number gap becomes an explicit placeholder instead.  A
    later candidate with the expected number causes the current candidate to
    be ignored as a table/reference false positive.
    """

    selected: list[dict[str, Any]] = []
    missing: list[int] = []
    expected = 1
    index = 0

    while expected <= 100 and index < len(candidates):
        current = candidates[index]
        raw_number = current["rawNumber"]
        if raw_number < expected:
            index += 1
            continue
        if raw_number == expected:
            selected.append({**current, "number": expected, "numberMismatch": False})
            expected += 1
            index += 1
            continue

        later_expected = next(
            (
                position
                for position in range(index + 1, len(candidates))
                if candidates[position]["rawNumber"] == expected
            ),
            None,
        )
        if later_expected is not None:
            index += 1
            continue

        next_raw = (
            candidates[index + 1]["rawNumber"]
            if index + 1 < len(candidates)
            else None
        )
        if raw_number == expected + 1:
            missing.append(expected)
            expected += 1
            continue
        if next_raw == expected + 1 or next_raw is None or (
            next_raw > expected and next_raw < raw_number
        ):
            selected.append({**current, "number": expected, "numberMismatch": True})
            expected += 1
            index += 1
            continue

        missing.append(expected)
        expected += 1

    if expected <= 100:
        missing.extend(range(expected, 101))
    return selected, sorted(set(missing))


def _marker_label(value: str) -> str:
    return "D" if value.casefold() == "0" else value.upper()


def _option_markers(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for line_index, item in enumerate(lines):
        text = item["text"]
        for match in OPTION_MARKER_RE.finditer(text):
            markers.append(
                {
                    "line": line_index,
                    "char": match.start(),
                    "end": match.end(),
                    "label": _marker_label(match.group("label")),
                    "text": text[match.end() :],
                }
            )
    return markers


def _ordered_sequences(markers: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    sequences: list[list[dict[str, Any]]] = []
    for start_index, marker in enumerate(markers):
        if marker["label"] != "A":
            continue
        sequence = [marker]
        previous_label = "A"
        for candidate in markers[start_index + 1 :]:
            label = candidate["label"]
            if label == "A":
                break
            if label not in {"B", "C", "D", "E"}:
                continue
            if ord(label) <= ord(previous_label):
                continue
            sequence.append(candidate)
            previous_label = label
            if label == "E":
                break
        if len(sequence) >= 2:
            sequences.append(sequence)
    return sequences


def _sequence_score(sequence: list[dict[str, Any]]) -> tuple[int, int, int]:
    gaps = sum(
        (right["line"] - left["line"]) * 100
        + right["char"]
        - left["char"]
        for left, right in zip(sequence, sequence[1:])
    )
    # Prefer a complete option set, then the most compact set.  The final
    # component prefers a later A marker when the answer column repeats the
    # correct choice before the actual option list.
    return len(sequence), -gaps, sequence[0]["line"]


def _slice_between(
    lines: list[dict[str, Any]],
    start: tuple[int, int],
    end: tuple[int, int] | None,
    *,
    filter_layout_noise: bool = False,
) -> str:
    parts: list[str] = []
    for line_index in range(start[0], len(lines)):
        line = lines[line_index]
        text = line["text"]
        if filter_layout_noise and _is_layout_noise_line(line):
            text = ""
        left = start[1] if line_index == start[0] else 0
        right = end[1] if end is not None and line_index == end[0] else len(text)
        if end is not None and line_index > end[0]:
            break
        if right > left:
            parts.append(text[left:right])
        if end is not None and line_index == end[0]:
            break
    return clean("\n".join(parts))


def _is_layout_noise_line(line: dict[str, Any]) -> bool:
    """Reject low-confidence one-token scan specks from an option tail."""

    if not line.get("layout"):
        return False
    tokens = line.get("text", "").split()
    split_x = line.get("columnSplitX")
    if not isinstance(split_x, (int, float)):
        split_x = 1130
    words = [
        word for word in line.get("words", []) if word.get("left", 0) < split_x
    ]
    if len(tokens) != 1 or len(tokens[0]) > 3 or not tokens[0].isalpha():
        return False
    confidences = [
        word.get("confidence")
        for word in words
        if isinstance(word.get("confidence"), (int, float))
    ]
    if not confidences:
        return False
    if max(confidences) < 60:
        return True
    # PSM 4 occasionally emits a low-confidence page number plus a fragment
    # where an option line should be. It has no explicit option marker and is
    # safer to quarantine than to append to the preceding choice.
    return (
        not OPTION_MARKER_RE.search(line.get("text", ""))
        and max(confidences) < 65
    )


def _remove_question_prefix(text: str, number: int) -> str:
    match = QUESTION_RE.match(text)
    if match:
        return match.group("text")
    # A placeholder/mismatch still retains the raw line if OCR punctuation was
    # too damaged for QUESTION_RE.
    return re.sub(rf"^\s*[^A-Za-z0-9]{{0,4}}{number}\s*[.),]\s*", "", text)


def _question_prefix_end(text: str) -> int:
    match = QUESTION_RE.match(text)
    return match.start("text") if match else 0


def _answer_marker(
    lines: list[dict[str, Any]],
    markers: list[dict[str, Any]],
    option_start: tuple[int, int] | None,
) -> dict[str, Any] | None:
    if any(item.get("layout") for item in lines):
        option_line = option_start[0] if option_start is not None else len(lines)
        for line_index, item in enumerate(lines[: option_line + 1]):
            text = clean(item.get("rightText", ""))
            if not text:
                continue
            labelled = RIGHT_ANSWER_WITH_LABEL_RE.match(text)
            if labelled:
                return {
                    "line": line_index,
                    "char": 0,
                    "end": len(text),
                    "rightEnd": len(text),
                    "key": labelled.group("key").upper(),
                    "answerText": (
                        f"{labelled.group('label').upper()}. "
                        f"{labelled.group('answer')}"
                    ).strip(),
                    "layout": True,
                }
            answer_line = RIGHT_ANSWER_RE.match(text)
            if answer_line:
                return {
                    "line": line_index,
                    "char": 0,
                    "end": len(text),
                    "rightEnd": len(text),
                    "key": answer_line.group("key").upper(),
                    "answerText": answer_line.group("answer").strip(),
                    "layout": True,
                }
            if len(text) == 1 and text.upper() in {"A", "B", "C", "D", "E"}:
                return {
                    "line": line_index,
                    "char": 0,
                    "end": len(text),
                    "rightEnd": len(text),
                    "key": text.upper(),
                    "answerText": "",
                    "layout": True,
                }

    limit = option_start or (len(lines), 0)
    for line_index, item in enumerate(lines):
        text = item["text"]
        for match in ANSWER_PAIR_RE.finditer(text):
            position = (line_index, match.start())
            if _is_before(position, limit):
                return {
                    "line": line_index,
                    "char": match.start(),
                    "end": match.end(),
                    "key": match.group("key").upper(),
                    "answerText": text[match.end() :],
                }
    before = [
        marker
        for marker in markers
        if _is_before((marker["line"], marker["char"]), limit)
    ]
    if before:
        marker = before[-1]
        return {
            "line": marker["line"],
            "char": marker["char"],
            "end": marker["end"],
            "key": marker["label"],
            "answerText": marker["text"],
        }
    return None


def _cut_at_reference(text: str) -> str:
    kept: list[str] = []
    for line in clean(text).splitlines():
        if REFERENCE_LINE_RE.match(line.strip()):
            break
        if FOOTER_RE.match(line):
            continue
        kept.append(line)
    return clean("\n".join(kept))


def _extract_stem(
    lines: list[dict[str, Any]],
    number: int,
    option_start: tuple[int, int] | None,
    answer: dict[str, Any] | None,
) -> str:
    end = option_start or (len(lines), 0)
    parts: list[str] = []
    for line_index, item in enumerate(lines):
        if line_index > end[0]:
            break
        text = item["text"]
        prefix_end = _question_prefix_end(text) if line_index == 0 else 0
        if line_index == 0:
            text = _remove_question_prefix(text, number)
        if answer and not answer.get("layout") and line_index == answer["line"]:
            answer_char = answer["char"] - prefix_end if line_index == 0 else answer["char"]
            text = text[: max(0, answer_char)]
        if line_index == end[0]:
            option_char = end[1] - prefix_end if line_index == 0 else end[1]
            text = text[: max(0, option_char)]
        if text.strip():
            parts.append(text)
        if line_index == end[0]:
            break
    stem = clean("\n".join(parts))
    # The first question mark/colon is the safest boundary in this interleaved
    # layout.  Anything after it belongs to the explanation column or OCR
    # noise until a reviewer confirms otherwise.
    question_mark = stem.find("?")
    if question_mark >= 0:
        stem = stem[: question_mark + 1]
    else:
        colon = stem.find(":")
        if colon >= 0:
            stem = stem[: colon + 1]
    return clean(stem.strip("|_{};,-: "))


def _extract_explanation(
    lines: list[dict[str, Any]],
    answer: dict[str, Any] | None,
    option_start: tuple[int, int] | None,
    choices: list[dict[str, str]] | None = None,
) -> str:
    if answer is None or option_start is None:
        return ""
    if answer.get("layout"):
        # In the source table, rationale text continues down the right cell
        # while the options continue down the left cell.  Do not stop at the
        # first option marker; that is exactly what caused the flattened OCR
        # import to lose or misassign rationale text.
        parts: list[str] = []
        answer_remainder = ""
        answer_text = clean(answer.get("answerText", ""))
        answer_body = re.sub(r"^[A-Ea-e]\s*[.)>:,]\s*", "", answer_text)
        if choices:
            correct_choice = next(
                (
                    choice["text"]
                    for choice in choices
                    if choice["label"] == answer["key"]
                ),
                "",
            )
            normalized_line = re.sub(r"\s+", " ", answer_body).strip()
            normalized_choice = re.sub(r"\s+", " ", clean(correct_choice)).strip()
            if normalized_choice and normalized_line.casefold().startswith(
                normalized_choice.casefold()
            ):
                answer_remainder = normalized_line[len(normalized_choice) :].strip()
        if answer_remainder:
            parts.append(answer_remainder)
        for line_index, item in enumerate(lines):
            if line_index <= answer["line"]:
                continue
            right_text = clean(item.get("rightText", ""))
            if right_text:
                parts.append(right_text)
        return _cut_at_reference("\n".join(parts))
    text = _slice_between(
        lines,
        (answer["line"], answer["end"]),
        option_start,
    )
    answer_text = clean(answer.get("answerText", ""))
    if answer_text and text.casefold().startswith(answer_text.casefold()):
        text = text[len(answer_text) :]
    # The question's continuation can occur after the answer column on the
    # same OCR path.  Drop it through the first question mark when present.
    question_end = text.find("?")
    if question_end >= 0:
        text = text[question_end + 1 :]
    return _cut_at_reference(text)


def _extract_choices(
    lines: list[dict[str, Any]], sequence: list[dict[str, Any]]
) -> list[dict[str, str]]:
    choices: list[dict[str, str]] = []
    for index, marker in enumerate(sequence):
        next_marker = sequence[index + 1] if index + 1 < len(sequence) else None
        end = (next_marker["line"], next_marker["char"]) if next_marker else None
        if end is None:
            page_break = next(
                (
                    line_index
                    for line_index in range(marker["line"] + 1, len(lines))
                    if lines[line_index]["page"] != lines[marker["line"]]["page"]
                ),
                None,
            )
            if page_break is not None:
                end = (page_break, 0)
            reference_line = next(
                (
                    line_index
                    for line_index in range(marker["line"] + 1, len(lines))
                    if REFERENCE_LINE_RE.match(lines[line_index]["text"].strip())
                ),
                None,
            )
            if end is None and reference_line is not None:
                end = (reference_line, 0)
        text = _slice_between(
            lines,
            (marker["line"], marker["end"]),
            end,
            filter_layout_noise=True,
        )
        choices.append({"label": marker["label"], "text": text.strip("|_{};,- ")})
    return choices


def _block_lines(
    all_lines: list[dict[str, Any]], start_index: int, end_index: int | None
) -> list[dict[str, Any]]:
    end = end_index if end_index is not None else len(all_lines)
    return all_lines[start_index:end]


def _ocr_configuration_groups(
    lines: list[dict[str, Any]], source: dict[str, Any]
) -> list[dict[str, Any]]:
    """Keep page-level OCR overrides alongside report-level defaults."""

    groups: dict[str, dict[str, Any]] = {}
    for line in lines:
        config = line.get("ocr")
        if not isinstance(config, dict):
            config = source["ocr"]
        key = json.dumps(config, sort_keys=True, default=str)
        group = groups.setdefault(key, {"pages": set(), "config": config})
        group["pages"].add(line["page"])
    return sorted(
        (
            {"pages": sorted(group["pages"]), "config": group["config"]}
            for group in groups.values()
        ),
        key=lambda group: group["pages"][0],
    )


def _record_from_block(
    *,
    subject: str,
    number: int,
    start: dict[str, Any],
    end_page: int,
    lines: list[dict[str, Any]],
    source: dict[str, Any],
    page_issues: set[str],
) -> dict[str, Any]:
    markers = _option_markers(lines)
    sequences = _ordered_sequences(markers)
    sequence = max(sequences, key=_sequence_score) if sequences else []
    option_start = (
        (sequence[0]["line"], sequence[0]["char"]) if sequence else None
    )
    answer = _answer_marker(lines, markers, option_start)
    choices = _extract_choices(lines, sequence) if sequence else []
    stem = _extract_stem(lines, number, option_start, answer)
    explanation = _extract_explanation(lines, answer, option_start, choices)
    pages = sorted({item["page"] for item in lines})
    ocr_configurations = _ocr_configuration_groups(lines, source)
    primary_ocr = (
        ocr_configurations[0]["config"]
        if ocr_configurations
        else source["ocr"]
    )
    issues = {
        "ocr_text_requires_manual_review",
        "answer_highlight_requires_manual_review",
        "option_boundaries_require_manual_review",
        "ocr_layout_requires_manual_review",
        *page_issues,
    }
    if start.get("numberMismatch"):
        issues.add("ocr_question_number_requires_manual_review")
    if start.get("separator") == ",":
        issues.add("ocr_question_boundary_requires_manual_review")
    if len(pages) > 1:
        issues.add("cross_page_record_requires_manual_review")
    if not answer:
        issues.add("missing_answer")
    elif answer["key"] not in {"A", "B", "C", "D", "E"}:
        issues.add("invalid_key")
    labels = "".join(choice["label"] for choice in choices)
    if labels not in {"ABCD", "ABCDE"} or any(
        not choice["text"] for choice in choices
    ):
        issues.add("invalid_or_incomplete_choices")
    if len(stem) < 15:
        issues.add("incomplete_stem")
    if not explanation:
        issues.add("missing_explanation")
    prose = f"{stem} {explanation}"
    if re.search(
        r"\b(select all|all that apply|more than one|multiple answers|choose all)\b",
        prose,
        re.IGNORECASE,
    ):
        issues.add("multiple_response_requires_review")
    if re.search(
        r"\b(figure|diagram|pictured|shown below|shown above|image below|"
        r"following graph|following table|table below)\b",
        prose,
        re.IGNORECASE,
    ):
        issues.add("required_figure_or_table_requires_review")
    if re.search(
        r"\b(above case|case above|previous case|same patient|preceding case|"
        r"previous question|patient above|refer to|based on the case|"
        r"following questions|following items|next two questions)\b",
        stem,
        re.IGNORECASE,
    ):
        issues.add("shared_case_requires_review")
    if re.search(
        r"\b(should (?:have )?be(?:en)?|typographical|typo|errat(?:a|um)|"
        r"no correct answer|not .{0,30}but)\b",
        explanation,
        re.IGNORECASE,
    ):
        issues.add("source_correction_requires_review")
    raw_text = clean(
        "\n".join(item.get("fullText", item["text"]) for item in lines)
    )
    first_page = pages[0] if pages else start["page"]
    last_page = pages[-1] if pages else end_page
    source_ref = {
        "filename": source["filename"],
        "pages": pages or [first_page],
        "answerPages": pages or [first_page],
        "kind": "pdf",
        "locator": f"PDF pages {first_page}-{last_page} / Question {number}",
        "metadata": {
            "sourceSha256": source["sha256"],
            "ocrEngine": primary_ocr["engine"],
            "ocrVersion": primary_ocr["version"],
            "ocrLanguage": primary_ocr["language"],
            "ocrDpi": str(primary_ocr["dpi"]),
            "ocrPsm": ",".join(
                str(group["config"].get("psm", ""))
                for group in ocr_configurations
            ),
            "ocrLayout": str(primary_ocr.get("layout", "plain-text")),
            "ocrColumnSplitX": str(primary_ocr.get("columnSplitX", "")),
            "ocrConfigurations": ocr_configurations,
        },
    }
    return {
        "id": f"ocr-ple-{subject}-{number:04d}",
        "subject": subject,
        "originalNumber": number,
        "stem": stem,
        "choices": choices,
        "correctChoice": answer["key"] if answer else None,
        "explanation": explanation,
        "sources": [source_ref],
        "status": "needs_review",
        "issues": sorted(issues),
        "rawQuestionNumber": start["rawNumber"],
        "rawText": raw_text,
    }


def _placeholder_record(
    *,
    subject: str,
    number: int,
    page: int,
    source: dict[str, Any],
) -> dict[str, Any]:
    source_ref = {
        "filename": source["filename"],
        "pages": [page],
        "answerPages": [],
        "kind": "pdf",
        "locator": f"PDF near page {page} / Question {number}",
        "metadata": {
            "sourceSha256": source["sha256"],
            "ocrEngine": source["ocr"]["engine"],
            "ocrVersion": source["ocr"]["version"],
            "ocrLanguage": source["ocr"]["language"],
            "ocrDpi": str(source["ocr"]["dpi"]),
            "ocrPsm": str(source["ocr"]["psm"]),
            "ocrLayout": str(source["ocr"].get("layout", "plain-text")),
            "ocrColumnSplitX": str(source["ocr"].get("columnSplitX", "")),
        },
    }
    return {
        "id": f"ocr-ple-{subject}-{number:04d}",
        "subject": subject,
        "originalNumber": number,
        "stem": "",
        "choices": [],
        "correctChoice": None,
        "explanation": "",
        "sources": [source_ref],
        "status": "needs_review",
        "issues": [
            "missing_ocr_question_boundary",
            "ocr_text_requires_manual_review",
        ],
        "rawQuestionNumber": None,
        "rawText": "",
    }


def _page_issue_set(report: dict[str, Any], pages: Iterable[int]) -> set[str]:
    by_page = {int(row["page"]): row for row in report.get("pages", [])}
    issues: set[str] = set()
    for page in pages:
        issues.update(by_page.get(page, {}).get("issues", []))
    return issues


def _parse_section(
    *,
    subject: str,
    start_page: int,
    end_page: int,
    page_rows: dict[int, dict[str, Any]],
    source: dict[str, Any],
    report: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_lines = _page_lines(page_rows, start_page, end_page)
    candidates = _question_candidates(page_rows, start_page, end_page)
    selected, missing = _select_question_starts(candidates)
    records: list[dict[str, Any]] = []
    selected_by_index = {item["index"]: item for item in selected}
    for position, start in enumerate(selected):
        next_start = (
            selected[position + 1]["index"] if position + 1 < len(selected) else None
        )
        lines = _block_lines(all_lines, start["index"], next_start)
        pages = sorted({item["page"] for item in lines})
        page_issues = _page_issue_set(report, pages)
        records.append(
            _record_from_block(
                subject=subject,
                number=start["number"],
                start=start,
                end_page=end_page,
                lines=lines,
                source=source,
                page_issues=page_issues,
            )
        )
    # Put boundary placeholders at the next available source page.  They are
    # deliberately empty: assigning neighboring OCR prose would fabricate a
    # question boundary.
    for number in missing:
        next_start = next((item for item in selected if item["number"] > number), None)
        page = next_start["page"] if next_start else end_page
        records.append(
            _placeholder_record(
                subject=subject,
                number=number,
                page=page,
                source=source,
            )
        )
    records.sort(key=lambda record: record["originalNumber"])
    summary = {
        "pages": [start_page, end_page],
        "candidateStarts": len(candidates),
        "parsedRecords": len(selected),
        "missingQuestionNumbers": missing,
        "numberMismatches": [
            {
                "question": item["number"],
                "ocrNumber": item["rawNumber"],
                "page": item["page"],
            }
            for item in selected
            if item.get("numberMismatch")
        ],
    }
    return records, summary


def _deduplicate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Report exact normalized duplicates without silently deleting variants."""

    seen: dict[tuple[str, str, str], str] = {}
    duplicates: list[dict[str, Any]] = []
    for record in records:
        fingerprint = (
            record["subject"],
            normalized(record.get("stem")),
            normalized(" ".join(choice.get("text", "") for choice in record["choices"])),
        )
        if not fingerprint[1] or not fingerprint[2]:
            continue
        prior = seen.get(fingerprint)
        if prior:
            record["issues"] = sorted(
                set(record["issues"] + ["duplicate_content_requires_review"])
            )
            duplicates.append(
                {"id": record["id"], "canonicalId": prior, "method": "identical_content"}
            )
        else:
            seen[fingerprint] = record["id"]
    return {"duplicates": duplicates, "fingerprints": len(seen)}


def parse_ocr_report(
    report: dict[str, Any],
    *,
    sections: Iterable[tuple[str, int, int]] = SECTION_RANGES,
) -> dict[str, Any]:
    if not isinstance(report, dict) or not isinstance(report.get("pages"), list):
        raise ValueError("OCR report must contain a pages list")
    if report.get("reviewStatus") != "needs_review":
        raise ValueError("OCR report is not marked needs_review")
    source = report.get("source")
    ocr = report.get("ocr")
    if not isinstance(source, dict) or not isinstance(ocr, dict):
        raise ValueError("OCR report is missing source or OCR metadata")
    required_ocr = {"engine", "version", "language", "dpi", "psm"}
    if not required_ocr.issubset(ocr):
        raise ValueError("OCR report is missing configuration metadata")
    page_rows = {int(row["page"]): row for row in report["pages"]}
    source_pages = int(source["pages"])
    if set(page_rows) != set(range(1, source_pages + 1)):
        raise ValueError("OCR report must contain exactly one row for every source page")
    source_metadata = {
        "filename": source["filename"],
        "sha256": source["sha256"],
        "ocr": ocr,
    }
    records: list[dict[str, Any]] = []
    section_reports: dict[str, Any] = {}
    for subject, start_page, end_page in sections:
        if start_page < 1 or end_page > source_pages or start_page > end_page:
            raise ValueError(f"Invalid section range for {subject}: {start_page}-{end_page}")
        parsed, section_report = _parse_section(
            subject=subject,
            start_page=start_page,
            end_page=end_page,
            page_rows=page_rows,
            source=source_metadata,
            report=report,
        )
        records.extend(parsed)
        section_reports[subject] = section_report
    dedup_report = _deduplicate(records)
    issue_counts = Counter(issue for record in records for issue in record["issues"])
    return {
        "parser": "ocr-question-candidates",
        "reviewStatus": "needs_review",
        "source": {
            **source,
            "ocr": ocr,
        },
        "sections": section_reports,
        "records": records,
        "report": {
            "total": len(records),
            "candidateRecords": sum(
                bool(record["rawText"]) for record in records
            ),
            "placeholders": sum(not record["rawText"] for record in records),
            "allNeedsReview": all(record["status"] == "needs_review" for record in records),
            "issues": dict(sorted(issue_counts.items())),
            **dedup_report,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build review-only Q&A candidates from OCR JSON")
    parser.add_argument("report", type=Path, help="OCR report produced by scripts/ocr_pdf.py")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".local/ocr-ple-qbank.json"),
        help="Draft JSON output path",
    )
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    output = parse_ocr_report(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "records": output["report"]["total"],
                "candidateRecords": output["report"]["candidateRecords"],
                "placeholders": output["report"]["placeholders"],
                "reviewStatus": output["reviewStatus"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

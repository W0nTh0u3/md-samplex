"""Coordinate-aware importer for the selectable MEDQBANK October 2025 PDF.

The source uses a ruled, two-column layout: questions and choices on the left,
answer headings and explanations on the right.  This adapter keeps that layout
boundary intact, assigns deterministic source-order numbers, and refuses to
infer answer keys that do not uniquely match a source choice.

Raster visuals from explanation cells are cropped from the original PDF and
registered as feedback-only assets.  Images in question cells are kept as
local review candidates and quarantine the dependent question until a reviewer
verifies an answer-neutral image and its alt text.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import fitz

try:  # Running as a package from the repository root.
    from .notion_import import has_multiple_indicator
except ImportError:  # Running scripts/extract.py directly.
    from notion_import import has_multiple_indicator  # type: ignore[no-redef]


def _repository_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    # The workspace is mounted from Windows with case-insensitive path aliases.
    # Prefer its lowercase writable alias when it resolves to the same directory.
    lowercase = Path(root.as_posix().lower())
    try:
        if lowercase.samefile(root):
            return lowercase
    except OSError:
        pass
    return root


ROOT = _repository_root()
DEFAULT_ASSET_DIR = ROOT / "public" / "assets" / "medqbank"
DEFAULT_CANDIDATE_DIR = ROOT / ".local" / "medqbank-visual-candidates"
DEFAULT_VISUAL_MANIFEST = ROOT / ".local" / "medqbank-visual-manifest.json"

SECTION_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("biochemistry", "Biochemistry", ("BIOCHEMISTRY",)),
    ("anatomy", "Anatomy", ("ANATOMY",)),
    ("microbiology", "Microbiology", ("MICROBIOLOGY",)),
    ("physiology", "Physiology", ("PHYSIOLOGY",)),
    ("legal-medicine", "Legal Medicine", ("LEGAL", "JURISPUDENCE")),
    ("pathology", "Pathology", ("PATHOLOGY",)),
    ("pharmacology", "Pharmacology", ("PHARMACOLOGY",)),
    ("surgery", "Surgery", ("SURGERY",)),
    ("internal-medicine", "Internal Medicine", ("INTERNAL",)),
    (
        "obstetrics-gynecology",
        "Obstetrics and Gynecology",
        ("OBSTETRICS", "GYNECOLOGY"),
    ),
    ("pediatrics", "Pediatrics", ("PEDIATRICS",)),
    ("preventive-medicine", "Preventive Medicine", ("PREVENTIVE",)),
)
SECTION_IDS = {item[0] for item in SECTION_DEFINITIONS}
SECTION_LABELS = {item[0]: item[1] for item in SECTION_DEFINITIONS}
SECTION_ALIASES = {
    alias: subject
    for subject, _label, aliases in SECTION_DEFINITIONS
    for alias in aliases
}
DATE_RE = re.compile(
    r"\b(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|"
    r"SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+20\d{2}\b",
    re.IGNORECASE,
)
QUESTION_OPTION_RE = re.compile(r"(?m)^[ \t]*([A-Ea-e])[ \t]*[.)][ \t]*")
VISUAL_REFERENCE_RE = re.compile(
    r"\b(?:figure|diagram|pictured|shown\s+(?:below|above|here)|"
    r"image\s+(?:below|above)|following\s+(?:graph|table|figure|image)|"
    r"table\s+(?:below|above))\b",
    re.IGNORECASE,
)
CONTINUATION_RE = re.compile(
    r"(?i)^(?:other\s+choices?|incorrect\s+choices?|"
    r"\(?(?:choice|option)\s+[A-E]\)?\b|"
    r"continued\b|cont['’]?d\b)"
)


def clean(text: str | None) -> str:
    """Normalize spacing while retaining source line breaks and wording."""

    value = (text or "").replace("\u00a0", " ").replace("\u200b", "")
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()).strip()


def _normalized_answer(text: str) -> str:
    value = unicodedata.normalize("NFKC", clean(text)).casefold()
    return re.sub(r"\s+", "", value)


def _subject_from_text(text: str) -> str | None:
    upper = unicodedata.normalize("NFKC", text).upper()
    # More specific aliases come first so an abbreviated cover title cannot
    # accidentally be attributed to another subject.
    ordered = sorted(
        SECTION_ALIASES.items(), key=lambda pair: len(pair[0]), reverse=True
    )
    for alias, subject in ordered:
        if re.search(rf"\b{re.escape(alias)}\b", upper):
            return subject
    return None


def _detect_cover_subject(page: fitz.Page) -> str | None:
    """Recognize the subject divider pages, which contain no question grid."""

    if len(page.get_text()) > 900:
        return None
    try:
        if _page_tables(page):
            return None
    except (RuntimeError, ValueError):
        return None
    text = page.get_text("text", clip=fitz.Rect(30, 80, page.rect.width - 30, 620))
    if DATE_RE.search(text):
        return None
    return _subject_from_text(text)


def _page_tables(page: fitz.Page):
    if not hasattr(page, "_medqbank_tables"):
        try:
            page._medqbank_tables = page.find_tables().tables
        except (RuntimeError, ValueError):
            page._medqbank_tables = []
    return page._medqbank_tables


def _detect_printed_heading(page: fitz.Page) -> tuple[str, str] | None:
    heading_text = page.get_text(
        "text", clip=fitz.Rect(35, 55, page.rect.width - 35, 110)
    )
    date_match = DATE_RE.search(heading_text)
    if not date_match:
        return None
    subject = _subject_from_text(heading_text)
    if not subject:
        return None
    date = re.sub(r"\s+", " ", date_match.group(0).title())
    return subject, date


def _main_table(page: fitz.Page):
    tables = _page_tables(page)
    candidates = []
    for table in tables:
        x0, y0, x1, y1 = table.bbox
        if x1 - x0 < page.rect.width * 0.68 or y1 - y0 < page.rect.height * 0.22:
            continue
        if table.row_count < 1:
            continue
        candidates.append(table)
    return max(candidates, key=lambda table: (table.bbox[2] - table.bbox[0]) * (table.bbox[3] - table.bbox[1])) if candidates else None


def _row_sides(table, row_index: int, split_x: float, extracted_rows=None) -> dict[str, Any]:
    values = (extracted_rows if extracted_rows is not None else table.extract())[row_index]
    cells = table.rows[row_index].cells
    sides: dict[str, Any] = {
        "left": [],
        "right": [],
        "leftRects": [],
        "rightRects": [],
    }
    for index, value in enumerate(values):
        if index >= len(cells) or cells[index] is None:
            continue
        rect = fitz.Rect(cells[index])
        side = "left" if (rect.x0 + rect.x1) / 2 < split_x else "right"
        sides[f"{side}Rects"].append(rect)
        if value:
            sides[side].append(clean(value))
    return {
        "left": clean("\n".join(sides["left"])),
        "right": clean("\n".join(sides["right"])),
        "leftRect": _union_rects(sides["leftRects"]),
        "rightRect": _union_rects(sides["rightRects"]),
    }


def _union_rects(rects: list[fitz.Rect]) -> fitz.Rect | None:
    if not rects:
        return None
    rect = fitz.Rect(rects[0])
    for other in rects[1:]:
        rect |= other
    return rect


def _cell_lines(page: fitz.Page, rect: fitz.Rect | None) -> list[dict[str, Any]]:
    if rect is None:
        return []
    lines = []
    for block in page.get_text("dict", clip=rect).get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = clean("".join(span.get("text", "") for span in line.get("spans", [])))
            if text:
                bbox = line.get("bbox", (0, 0, 0, 0))
                lines.append({"y0": float(bbox[1]), "y1": float(bbox[3]), "text": text})
    return sorted(lines, key=lambda line: (line["y0"], line["text"]))


def _paragraphs(page: fitz.Page, rect: fitz.Rect | None, gap: float = 22.0) -> list[str]:
    lines = _cell_lines(page, rect)
    groups: list[list[dict[str, Any]]] = []
    for line in lines:
        if not groups or line["y0"] - groups[-1][-1]["y0"] > gap:
            groups.append([line])
        else:
            groups[-1].append(line)
    return [clean("\n".join(line["text"] for line in group)) for group in groups]


def _labeled_options(text: str) -> tuple[str, list[tuple[str, str]]] | None:
    markers = list(QUESTION_OPTION_RE.finditer(text))
    if not markers:
        return None
    stem = clean(text[: markers[0].start()])
    choices = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        choices.append((marker.group(1).upper(), clean(text[marker.end() : end])))
    return stem, choices


def _right_answer_prefix(text: str, choices: list[tuple[str, str]]) -> dict[str, Any] | None:
    lines = [line.strip() for line in clean(text).splitlines() if line.strip()]
    if not lines or not choices:
        return None
    max_lines = min(12, len(lines))
    for line_count in range(1, max_lines + 1):
        prefix = clean("\n".join(lines[:line_count]))
        matches = [
            label
            for label, choice_text in choices
            if choice_text and _normalized_answer(choice_text) == _normalized_answer(prefix)
        ]
        if matches:
            return {
                "labels": matches,
                "heading": prefix,
                "explanation": clean("\n".join(lines[line_count:])),
                "ambiguous": len(matches) != 1,
            }
    return None


def _unlabeled_options(
    page: fitz.Page,
    left_rect: fitz.Rect | None,
    right_text: str,
) -> tuple[str, list[tuple[str, str]]] | None:
    groups = _paragraphs(page, left_rect)
    if len(groups) < 5:
        return None

    candidates: list[dict[str, Any]] = []
    # Prefer a paragraph ending in the printed question mark/colon followed by
    # exactly four or five visually separated option paragraphs.
    for stem_end in range(len(groups) - 1):
        if not re.search(r"[?:]\s*$", groups[stem_end]):
            continue
        option_count = len(groups) - stem_end - 1
        if option_count not in (4, 5):
            continue
        stem = clean("\n".join(groups[: stem_end + 1]))
        option_texts = groups[stem_end + 1 :]
        choices = [(chr(ord("A") + index), value) for index, value in enumerate(option_texts)]
        answer = _right_answer_prefix(right_text, choices)
        candidates.append(
            {
                "stem": stem,
                "choices": choices,
                "answerMatched": bool(answer and not answer["ambiguous"]),
            }
        )

    if not candidates:
        # The final four/five visual paragraphs are a safe fallback only when
        # the answer heading uniquely identifies an option.
        for option_count in (4, 5):
            if len(groups) <= option_count:
                continue
            choices = [
                (chr(ord("A") + index), value)
                for index, value in enumerate(groups[-option_count:])
            ]
            answer = _right_answer_prefix(right_text, choices)
            stem = clean("\n".join(groups[:-option_count]))
            if stem and answer and not answer["ambiguous"]:
                candidates.append(
                    {"stem": stem, "choices": choices, "answerMatched": True}
                )

    preferred = [candidate for candidate in candidates if candidate["answerMatched"]]
    selected = preferred if preferred else candidates
    # Multiple equally plausible segmentations are deliberately unresolved.
    unique = {
        (
            _normalized_answer(candidate["stem"]),
            tuple(_normalized_answer(choice) for _label, choice in candidate["choices"]),
        ): candidate
        for candidate in selected
    }
    if len(unique) != 1:
        return None
    result = next(iter(unique.values()))
    if len(result["stem"]) < 8 or any(not text for _label, text in result["choices"]):
        return None
    return result["stem"], result["choices"]


def _record_choices(record: dict[str, Any]) -> list[tuple[str, str]]:
    return list(record.get("_choiceMap", []))


def _record_is_complete(record: dict[str, Any]) -> bool:
    labels = [label for label, _text in _record_choices(record)]
    return labels in (["A", "B", "C", "D"], ["A", "B", "C", "D", "E"])


def _next_labels(record: dict[str, Any]) -> list[str]:
    labels = [label for label, _text in _record_choices(record)]
    return list("ABCDE")[len(labels) :]


def _new_record(
    subject: str,
    number: int,
    filename: str,
    page_number: int,
    printed_date: str,
) -> dict[str, Any]:
    record = {
        "id": f"medqbank-{subject}-{number:04d}",
        "subject": subject,
        "originalNumber": number,
        "stem": "",
        "choices": [],
        "correctChoice": None,
        "explanation": "",
        "sources": [
            {
                "filename": filename,
                "pages": [page_number],
                "answerPages": [],
                "metadata": {
                    "sectionTitle": SECTION_LABELS[subject],
                    "sectionDate": printed_date,
                },
            }
        ],
        "status": "needs_review",
        "issues": [],
        "_raw": "",
        "_namespace": "medqbank",
        "_choiceMap": [],
        "_answerBlocks": [],
        "_questionVisuals": [],
        "_feedbackVisuals": [],
    }
    return record


def _add_source_page(record: dict[str, Any], filename: str, page_number: int, *, answer: bool = False) -> None:
    source = next((item for item in record["sources"] if item["filename"] == filename), None)
    if source is None:
        source = {
            "filename": filename,
            "pages": [],
            "answerPages": [],
            "metadata": {},
        }
        record["sources"].append(source)
    field = "answerPages" if answer else "pages"
    source[field] = sorted(set(source[field] + [page_number]))


def _write_question_text(
    record: dict[str, Any],
    stem: str,
    choices: list[tuple[str, str]],
    *,
    synthesized_labels: bool = False,
    continuation: bool = False,
) -> None:
    if stem:
        if record["_raw"]:
            record["_raw"] = clean(record["_raw"] + "\n" + stem)
        else:
            record["_raw"] = stem
    existing = _record_choices(record)
    next_index = len(existing)
    for offset, (label, text) in enumerate(choices):
        label = label.upper()
        if synthesized_labels:
            label = chr(ord("A") + next_index + offset)
        elif continuation:
            expected = list("ABCDE")[next_index + offset : next_index + offset + 1]
            if not expected or label != expected[0]:
                record["issues"].append("option_sequence_requires_review")
        record["_choiceMap"].append((label, clean(text)))
        if record["_raw"]:
            record["_raw"] += "\n"
        record["_raw"] += f"{label}. {clean(text)}"
    if _record_is_complete(record):
        record["issues"] = [
            issue
            for issue in record["issues"]
            if issue != "question_options_unresolved"
        ]
    if synthesized_labels:
        record["sources"][0]["metadata"]["choiceLabelsSynthesized"] = True


def _has_question_shape(text: str) -> bool:
    cleaned = clean(text)
    if not cleaned:
        return False
    return bool(
        re.search(r"[?]\s*$", cleaned)
        or re.search(r"(?i)^(?:which|what|who|when|where|why|how|a\s+\d+|an?\s+\d+|during|in\s+the|under\s+the|the\s+following)\b", cleaned)
    )


def _can_continue(record: dict[str, Any], labels: list[str]) -> bool:
    if not record or _record_is_complete(record):
        return False
    expected = _next_labels(record)
    return bool(labels) and labels == expected[: len(labels)]


def _process_question_cell(
    *,
    subject: str,
    printed_date: str,
    filename: str,
    page_number: int,
    page: fitz.Page,
    left_text: str,
    left_rect: fitz.Rect | None,
    right_text: str,
    active: dict[str, Any] | None,
    counters: dict[str, int],
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Append this row's left cell to a record; return (record, issue)."""

    if not left_text:
        return None, None
    parsed = _labeled_options(left_text)
    if parsed:
        stem, choices = parsed
        labels = [label for label, _text in choices]
        should_continue = bool(
            active
            and not stem
            and _can_continue(active, labels)
        )
        if should_continue:
            _write_question_text(active, "", choices, continuation=True)
            _add_source_page(active, filename, page_number)
            return active, None

        counters[subject] += 1
        record = _new_record(
            subject, counters[subject], filename, page_number, printed_date
        )
        _write_question_text(record, stem, choices)
        if not stem:
            record["issues"].append("incomplete_stem")
        records.append(record)
        return record, None

    options = _unlabeled_options(page, left_rect, right_text)
    if options:
        stem, choices = options
        counters[subject] += 1
        record = _new_record(
            subject, counters[subject], filename, page_number, printed_date
        )
        _write_question_text(record, stem, choices, synthesized_labels=True)
        records.append(record)
        return record, None

    # A question stem can end a page with its options on the next page. Keep it
    # as a candidate so the next A–E row can complete it; it remains excluded
    # if the continuation never arrives.
    if active and not _record_is_complete(active) and not _has_question_shape(left_text):
        active["_raw"] = clean(active["_raw"] + "\n" + left_text)
        _add_source_page(active, filename, page_number)
        return active, None

    counters[subject] += 1
    record = _new_record(subject, counters[subject], filename, page_number, printed_date)
    record["_raw"] = clean(left_text)
    record["issues"].append("question_options_unresolved")
    if active and not _record_is_complete(active):
        active["issues"].append("page_continuation_boundary_requires_review")
    records.append(record)
    return record, {"reason": "question_options_unresolved", "page": page_number}


def _resolve_answer(record: dict[str, Any]) -> None:
    choices = _record_choices(record)
    if not record.get("_answerBlocks"):
        return
    answer_blocks = record["_answerBlocks"]
    if not _record_is_complete(record):
        return

    for index, block in enumerate(answer_blocks):
        parsed = _right_answer_prefix(block["text"], choices)
        if not parsed:
            continue
        if parsed["ambiguous"]:
            record["issues"].append("ambiguous_answer_text_matches_multiple_choices")
            record["correctChoice"] = None
            record["explanation"] = clean(
                "\n".join(item["text"] for item in answer_blocks)
            )
            return
        question_prose = record["_raw"].split("\n", 1)[0]
        if has_multiple_indicator(question_prose):
            record["issues"].append("multiple_response_requires_review")
            record["correctChoice"] = None
            record["explanation"] = clean(
                "\n".join(item["text"] for item in answer_blocks)
            )
            return
        record["correctChoice"] = parsed["labels"][0]
        explanation_parts = [item["text"] for item in answer_blocks[:index]]
        explanation_parts.append(parsed["explanation"])
        explanation_parts.extend(item["text"] for item in answer_blocks[index + 1 :])
        record["explanation"] = clean("\n".join(part for part in explanation_parts if part))
        return

    record["correctChoice"] = None
    record["explanation"] = clean("\n".join(item["text"] for item in answer_blocks))
    record["issues"].append("answer_text_did_not_match_unique_choice")


def _add_answer_block(record: dict[str, Any], filename: str, page_number: int, text: str) -> None:
    _add_source_page(record, filename, page_number, answer=True)
    if text:
        record["_answerBlocks"].append({"text": clean(text), "page": page_number})
    _resolve_answer(record)


def _candidate_right_target(
    current: dict[str, Any] | None,
    active: dict[str, Any] | None,
    right_text: str,
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if current:
        current_match = _right_answer_prefix(right_text, _record_choices(current))
        if current_match or not _record_is_complete(current):
            # The ruled row is the primary pairing signal. Keep an ambiguous
            # duplicate choice on this row for explicit review instead of
            # pairing it to an earlier question that happens to repeat text.
            return current, []

    matches = []
    for record in records[-12:]:
        if record is current or record.get("_answerBlocks"):
            continue
        parsed = _right_answer_prefix(right_text, _record_choices(record))
        if parsed and not parsed["ambiguous"]:
            matches.append(record)
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, matches
    if current:
        return current, []
    if active and (not _record_is_complete(active) or active.get("correctChoice") is None):
        return active, []
    if active and CONTINUATION_RE.search(clean(right_text)):
        return active, []
    return active, []


def _image_context(page: fitz.Page, rect: fitz.Rect, image_bbox: fitz.Rect) -> tuple[str, str]:
    lines = _cell_lines(page, rect)
    preceding = [
        line
        for line in lines
        if line["y1"] <= image_bbox.y0 + 1 and image_bbox.y0 - line["y1"] <= 70
    ]
    context = preceding[-1]["text"] if preceding else ""
    if not context:
        following = [line for line in lines if line["y0"] >= image_bbox.y1 - 1]
        context = following[0]["text"] if following else ""
    kind = "image"
    if re.search(r"\btable\b", context, re.IGNORECASE):
        kind = "table"
    elif re.search(r"\b(?:diagram|figure|graph|illustration)\b", context, re.IGNORECASE):
        kind = "diagram"
    description = clean(context).replace("\n", " ")[:180]
    return kind, description


def _save_crop(page: fitz.Page, bbox: fitz.Rect, destination: Path) -> tuple[str, int, int]:
    clip = fitz.Rect(bbox)
    clip.x0 -= 1.5
    clip.y0 -= 1.5
    clip.x1 += 1.5
    clip.y1 += 1.5
    clip &= page.rect
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), clip=clip, alpha=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    png_bytes = pixmap.tobytes("png")
    digest = hashlib.sha256(png_bytes).hexdigest()
    destination = destination.parent / f"{digest}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f".{destination.stem}.tmp.png")
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == digest:
        pass
    else:
        temp_path.write_bytes(png_bytes)
        temp_path.replace(destination)
    return digest, pixmap.width, pixmap.height


def _save_visuals_for_row(
    *,
    page: fitz.Page,
    page_number: int,
    filename: str,
    row: dict[str, Any],
    question_record: dict[str, Any] | None,
    right_record: dict[str, Any] | None,
    asset_dir: Path,
    candidate_dir: Path,
    manifest: dict[str, Any],
    report: dict[str, Any],
    image_index: dict[int, list[dict[str, Any]]],
) -> None:
    for side, rect_key, target in (
        ("left", "leftRect", question_record or right_record),
        ("right", "rightRect", right_record or question_record),
    ):
        cell_rect = row.get(rect_key)
        if cell_rect is None:
            continue
        for image in image_index.get(page_number, []):
            bbox = image["bbox"]
            intersection = fitz.Rect(cell_rect) & bbox
            if intersection.is_empty or intersection.get_area() < bbox.get_area() * 0.8:
                continue
            if target is None:
                continue
            if image.get("assigned"):
                continue
            image["assigned"] = True
            target_id = target["id"]
            if side == "left":
                _add_source_page(target, filename, page_number)
                target["issues"].append("source_visual_requires_review")
                visual_id = hashlib.sha256(
                    f"{target_id}:{filename}:{page_number}:{image['index']}".encode()
                ).hexdigest()[:20]
                candidate_path = candidate_dir / f"{visual_id}.png"
                digest, width, height = _save_crop(page, bbox, candidate_path)
                candidate_path = candidate_dir / f"{digest}.png"
                candidate = {
                    "questionId": target_id,
                    "page": page_number,
                    "path": str(candidate_path),
                    "sha256": digest,
                    "width": width,
                    "height": height,
                    "status": "needs_review",
                    "reason": "Question-cell visual needs answer-neutrality and alt-text review.",
                }
                target["_questionVisuals"].append(candidate)
                report["questionVisualCandidates"].append(candidate)
                continue

            _add_source_page(target, filename, page_number, answer=True)
            kind, _context = _image_context(page, cell_rect, bbox)
            visual_id = (
                f"medqbank-october2025-{target['subject']}-{target['originalNumber']:04d}"
                f"-p{page_number:03d}-i{image['index']:02d}"
            )
            asset_path = asset_dir / f"{visual_id}.png"
            digest, width, height = _save_crop(page, bbox, asset_path)
            asset_path = asset_dir / f"{digest}.png"
            public_path = "/assets/medqbank/" + digest + ".png"
            alt = (
                f"MEDQBANK source {kind} for the explanation of "
                f"{SECTION_LABELS[target['subject']]} item {target['originalNumber']} "
                f"(PDF page {page_number})."
            )
            caption = f"MEDQBANK source page {page_number}; shown after answer checking."
            source_locator = f"{filename} page {page_number}"
            manifest["assets"].append(
                {
                    "id": visual_id,
                    "path": public_path,
                    "localPath": str(asset_path),
                    "sha256": digest,
                    "kind": kind,
                    "alt": alt,
                    "caption": caption,
                    "visibility": "feedback",
                    "source": {"filename": filename, "pages": [page_number]},
                }
            )
            question_entry = next(
                (
                    entry
                    for entry in manifest["questions"]
                    if entry["questionId"] == target_id
                ),
                None,
            )
            if question_entry is None:
                question_entry = {
                    "questionId": target_id,
                    "visualIds": [],
                    # These explanation visuals are optional and feedback-only;
                    # none is required to understand the unanswered question.
                    "requiredVisualIds": [],
                    "verified": True,
                    "reviewNote": "Automated source-row pairing; feedback-only raster crop.",
                }
                manifest["questions"].append(question_entry)
            question_entry["visualIds"].append(visual_id)
            visual = {
                "id": visual_id,
                "path": public_path,
                "sha256": digest,
                "kind": kind,
                "alt": alt,
                "caption": caption,
                "visibility": "feedback",
                "sourceLocator": source_locator,
                "width": width,
                "height": height,
            }
            target["_feedbackVisuals"].append(visual)
            report["feedbackVisuals"].append({"questionId": target_id, **visual})


def _inventory_images(doc: fitz.Document) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for page_index, page in enumerate(doc):
        seen_bboxes: set[tuple[float, float, float, float]] = set()
        for image_index, image in enumerate(page.get_image_info()):
            bbox = fitz.Rect(image["bbox"])
            # Ignore tiny repeated decorations and footnote icons. The source's
            # clinical tables, graphs, and diagrams are substantially larger.
            if (
                image.get("width", 0) < 80
                or image.get("height", 0) < 50
                or bbox.width < 20
                or bbox.height < 18
            ):
                continue
            # Some source pages stack identical image placements. The final
            # rendered crop is the same composite region, so report it once.
            bbox_key = tuple(round(value, 2) for value in bbox)
            if bbox_key in seen_bboxes:
                continue
            seen_bboxes.add(bbox_key)
            result[page_index + 1].append(
                {"index": image_index + 1, "bbox": bbox, "assigned": False}
            )
    return result


def parse_medqbank(
    path: str | Path,
    *,
    asset_dir: str | Path = DEFAULT_ASSET_DIR,
    candidate_dir: str | Path = DEFAULT_CANDIDATE_DIR,
    visual_manifest_path: str | Path = DEFAULT_VISUAL_MANIFEST,
) -> tuple[list[dict[str, Any]], dict[str, Any], Path]:
    """Parse the MEDQBANK PDF and produce a generated visual manifest.

    Explanation visuals are materialized under ``public/assets/medqbank`` and
    entered in a hash-checked feedback-only manifest. Question-cell visuals are
    kept under ``.local`` for review and make their records ineligible.
    """

    source_path = Path(path)
    if not source_path.is_file():
        raise ValueError(f"MEDQBANK parser expects a PDF file: {source_path}")
    asset_root = Path(asset_dir)
    candidate_root = Path(candidate_dir)
    manifest_path = Path(visual_manifest_path)
    source_data = source_path.read_bytes()
    source_digest = hashlib.sha256(source_data).hexdigest()
    doc = fitz.open(source_path)
    images = _inventory_images(doc)
    counters: dict[str, int] = defaultdict(int)
    records: list[dict[str, Any]] = []
    active_by_subject: dict[str, dict[str, Any] | None] = defaultdict(lambda: None)
    current_subject: str | None = None
    printed_dates: dict[str, str] = {}
    sections = {
        subject: {
            "title": label,
            "dividerPage": None,
            "printedDate": None,
            "firstQuestionPage": None,
            "lastQuestionPage": None,
            "records": 0,
        }
        for subject, label, _aliases in SECTION_DEFINITIONS
    }
    report: dict[str, Any] = {
        "filename": source_path.name,
        "sha256": source_digest,
        "pages": len(doc),
        "sections": sections,
        "tablePages": 0,
        "questionRows": 0,
        "continuationRows": 0,
        "visualOnlyRows": [],
        "unrecognizedPages": [],
        "unparsedRows": [],
        "questionVisualCandidates": [],
        "feedbackVisuals": [],
        "unassignedVisuals": [],
        "issues": {},
    }
    generated_manifest: dict[str, Any] = {
        "version": 1,
        "description": "Generated, hash-checked MEDQBANK feedback-only explanation crops.",
        "assets": [],
        "questions": [],
        "sharedCases": [],
    }

    for page_index, page in enumerate(doc):
        page_number = page_index + 1
        if images.get(page_number) and _main_table(page) is None:
            report["visualOnlyRows"].append(
                {"page": page_number, "reason": "visual_page_without_question_table"}
            )
        cover_subject = _detect_cover_subject(page)
        if cover_subject:
            current_subject = cover_subject
            sections[cover_subject]["dividerPage"] = page_number

        heading = _detect_printed_heading(page)
        if heading:
            current_subject, section_date = heading
            printed_dates[current_subject] = section_date
            sections[current_subject]["printedDate"] = section_date

        table = _main_table(page)
        if table is None:
            continue
        report["tablePages"] += 1
        if not current_subject or current_subject not in SECTION_IDS:
            report["unrecognizedPages"].append(page_number)
            continue
        section_date = printed_dates.get(current_subject)
        if not section_date:
            report["unparsedRows"].append(
                {"page": page_number, "reason": "missing_printed_section_date", "subject": current_subject}
            )
            section_date = "Unknown"

        active = active_by_subject[current_subject]
        split_x = page.rect.width * (256.5 / 595.4)
        extracted_rows = table.extract()
        for row_index in range(table.row_count):
            row = _row_sides(table, row_index, split_x, extracted_rows)
            left_text = row["left"]
            right_text = row["right"]
            combined = clean(left_text + "\n" + right_text)
            if not combined:
                continue

            # The first bordered row on each section is a printed title/date.
            if DATE_RE.search(combined) and not QUESTION_OPTION_RE.search(left_text):
                continue

            record_count_before = len(records)
            record, parse_issue = _process_question_cell(
                subject=current_subject,
                printed_date=section_date,
                filename=source_path.name,
                page_number=page_number,
                page=page,
                left_text=left_text,
                left_rect=row["leftRect"],
                right_text=right_text,
                active=active,
                counters=counters,
                records=records,
            )
            if record:
                active = record
                active_by_subject[current_subject] = record
                is_new_record = len(records) > record_count_before
                if is_new_record:
                    sections[current_subject]["records"] += 1
                    if sections[current_subject]["firstQuestionPage"] is None:
                        sections[current_subject]["firstQuestionPage"] = page_number
                    report["questionRows"] += 1
                elif left_text:
                    report["continuationRows"] += 1
                sections[current_subject]["lastQuestionPage"] = page_number
                if parse_issue:
                    report["unparsedRows"].append(
                        {"questionId": record["id"], **parse_issue}
                    )
            elif left_text:
                report["continuationRows"] += 1

            right_target, ambiguous_targets = _candidate_right_target(
                record, active, right_text, records
            ) if right_text else (record or active, [])
            if ambiguous_targets:
                for candidate in ambiguous_targets:
                    candidate["issues"].append("ambiguous_answer_pairing_requires_review")
                if record:
                    record["issues"].append("ambiguous_answer_pairing_requires_review")
                right_target = None
            if right_text and right_target:
                _add_answer_block(right_target, source_path.name, page_number, right_text)
                if right_target["subject"] == current_subject:
                    active = right_target
                    active_by_subject[current_subject] = right_target

            _save_visuals_for_row(
                page=page,
                page_number=page_number,
                filename=source_path.name,
                row=row,
                question_record=record,
                right_record=right_target,
                asset_dir=asset_root,
                candidate_dir=candidate_root,
                manifest=generated_manifest,
                report=report,
                image_index=images,
            )
        if page_number % 25 == 0:
            print(f"{source_path.name}: {page_number}/{len(doc)} pages", flush=True)

    # Give every source question a visual-free text representation, retaining
    # uncertain answer blocks as explanation text for human review.
    for record in records:
        _resolve_answer(record)
        if record["_questionVisuals"]:
            record["issues"].append("source_visual_requires_review")
        if VISUAL_REFERENCE_RE.search(record.get("_raw", "")) and not record["_questionVisuals"]:
            record["issues"].append("required_figure_or_table_requires_review")
        record["issues"] = sorted(set(record["issues"]))
        for key in ("_choiceMap", "_answerBlocks", "_questionVisuals", "_feedbackVisuals"):
            record.pop(key, None)

    issue_counts = Counter(issue for record in records for issue in record["issues"])
    for page_number, page_images in images.items():
        for image in page_images:
            if not image["assigned"]:
                entry = {
                    "page": page_number,
                    "bbox": [round(value, 2) for value in image["bbox"]],
                    "reason": "visual_not_associated_with_a_question_cell",
                }
                report["unassignedVisuals"].append(entry)
    report["issues"] = dict(sorted(issue_counts.items()))
    unresolved_ids = {
        record["id"]
        for record in records
        if "question_options_unresolved" in record["issues"]
    }
    report["unparsedRows"] = [
        entry
        for entry in report["unparsedRows"]
        if not entry.get("questionId") or entry.get("questionId") in unresolved_ids
    ]
    report["records"] = len(records)
    report["sectionsFound"] = sum(bool(section["printedDate"]) for section in sections.values())
    report["sectionRecordCounts"] = {
        subject: counters.get(subject, 0) for subject, _label, _aliases in SECTION_DEFINITIONS
    }
    report["feedbackVisualCount"] = len(generated_manifest["assets"])
    report["questionVisualCandidateCount"] = len(report["questionVisualCandidates"])

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_manifest = manifest_path.with_name(f".{manifest_path.name}.tmp")
    temp_manifest.write_text(
        json.dumps(generated_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_manifest.replace(manifest_path)
    doc.close()
    return records, report, manifest_path


if __name__ == "__main__":  # A quick local draft report; canonical publishing uses extract.py.
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="?", default="raw pdfs/MEDQBANK-OCTOBER2025.pdf")
    args = parser.parse_args()
    source_records, source_report, source_manifest = parse_medqbank(args.pdf)
    print(
        json.dumps(
            {
                "filename": source_report["filename"],
                "pages": source_report["pages"],
                "sectionsFound": source_report["sectionsFound"],
                "sectionRecordCounts": source_report["sectionRecordCounts"],
                "records": source_report["records"],
                "issues": source_report["issues"],
                "feedbackVisualCount": source_report["feedbackVisualCount"],
                "questionVisualCandidateCount": source_report["questionVisualCandidateCount"],
                "visualManifest": str(source_manifest),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

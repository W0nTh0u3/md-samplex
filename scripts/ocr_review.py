"""Create review-only explanation images and audit OCR Q&A boundaries.

The scanned PLE PDF is a three-column source table.  OCR is useful for finding
question boundaries and answer cells, but it is a poor representation of
explanation tables.  This script keeps the OCR text for auditability and adds
feedback-only crops rendered directly from the source PDF.

The generated assets intentionally live outside ``public/assets``.  They are
unverified review evidence, not canonical bank visuals.  A reviewer can later
promote a selected crop through ``scripts/visual-manifest.json`` after
checking its content and writing an accurate alt description.

The source audit is structural: it checks the source hash, page locators,
question-number boundaries, option labels/text, and answer-column key pairing.
It does not certify the clinical correctness or currency of the historical
material.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import fitz

try:  # Running from the repository root (tests and module imports).
    from scripts.ocr_import import (
        SECTION_RANGES,
        _answer_marker,
        _block_lines,
        _extract_choices,
        _ocr_configuration_groups,
        _option_markers,
        _ordered_sequences,
        _page_lines,
        _question_candidates,
        _select_question_starts,
        _sequence_score,
        clean,
        normalized,
    )
except ModuleNotFoundError:  # Running as ``python scripts/ocr_review.py``.
    from ocr_import import (  # type: ignore[no-redef]
        SECTION_RANGES,
        _answer_marker,
        _block_lines,
        _extract_choices,
        _ocr_configuration_groups,
        _option_markers,
        _ordered_sequences,
        _page_lines,
        _question_candidates,
        _select_question_starts,
        _sequence_score,
        clean,
        normalized,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PDF = ROOT / "raw pdfs" / "821551629-Ple-Test-Bank-compressed.pdf"
DEFAULT_REPORT = ROOT / ".local" / "ocr-ple-layout-full.json"
DEFAULT_QBANK = ROOT / ".local" / "ocr-ple-qbank.json"
DEFAULT_ASSET_DIR = ROOT / ".local" / "ocr-ple-explanation-assets"
DEFAULT_MANIFEST = ROOT / ".local" / "ocr-ple-explanation-manifest.json"
DEFAULT_AUDIT = ROOT / ".local" / "ocr-ple-source-audit.json"

def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Unable to read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object at {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _line_bbox(line: dict[str, Any], *, split_x: int | float | None = None) -> tuple[float, float, float, float] | None:
    words = line.get("words")
    if not isinstance(words, list):
        return None
    filtered = []
    for word in words:
        if not isinstance(word, dict):
            continue
        try:
            left = float(word["left"])
            top = float(word["top"])
            width = float(word["width"])
            height = float(word["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if split_x is not None and left < float(split_x):
            continue
        filtered.append((left, top, left + max(0.0, width), top + max(0.0, height)))
    if not filtered:
        return None
    return (
        min(item[0] for item in filtered),
        min(item[1] for item in filtered),
        max(item[2] for item in filtered),
        max(item[3] for item in filtered),
    )


def _line_top(line: dict[str, Any]) -> float | None:
    bbox = _line_bbox(line)
    if bbox:
        return bbox[1]
    value = line.get("top")
    return float(value) if isinstance(value, (int, float)) else None


def _ocr_config(line: dict[str, Any], page_row: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    for value in (line.get("ocr"), page_row.get("ocr"), report.get("ocr")):
        if isinstance(value, dict):
            return value
    return {}


def _split_x(line: dict[str, Any], page_row: dict[str, Any], report: dict[str, Any]) -> int:
    for value in (
        line.get("columnSplitX"),
        (page_row.get("layout") or {}).get("columnSplitX"),
        page_row.get("ocr", {}).get("columnSplitX")
        if isinstance(page_row.get("ocr"), dict)
        else None,
        report.get("ocr", {}).get("columnSplitX")
        if isinstance(report.get("ocr"), dict)
        else None,
    ):
        if isinstance(value, (int, float)):
            return int(value)
    return 1130


def _build_contexts(report: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Reconstruct the importer's physical blocks, including their line data."""

    page_rows = {int(row["page"]): row for row in report.get("pages", [])}
    contexts: dict[str, dict[str, Any]] = {}
    expected_ids: set[str] = set()
    for subject, start_page, end_page in SECTION_RANGES:
        all_lines = _page_lines(page_rows, start_page, end_page)
        candidates = _question_candidates(page_rows, start_page, end_page)
        selected, missing = _select_question_starts(candidates)
        for position, start in enumerate(selected):
            next_start = (
                selected[position + 1]["index"]
                if position + 1 < len(selected)
                else None
            )
            block = _block_lines(all_lines, start["index"], next_start)
            record_id = f"ocr-ple-{subject}-{start['number']:04d}"
            expected_ids.add(record_id)
            markers = _option_markers(block)
            sequences = _ordered_sequences(markers)
            sequence = max(sequences, key=_sequence_score) if sequences else []
            option_start = (
                (sequence[0]["line"], sequence[0]["char"])
                if sequence
                else None
            )
            answer = _answer_marker(block, markers, option_start)
            contexts[record_id] = {
                "id": record_id,
                "subject": subject,
                "number": start["number"],
                "start": start,
                "nextStart": all_lines[next_start] if next_start is not None else None,
                "lines": block,
                "pages": sorted({line["page"] for line in block}),
                "choices": _extract_choices(block, sequence) if sequence else [],
                "answer": answer,
                "pageRows": page_rows,
                "report": report,
                "ocrConfigurations": _ocr_configuration_groups(
                    block,
                    {
                        "ocr": report["ocr"],
                    },
                ),
            }
        for number in missing:
            record_id = f"ocr-ple-{subject}-{number:04d}"
            expected_ids.add(record_id)
            contexts[record_id] = {
                "id": record_id,
                "subject": subject,
                "number": number,
                "placeholder": True,
                "pages": [],
                "pageRows": page_rows,
                "report": report,
            }
    return contexts, expected_ids


def _source_pages(record: dict[str, Any]) -> list[int]:
    values: list[int] = []
    for source in record.get("sources", []):
        if not isinstance(source, dict):
            continue
        pages = source.get("pages")
        if isinstance(pages, list):
            values.extend(page for page in pages if isinstance(page, int))
    return sorted(set(values))


def _stored_choices(record: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"label": str(choice.get("label", "")), "text": clean(choice.get("text", ""))}
        for choice in record.get("choices", [])
        if isinstance(choice, dict)
    ]


def _audit_candidate(record: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    expected_pages = context.get("pages", [])
    stored_pages = _source_pages(record)
    source_answer = context.get("answer")
    source_choices = context.get("choices", [])
    stored_choices = _stored_choices(record)
    stored_mode = record.get("answerMode", "single")
    stored_answer = record.get("correctChoice")
    choice_labels = [choice.get("label") for choice in source_choices]
    choice_set_complete = choice_labels in (
        ["A", "B", "C", "D"],
        ["A", "B", "C", "D", "E"],
    ) and all(clean(choice.get("text")) for choice in source_choices)
    checks = {
        "questionNumber": record.get("originalNumber") == context.get("number"),
        "rawQuestionNumber": record.get("rawQuestionNumber")
        == context["start"].get("rawNumber"),
        "sourcePages": stored_pages == expected_pages,
        "questionBlock": bool(clean(record.get("rawText", ""))),
        "choiceLabels": [choice.get("label") for choice in stored_choices]
        == [choice.get("label") for choice in source_choices],
        "choiceText": [normalized(choice.get("text")) for choice in stored_choices]
        == [normalized(choice.get("text")) for choice in source_choices],
        "choiceSetComplete": choice_set_complete,
    }
    if source_answer is None:
        checks["answerColumnKey"] = False
        checks["storedAnswer"] = False
        checks["answerKeyPairing"] = False
    elif stored_mode == "multiple" or record.get("correctChoices") is not None:
        checks["answerColumnKey"] = False
        checks["storedAnswer"] = False
        checks["answerKeyPairing"] = False
    else:
        checks["answerColumnKey"] = source_answer.get("key") in {
            "A",
            "B",
            "C",
            "D",
            "E",
        }
        checks["storedAnswer"] = stored_answer in {"A", "B", "C", "D", "E"}
        checks["answerKeyPairing"] = stored_answer == source_answer.get("key")

    mismatch_reasons = []
    if not checks["questionNumber"] or not checks["rawQuestionNumber"]:
        mismatch_reasons.append("source_question_boundary_mismatch_requires_review")
    if not checks["sourcePages"]:
        mismatch_reasons.append("source_page_locator_mismatch_requires_review")
    if not checks["choiceLabels"] or not checks["choiceText"]:
        mismatch_reasons.append("source_choices_mismatch_requires_review")
    if not checks["answerKeyPairing"] and source_answer is not None:
        mismatch_reasons.append("source_answer_key_mismatch_requires_review")

    unresolved_reasons = []
    if source_answer is None:
        unresolved_reasons.append("source_answer_key_unresolved_requires_review")
    if not checks["choiceSetComplete"]:
        unresolved_reasons.append("source_choice_set_incomplete_requires_review")
    if not clean(record.get("stem", "")) or len(clean(record.get("stem", ""))) < 15:
        checks["stemComplete"] = False
        unresolved_reasons.append("source_stem_incomplete_requires_review")
    else:
        checks["stemComplete"] = True

    if mismatch_reasons:
        status = "mismatch"
    elif unresolved_reasons or not all(checks.values()):
        status = "needs_review"
    else:
        status = "structurally_consistent"

    return {
        "status": status,
        "sourceQuestionNumber": context.get("number"),
        "sourceRawQuestionNumber": context.get("start", {}).get("rawNumber"),
        "sourcePages": expected_pages,
        "storedPages": stored_pages,
        "sourceAnswerKey": source_answer.get("key") if source_answer else None,
        "storedAnswerKey": stored_answer,
        "checks": checks,
        "issues": sorted(set(mismatch_reasons + unresolved_reasons)),
    }


def _audit_placeholder(record: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "needs_review",
        "sourceQuestionNumber": context["number"],
        "sourceRawQuestionNumber": None,
        "sourcePages": _source_pages(record),
        "storedPages": _source_pages(record),
        "sourceAnswerKey": None,
        "storedAnswerKey": None,
        "checks": {
            "questionNumber": record.get("originalNumber") == context["number"],
            "questionBlock": False,
            "sourcePageLocator": bool(_source_pages(record)),
            "answerColumnKey": False,
        },
        "issues": ["missing_ocr_question_boundary"],
    }


def _table_like(page: fitz.Page, clip: fitz.Rect) -> bool:
    """Conservatively identify vector table rules without trusting OCR text."""

    horizontal = 0
    vertical = 0
    try:
        drawings = page.get_drawings()
    except Exception:  # pragma: no cover - defensive for unusual PDF pages.
        return False
    for drawing in drawings:
        rect = drawing.get("rect")
        if not rect or not (fitz.Rect(rect) & clip):
            continue
        for item in drawing.get("items", []):
            if not item or item[0] != "l" or len(item) < 3:
                continue
            start, end = item[1], item[2]
            if abs(start.y - end.y) > 3 and abs(start.x - end.x) < 3:
                vertical += 1
            elif abs(start.x - end.x) > 15 and abs(start.y - end.y) < 3:
                horizontal += 1
    return horizontal >= 2 and vertical >= 2


def _crop_bounds(
    page: fitz.Page,
    context: dict[str, Any],
    page_number: int,
) -> tuple[fitz.Rect, dict[str, Any]]:
    page_rows = context["pageRows"]
    report = context["report"]
    lines = [line for line in context["lines"] if line["page"] == page_number]
    first_line = lines[0] if lines else context["lines"][0]
    split_x = _split_x(first_line, page_rows[page_number], report)
    config = _ocr_config(first_line, page_rows[page_number], report)
    try:
        ocr_dpi = int(config.get("dpi", report.get("ocr", {}).get("dpi", 300)))
    except (TypeError, ValueError):
        ocr_dpi = 300
    if ocr_dpi < 72:
        ocr_dpi = 300
    px_per_point = ocr_dpi / 72.0
    page_width_px = page.rect.width * px_per_point
    page_height_px = page.rect.height * px_per_point

    right_boxes = []
    all_boxes = []
    has_right_text = False
    for line in lines:
        if clean(line.get("rightText", "")):
            has_right_text = True
        all_box = _line_bbox(line)
        right_box = _line_bbox(line, split_x=split_x)
        if all_box:
            all_boxes.append(all_box)
        if right_box:
            right_boxes.append(right_box)
    content_boxes = right_boxes or all_boxes
    top_px = min(box[1] for box in content_boxes) if content_boxes else 0
    bottom_px = max(box[3] for box in content_boxes) if content_boxes else page_height_px

    next_line = context.get("nextStart")
    next_top = (
        _line_top(next_line)
        if isinstance(next_line, dict) and next_line.get("page") == page_number
        else None
    )
    if next_top is not None:
        bottom_px = min(bottom_px + 24, next_top - 20)
    else:
        bottom_px = min(page_height_px - 24, bottom_px + 28)
    top_px = max(0, top_px - 24)
    bottom_px = min(page_height_px, max(bottom_px, top_px + 48))
    left_px = max(0, split_x - 24)
    right_px = page_width_px - 18
    if right_px <= left_px:
        right_px = page_width_px

    clip = fitz.Rect(
        left_px / px_per_point,
        top_px / px_per_point,
        right_px / px_per_point,
        bottom_px / px_per_point,
    ) & page.rect
    return clip, {
        "bboxPx": {
            "left": round(left_px),
            "top": round(top_px),
            "right": round(right_px),
            "bottom": round(bottom_px),
        },
        "ocrDpi": ocr_dpi,
        "columnSplitX": split_x,
        "hasOcrRightText": has_right_text,
    }


def _asset_for_crop(
    *,
    page: fitz.Page,
    page_number: int,
    context: dict[str, Any],
    asset_dir: Path,
    render_dpi: int,
    question_id: str,
) -> tuple[dict[str, Any], bytes]:
    clip, crop = _crop_bounds(page, context, page_number)
    matrix = fitz.Matrix(render_dpi / 72.0, render_dpi / 72.0)
    pixmap = page.get_pixmap(
        matrix=matrix,
        clip=clip,
        colorspace=fitz.csRGB,
        alpha=False,
    )
    image_bytes = pixmap.tobytes("png")
    digest = hashlib.sha256(image_bytes).hexdigest()
    destination = asset_dir / f"{digest}.png"
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(image_bytes)
    locator = (
        f"{context['report']['source']['filename']} page {page_number} / "
        f"Question {context['number']} / answer-explanation column"
    )
    detected_table = _table_like(page, clip)
    asset = {
        "id": f"ocr-review-explanation-{digest[:24]}",
        "path": _relative_path(destination),
        "localPath": _relative_path(destination),
        "sha256": digest,
        "kind": "table" if detected_table else "image",
        "alt": (
            f"Unverified source explanation crop for {context['subject']} "
            f"question {context['number']} on PDF page {page_number}; "
            "feedback-only review image."
        ),
        "caption": (
            f"Feedback-only source crop · PDF page {page_number} · "
            f"Question {context['number']}"
        ),
        "visibility": "feedback",
        "sourceLocator": locator,
        "reviewStatus": "needs_review",
        "answerMarked": True,
        "questionId": question_id,
        "page": page_number,
        "crop": crop,
        "renderDpi": render_dpi,
    }
    return asset, image_bytes


def _record_visuals(
    *,
    record: dict[str, Any],
    context: dict[str, Any],
    document: fitz.Document,
    asset_dir: Path,
    render_dpi: int,
    assets: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if context.get("placeholder"):
        record["explanationVisuals"] = []
        record["explanationVisualStatus"] = "unavailable"
        record["explanationVisualReviewReason"] = (
            "No recoverable OCR question boundary; no source crop was assigned."
        )
        return []

    refs: list[dict[str, Any]] = []
    for page_number in context["pages"]:
        asset, _ = _asset_for_crop(
            page=document[page_number - 1],
            page_number=page_number,
            context=context,
            asset_dir=asset_dir,
            render_dpi=render_dpi,
            question_id=record["id"],
        )
        asset_id = asset["id"]
        prior = assets.get(asset_id)
        if prior:
            prior.setdefault("questionIds", []).append(record["id"])
        else:
            asset["questionIds"] = [record["id"]]
            assets[asset_id] = asset
        refs.append(
            {
                key: asset[key]
                for key in (
                    "id",
                    "path",
                    "localPath",
                    "sha256",
                    "kind",
                    "alt",
                    "caption",
                    "visibility",
                    "sourceLocator",
                    "reviewStatus",
                    "answerMarked",
                    "page",
                    "crop",
                    "renderDpi",
                )
            }
        )
    record["explanationVisuals"] = refs
    record["explanationVisualStatus"] = (
        "generated_needs_review" if refs else "unavailable"
    )
    if not refs:
        record["explanationVisualReviewReason"] = "No source pages in OCR block."
    return refs


def review_ocr(
    *,
    pdf_path: Path,
    report_path: Path,
    qbank_path: Path,
    output_qbank_path: Path,
    asset_dir: Path,
    manifest_path: Path,
    audit_path: Path,
    render_dpi: int = 150,
) -> dict[str, Any]:
    report = _read_json(report_path)
    qbank = _read_json(qbank_path)
    if report.get("reviewStatus") != "needs_review":
        raise SystemExit("OCR report must remain marked needs_review")
    if qbank.get("reviewStatus") != "needs_review":
        raise SystemExit("OCR qbank must remain marked needs_review")
    if not pdf_path.is_file():
        raise SystemExit(f"Source PDF does not exist: {pdf_path}")
    source_hash = _sha256(pdf_path)
    report_hash = report.get("source", {}).get("sha256")
    qbank_hash = qbank.get("source", {}).get("sha256")
    if source_hash != report_hash or source_hash != qbank_hash:
        raise SystemExit(
            "Source hash mismatch: refusing to render or attach evidence from a different PDF"
        )

    contexts, expected_ids = _build_contexts(report)
    records = qbank.get("records")
    if not isinstance(records, list):
        raise SystemExit("OCR qbank must contain a records list")
    records_by_id = {
        record.get("id"): record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }
    missing_ids = sorted(expected_ids - set(records_by_id))
    unexpected_ids = sorted(set(records_by_id) - expected_ids)
    if missing_ids or unexpected_ids:
        raise SystemExit(
            "OCR qbank and source-boundary reconstruction disagree: "
            f"missing={missing_ids[:3]} unexpected={unexpected_ids[:3]}"
        )

    asset_dir.mkdir(parents=True, exist_ok=True)
    assets: dict[str, dict[str, Any]] = {}
    audit_records: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        document_page_count = len(document)
        if document_page_count != int(report.get("source", {}).get("pages", 0)):
            raise SystemExit("Source PDF page count does not match the OCR report")
        for record in records:
            if not isinstance(record, dict):
                continue
            record_id = record["id"]
            context = contexts[record_id]
            if context.get("placeholder"):
                audit = _audit_placeholder(record, context)
            else:
                audit = _audit_candidate(record, context)
            record["ocrSourceAudit"] = audit
            for issue in audit["issues"]:
                if issue not in record.setdefault("issues", []):
                    record["issues"].append(issue)
            record["issues"] = sorted(set(record["issues"]))
            _record_visuals(
                record=record,
                context=context,
                document=document,
                asset_dir=asset_dir,
                render_dpi=render_dpi,
                assets=assets,
            )
            audit_records.append({"questionId": record_id, **audit})

    status_counts: dict[str, int] = {}
    for item in audit_records:
        status = item["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    audit_output = {
        "reviewStatus": "needs_review",
        "scope": "structural_source_check_only",
        "source": {
            "filename": pdf_path.name,
            "sha256": source_hash,
            "pages": document_page_count,
        },
        "report": {
            "path": _relative_path(report_path),
            "ocr": report.get("ocr"),
        },
        "qbank": {
            "path": _relative_path(qbank_path),
            "records": len(records),
        },
        "summary": {
            "recordsChecked": len(audit_records),
            "statusCounts": status_counts,
            "questionAnswerMismatches": sum(
                item["status"] == "mismatch" for item in audit_records
            ),
            "structurallyConsistent": sum(
                item["status"] == "structurally_consistent" for item in audit_records
            ),
            "requiresManualReview": sum(
                item["status"] != "structurally_consistent" for item in audit_records
            ),
        },
        "records": audit_records,
    }
    manifest_output = {
        "version": 1,
        "kind": "ocr-review-explanation-assets",
        "reviewStatus": "needs_review",
        "description": (
            "Source-PDF answer/explanation crops for OCR review. These are "
            "feedback-only evidence and are not canonical verified visuals."
        ),
        "source": {
            "filename": pdf_path.name,
            "sha256": source_hash,
            "pages": document_page_count,
        },
        "render": {
            "dpi": render_dpi,
            "region": "right answer/explanation column",
            "visibility": "feedback",
            "answerMarked": True,
        },
        "audit": {
            "path": _relative_path(audit_path),
            "summary": audit_output["summary"],
        },
        "assets": sorted(assets.values(), key=lambda asset: asset["id"]),
        "questionAssets": [
            {
                "questionId": record["id"],
                "assetIds": [
                    visual["id"] for visual in record.get("explanationVisuals", [])
                ],
                "status": record.get("explanationVisualStatus"),
            }
            for record in records
            if isinstance(record, dict)
        ],
    }
    qbank["ocrReview"] = {
        "reviewStatus": "needs_review",
        "explanationPresentation": "source_pdf_feedback_image",
        "explanationVisualManifest": _relative_path(manifest_path),
        "sourceAudit": _relative_path(audit_path),
        "sourceAuditSummary": audit_output["summary"],
        "assetsDirectory": _relative_path(asset_dir),
        "renderDpi": render_dpi,
        "note": (
            "OCR explanation text is retained for audit only; explanation "
            "images are feedback-only and require independent visual/alt-text review."
        ),
    }
    _write_json(audit_path, audit_output)
    _write_json(manifest_path, manifest_output)
    _write_json(output_qbank_path, qbank)
    return {
        "qbank": _relative_path(output_qbank_path),
        "manifest": _relative_path(manifest_path),
        "audit": _relative_path(audit_path),
        "assets": len(assets),
        "records": len(records),
        "statusCounts": status_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render OCR explanation crops and structurally audit source Q&A"
    )
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--qbank", type=Path, default=DEFAULT_QBANK)
    parser.add_argument("--output-qbank", type=Path, default=DEFAULT_QBANK)
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSET_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--render-dpi", type=int, default=150)
    args = parser.parse_args()
    if args.render_dpi < 72 or args.render_dpi > 600:
        raise SystemExit("--render-dpi must be between 72 and 600")
    result = review_ocr(
        pdf_path=args.pdf,
        report_path=args.report,
        qbank_path=args.qbank,
        output_qbank_path=args.output_qbank,
        asset_dir=args.assets_dir,
        manifest_path=args.manifest,
        audit_path=args.audit,
        render_dpi=args.render_dpi,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

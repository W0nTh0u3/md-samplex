"""Fetch and parse a public Notion QBank through its read-only page API.

This is an intake adapter for the public page when an owner cannot provide an
export. It snapshots the API response locally, records the source hash and
retrieval configuration, and emits review-only records. It never mutates
Notion and never infers an answer when the source does not expose one
unambiguously.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from .extract import validate
    from .notion_import import (
        OPTION_RE,
        clean,
        has_multiple_indicator,
        subject_slug,
    )
except ImportError:  # Running the script directly from scripts/.
    from extract import validate
    from notion_import import OPTION_RE, clean, has_multiple_indicator, subject_slug


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = "https://www.notion.so/api/v3"
DATABASE_PAGE_ID = "5534be59-f268-4365-b4c4-d9be5a70af86"
COLLECTION_ID = "3e64d1be-6a26-40a8-b72e-29e66921812d"
COLLECTION_VIEW_ID = "7e8d3971-8932-44f6-a8ad-7b88ea6c39af"
SPACE_ID = "590d51e2-32a1-43e4-95c4-f752dda65bfc"
PUBLIC_URL = "https://plereviewhub.notion.site/5534be59f2684365b4c4d9be5a70af86"
USER_AGENT = "PLE-Practice-public-Notion-intake/1.0"
RECORD_BATCH_SIZE = 100
EXPLICIT_QUESTION_RE = re.compile(
    r"^(?:question\s*)?(?P<number>\d{1,4})\s*(?:[.):]\s+|-\s+)(?P<stem>.+)$",
    re.IGNORECASE,
)


def _post(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{API_ROOT}/{endpoint}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "x-notion-space-id": SPACE_ID,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def _record_map(response: dict[str, Any]) -> dict[str, Any]:
    return response.get("recordMap", {}).get("block", {})


def _block_value(entry: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    return entry.get("value", {}).get("value", {})


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _merge_record_values(blocks: dict[str, Any], response: dict[str, Any]) -> int:
    """Merge values returned by getRecordValues into a page block map."""

    merged = 0
    for result in response.get("results", []):
        value = result.get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict) or not value.get("id"):
            continue
        blocks[str(value["id"])] = {
            "value": {"value": value, "role": result.get("role", "reader")}
        }
        merged += 1
    return merged


def _option_child_ids(blocks: dict[str, Any]) -> list[str]:
    """Find unloaded direct children of option toggles.

    Notion's public page chunk omits collapsed toggle bodies. The option
    headings are present, so these children are the narrowest safe set to
    hydrate before following any nested rationale content.
    """

    ids: list[str] = []
    for entry in blocks.values():
        block = entry.get("value", {}).get("value", {})
        if block.get("type") != "toggle":
            continue
        title, _ = _title(block)
        if not OPTION_RE.match(_inline(title)):
            continue
        ids.extend(
            str(child_id)
            for child_id in block.get("content", []) or []
            if str(child_id) not in blocks
        )
    return list(dict.fromkeys(ids))


def _hydrate_option_children(blocks: dict[str, Any]) -> int:
    """Load option rationales and any nested rationale blocks in batches."""

    pending = _option_child_ids(blocks)
    seen: set[str] = set()
    requests = 0
    while pending:
        batch = [block_id for block_id in pending if block_id not in seen][:RECORD_BATCH_SIZE]
        if not batch:
            break
        seen.update(batch)
        response = _post(
            "getRecordValues",
            {"requests": [{"id": block_id, "table": "block"} for block_id in batch]},
        )
        requests += 1
        _merge_record_values(blocks, response)
        discovered: list[str] = []
        for block_id in batch:
            block = _block_value(blocks.get(block_id))
            discovered.extend(
                str(child_id)
                for child_id in block.get("content", []) or []
                if str(child_id) not in blocks and str(child_id) not in seen
            )
        pending.extend(discovered)
        pending = list(dict.fromkeys(pending))
    return requests


def _load_collection() -> dict[str, Any]:
    return _post(
        "queryCollection",
        {
            "collectionView": {"id": COLLECTION_VIEW_ID, "spaceId": SPACE_ID},
            "collectionViewBlock": {"id": DATABASE_PAGE_ID, "spaceId": SPACE_ID},
            "clientType": "notion_app",
            "userTimeZone": "UTC",
            "isFullScreen": True,
            "isMobile": False,
        },
    )


def _subject_page_ids(collection_response: dict[str, Any]) -> list[str]:
    groups = (
        collection_response.get("result", {})
        .get("reducerResults", {})
        .get("table_groups", {})
        .get("blockResults", {})
    )
    ids: list[str] = []
    for group in groups.values():
        ids.extend(str(value) for value in group.get("blockIds", []))
    return list(dict.fromkeys(ids))


def _load_page(page_id: str, limit: int = 1000) -> dict[str, Any]:
    """Load one page and all nested blocks by following Notion cursors."""

    cursor: dict[str, Any] = {"stack": []}
    seen: set[str] = set()
    merged: dict[str, Any] = {}
    chunk_requests = 0
    while True:
        chunk_requests += 1
        if chunk_requests > 500:
            raise RuntimeError(f"Notion cursor did not converge for page {page_id}")
        response = _post(
            "loadCachedPageChunk",
            {
                "pageId": page_id,
                "limit": limit,
                "cursor": cursor,
                "chunkNumber": 0,
                "verticalColumns": False,
            },
        )
        merged.update(_record_map(response))
        next_cursor = response.get("cursor") or {"stack": []}
        marker = _canonical_json(next_cursor)
        if marker in seen:
            raise RuntimeError(f"Notion cursor repeated for page {page_id}")
        seen.add(marker)
        if not next_cursor.get("stack"):
            break
        cursor = next_cursor
    record_requests = _hydrate_option_children(merged)
    return {
        "pageId": page_id,
        "blocks": merged,
        "requests": chunk_requests + record_requests,
        "chunkRequests": chunk_requests,
        "recordRequests": record_requests,
    }


def fetch_snapshot() -> dict[str, Any]:
    collection = _load_collection()
    page_ids = _subject_page_ids(collection)
    if len(page_ids) != 12:
        raise RuntimeError(f"Expected 12 public subject pages, received {len(page_ids)}")
    pages = [_load_page(page_id) for page_id in page_ids]
    snapshot = {
        "source": {
            "url": PUBLIC_URL,
            "databasePageId": DATABASE_PAGE_ID,
            "collectionId": COLLECTION_ID,
            "collectionViewId": COLLECTION_VIEW_ID,
            "spaceId": SPACE_ID,
            "api": "queryCollection + loadCachedPageChunk + getRecordValues",
            "apiVersion": 3,
            "recordBatchSize": RECORD_BATCH_SIZE,
            "retrievedAt": datetime.now(timezone.utc).isoformat(),
        },
        "collection": collection,
        "pages": pages,
    }
    stable = _canonical_json({"collection": collection, "pages": pages})
    snapshot["source"]["sha256"] = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    return snapshot


def _rich_text(value: Any) -> tuple[str, list[Any]]:
    """Flatten a Notion rich-text property while retaining formatting runs."""

    if not isinstance(value, list):
        return "", []
    parts: list[str] = []
    marks: list[Any] = []
    for run in value:
        if isinstance(run, list) and run and isinstance(run[0], str):
            parts.append(run[0])
            if len(run) > 1:
                marks.extend(run[1:] if isinstance(run[1], list) else [run[1]])
    return clean("".join(parts)), marks


def _property_text(value: Any) -> str:
    text, _ = _rich_text(value)
    return text


def _title(block: dict[str, Any]) -> tuple[str, list[Any]]:
    properties = block.get("properties", {})
    for key in ("title", "caption"):
        if key in properties:
            return _rich_text(properties[key])
    return "", []


ANSWER_BACKGROUND_TOKENS = ("green_background", "teal_background")


def _has_answer_highlight(value: Any) -> bool:
    """Recognize Notion's explicit answer-background colors.

    The public renderer maps ``teal_background`` to its secondary green
    palette (``--c-greBacSec``). It is therefore the source-level marker used
    by the observed QBank, even though it is not named ``green_background``.
    Keep this allow-list exact so ordinary prose containing a color name can
    never become an answer key.
    """

    encoded = json.dumps(value, ensure_ascii=False).casefold()
    return any(token in encoded for token in ANSWER_BACKGROUND_TOKENS)


def _inline(value: str) -> str:
    """Normalize line-wrapped Notion headings for boundary recognition."""

    return clean(re.sub(r"\s+", " ", value))


def _children(block: dict[str, Any]) -> list[str]:
    return [str(value) for value in block.get("content", []) if value]


def _walk_ids(blocks: dict[str, Any], root_id: str) -> Iterable[str]:
    for child_id in _children(_block_value(blocks.get(root_id))):
        yield child_id
        yield from _walk_ids(blocks, child_id)


def _source_metadata(page: dict[str, Any], page_block: dict[str, Any]) -> dict[str, str | bool]:
    values = " ".join(
        _property_text(value)
        for value in page_block.get("properties", {}).values()
        if isinstance(value, list)
    ).casefold()
    metadata: dict[str, str | bool] = {
        "publicApi": "notion-v3",
        "pageId": page["pageId"],
    }
    if "with ratio" in values:
        metadata["withRatio"] = True
    if "for revision" in values:
        metadata["forRevision"] = True
    return metadata


def _rationale_text(blocks: dict[str, Any], option_id: str, issues: set[str]) -> str:
    parts: list[str] = []
    for block_id in _walk_ids(blocks, option_id):
        block = _block_value(blocks.get(block_id))
        block_type = block.get("type")
        title, _ = _title(block)
        if block_type in {"image", "video", "file", "pdf", "equation", "transclusion_reference", "transclusion_container"}:
            issues.add("source_visual_requires_review")
            continue
        if title and block_type not in {"column", "column_list", "toggle", "page"}:
            parts.append(title)
    return clean("\n".join(parts))


def _parse_page(page: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = page["blocks"]
    page_block = _block_value(blocks.get(page["pageId"]))
    page_title, _ = _title(page_block)
    subject = subject_slug(page_title)
    if not subject:
        raise RuntimeError(f"Could not map public Notion page to a subject: {page_title}")
    metadata = _source_metadata(page, page_block)
    records: list[dict[str, Any]] = []
    top_level = _children(page_block)
    ordinal = 0
    for block_id in top_level:
        question_block = _block_value(blocks.get(block_id))
        if question_block.get("type") != "numbered_list":
            continue
        ordinal += 1
        question_title, _ = _title(question_block)
        explicit_match = EXPLICIT_QUESTION_RE.match(_inline(question_title))
        number = int(explicit_match.group("number")) if explicit_match else ordinal
        stem = explicit_match.group("stem") if explicit_match else question_title
        issues: set[str] = set()
        choices: list[dict[str, str]] = []
        rationales: dict[str, str] = {}
        marked: list[str] = []
        for descendant_id in _walk_ids(blocks, block_id):
            candidate = _block_value(blocks.get(descendant_id))
            if candidate.get("type") != "toggle":
                continue
            option_title, marks = _title(candidate)
            option_match = OPTION_RE.match(_inline(option_title))
            if not option_match:
                continue
            label = option_match.group("label").upper()
            if any(choice["label"] == label for choice in choices):
                continue
            choices.append({"label": label, "text": clean(option_match.group("text"))})
            rationale = _rationale_text(blocks, descendant_id, issues)
            if rationale:
                rationales[label] = rationale
            highlighted = _has_answer_highlight(marks) or _has_answer_highlight(
                candidate.get("format", {})
            )
            if not highlighted:
                # In the public QBank the answer color is applied to the
                # expanded rationale text block, not to the option toggle.
                # Following the option's descendants preserves that explicit
                # source annotation without inferring from rationale prose.
                for rationale_id in _walk_ids(blocks, descendant_id):
                    rationale_block = _block_value(blocks.get(rationale_id))
                    rationale_title, rationale_marks = _title(rationale_block)
                    if _has_answer_highlight(rationale_block.get("format", {})) or _has_answer_highlight(rationale_marks):
                        highlighted = True
                        break
            if highlighted:
                marked.append(label)
        explicit_multiple = has_multiple_indicator(stem)
        if len(marked) > 1 and explicit_multiple:
            answer_mode = "multiple"
            correct_choice: str | None = None
            correct_choices: list[str] | None = list(dict.fromkeys(marked))
            multiple_explicit = True
        elif len(marked) == 1:
            answer_mode = "single"
            correct_choice = marked[0]
            correct_choices = None
            multiple_explicit = False
        else:
            answer_mode = "single"
            correct_choice = None
            correct_choices = None
            multiple_explicit = False
            if len(marked) > 1:
                issues.add("conflicting_answer_highlights")
        if any(
            _block_value(blocks.get(descendant_id)).get("type")
            in {"image", "video", "file", "pdf", "equation", "transclusion_reference", "transclusion_container"}
            for descendant_id in _walk_ids(blocks, block_id)
        ):
            issues.add("source_visual_requires_review")
        source = {
            "filename": f"notion-public/{page['pageId']}",
            "pages": [],
            "answerPages": [],
            "kind": "notion",
            "locator": f"{page_title} / Question {number}",
            "title": page_title,
            "url": PUBLIC_URL,
            "metadata": metadata,
        }
        record: dict[str, Any] = {
            "id": f"notion-{subject}-{number:04d}",
            "subject": subject,
            "originalNumber": number,
            "stem": clean(stem),
            "choices": choices,
            "correctChoice": correct_choice,
            "explanation": "",
            "choiceRationales": rationales,
            "sources": [source],
            "status": "needs_review",
            "issues": sorted(issues),
            "_raw": "\n".join(
                [clean(stem)]
                + [f"{choice['label']}. {choice['text']}" for choice in choices]
            ),
            "_namespace": "notion",
            "_source_kind": "notion",
        }
        if answer_mode == "multiple":
            record["answerMode"] = "multiple"
            record["correctChoices"] = correct_choices
            record["_multiple_explicit"] = multiple_explicit
        validate(record)
        records.append(record)
    return records


def parse_snapshot(
    snapshot: dict[str, Any], *, review_only: bool = True
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse a snapshot, optionally allowing verified source highlights.

    The standalone public intake remains review-only by default. The canonical
    extractor may opt into the same explicit answer annotations after the
    source color mapping has been verified; structural validation still
    quarantines malformed, visual, and ambiguous records.
    """

    pages = snapshot.get("pages", [])
    records = [record for page in pages for record in _parse_page(page)]
    source = snapshot.get("source", {})
    report = {
        "source": source,
        "pages": len(pages),
        "records": len(records),
        "choiceRationaleRecords": sum(bool(record.get("choiceRationales")) for record in records),
        "explicitAnswerRecords": sum(
            bool(record.get("correctChoice") or record.get("correctChoices"))
            for record in records
        ),
        "reviewStatus": "needs_review" if review_only else "source_annotations_verified",
        "issues": {},
    }
    for record in records:
        if review_only:
            record["issues"] = sorted(
                set(record["issues"] + ["public_snapshot_requires_review"])
            )
            record["status"] = "needs_review"
        for issue in record["issues"]:
            report["issues"][issue] = report["issues"].get(issue, 0) + 1
    return records, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a public Notion QBank into a review-only snapshot")
    parser.add_argument("--snapshot", type=Path, help="Use an existing snapshot instead of fetching")
    parser.add_argument("--output", type=Path, default=ROOT / ".local/notion-public-qbank.json")
    parser.add_argument("--raw-output", type=Path, default=ROOT / ".local/notion-public-snapshot.json")
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8")) if args.snapshot else fetch_snapshot()
    records, report = parse_snapshot(snapshot)
    args.raw_output.parent.mkdir(parents=True, exist_ok=True)
    args.raw_output.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"records": records, "report": report}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "pages",
                    "records",
                    "choiceRationaleRecords",
                    "explicitAnswerRecords",
                    "issues",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

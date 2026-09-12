"""Parse a local Notion HTML or Markdown export into reviewable question records.

The parser is deliberately local and conservative. It recognizes explicit
question/choice boundaries and explicit answer markers, but it never chooses a
key from prose or from a Notion property such as ``With Ratio``. Records that
cannot be represented as a single-answer MCQ are returned with review issues so
the canonical extraction pipeline can exclude them from scored sessions.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


EXPORT_SUFFIXES = {".html", ".htm", ".md", ".markdown"}


OPTION_RE = re.compile(
    r"^(?:(?:[-*+]\s+)?(?:\[[ xX]\]|[✓✔✅★*])\s*)?"
    r"(?P<label>[A-Ea-e])\s*[.)\-:]\s+(?P<text>.+)$"
)
QUESTION_RE = re.compile(
    r"^(?:question\s*)?(?P<number>\d{1,4})\s*[.):\-]\s*(?P<stem>.*)$",
    re.IGNORECASE,
)
QUESTION_ONLY_RE = re.compile(
    r"^(?:question\s*)?(?P<number>\d{1,4})\s*$", re.IGNORECASE
)
ANSWER_RE = re.compile(
    r"^(?:correct\s+)?(?:answer|key|correct\s+choice)\s*[:=\-]\s*"
    r"(?:option\s*)?[\[(]?\s*(?P<answer>[A-Ea-e])\s*[\].)]?\s*$",
    re.IGNORECASE,
)
MULTI_ANSWER_RE = re.compile(
    r"^(?:correct\s+)?(?:answers?|keys?|correct\s+choices?)\s*[:=\-]\s*"
    r"(?P<answers>[A-Ea-e](?:\s*(?:,|/|and|&|\+)\s*[A-Ea-e])+)$",
    re.IGNORECASE,
)
MULTI_ANSWER_PREFIX_RE = re.compile(
    r"^(?:correct\s+)?(?:answers?|keys?|correct\s+choices?)\s*[:=\-]",
    re.IGNORECASE,
)
MULTIPLE_INDICATOR_RE = re.compile(
    r"\b(?:select\s+all(?:\s+that\s+apply)?|all\s+that\s+apply|"
    r"choose\s+all|multiple\s+(?:answer|response|choice)s?|more\s+than\s+one)\b",
    re.IGNORECASE,
)
RATIONALE_RE = re.compile(
    r"^(?:rationale|reason|why)\s*[:\-]\s*(?P<text>.*)$", re.IGNORECASE
)
EXPLANATION_RE = re.compile(
    r"^(?:overall\s+)?(?:source\s+)?explanation\s*[:\-]?\s*(?P<text>.*)$",
    re.IGNORECASE,
)
PROPERTY_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z ]{1,40})\s*[:|]\s*(?P<value>.+)$")
BLOCK_TAGS = {"address", "blockquote", "dd", "div", "dt", "h1", "h2", "h3", "h4", "li", "p", "pre", "td", "th", "tr"}


def has_multiple_indicator(value: str | None) -> bool:
    return bool(MULTIPLE_INDICATOR_RE.search(clean(value or "")))


def parse_multiple_answer(value: str | None) -> list[str] | None:
    """Parse an explicitly labelled, unambiguous multiple-response key."""

    match = MULTI_ANSWER_RE.match(clean(value or ""))
    if not match:
        return None
    labels = [
        label.upper() for label in re.findall(r"[A-Ea-e]", match.group("answers"))
    ]
    if len(labels) < 2 or len(set(labels)) != len(labels):
        return None
    return labels


def discover_export_files(path: str | Path) -> list[Path]:
    """Return supported local export files in deterministic order.

    Notion's HTML export is commonly a directory rather than a single file.
    Attachments and unsupported files are ignored; an empty or unsupported
    path fails explicitly so extraction cannot silently publish an empty bank.
    """

    source_path = Path(path)
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if source_path.is_file():
        if source_path.suffix.casefold() not in EXPORT_SUFFIXES:
            raise ValueError(f"Unsupported Notion export format: {source_path}")
        return [source_path]
    files = sorted(
        (
            candidate
            for candidate in source_path.rglob("*")
            if candidate.is_file()
            and candidate.suffix.casefold() in EXPORT_SUFFIXES
        ),
        key=lambda candidate: candidate.as_posix().casefold(),
    )
    if not files:
        raise ValueError(f"No HTML or Markdown files found in Notion export: {source_path}")
    return files


def subject_slug(value: str | None) -> str | None:
    """Map an explicit subject label or slug to the bank subject ID.

    This is intentionally limited to the twelve known PLE subjects. It is not
    used to classify question content; it only makes a page filename/title
    usable as a manifest convenience when it is an unambiguous subject label.
    """

    if not value:
        return None
    compact = re.sub(r"[^a-z0-9]+", "", clean(value).casefold())
    aliases = {
        "biochemistry": "biochemistry",
        "anatomy": "anatomy",
        "anatomyhistology": "anatomy",
        "microbiology": "microbiology",
        "microbiologyparasitology": "microbiology",
        "physiology": "physiology",
        "legalmedicine": "legal-medicine",
        "legalmedicineandjuris": "legal-medicine",
        "jurisprudence": "legal-medicine",
        "pathology": "pathology",
        "pharmacology": "pharmacology",
        "surgery": "surgery",
        "internalmedicine": "internal-medicine",
        "obstetricsgynecology": "obstetrics-gynecology",
        "obgyne": "obstetrics-gynecology",
        "obsgyne": "obstetrics-gynecology",
        "pediatrics": "pediatrics",
        "preventivemedicine": "preventive-medicine",
    }
    exact = aliases.get(compact)
    if exact:
        return exact
    matches = [slug for alias, slug in aliases.items() if alias in compact]
    return matches[0] if len(set(matches)) == 1 else None


def clean(value: str | None) -> str:
    text = html.unescape(value or "").replace("\u00a0", " ")
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    text = re.sub(r"(?<!\w)\*+|\*+(?!\w)", "", text)
    text = re.sub(r"(?<!\w)_+|_+(?!\w)", "", text)
    text = text.replace("`", "")
    return "\n".join(
        re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()
    ).strip()


def normalized(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def safe_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value.strip()
    return None


def boolean_property(value: str) -> bool | None:
    normalized_value = clean(value).casefold()
    if normalized_value in {"yes", "true", "1", "on", "y"}:
        return True
    if normalized_value in {"no", "false", "0", "off", "n"}:
        return False
    return None


class _HTMLBlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, Any]] = []
        self.title = ""
        self._parts: list[str] = []
        self._links: list[str] = []
        self._block_tag: str | None = None
        self._marked = False
        self._visual = False
        self._ignored = 0
        self._in_title = False
        self._list_depth = 0
        self._block_depth = 0

    def _flush(self) -> None:
        text = clean("".join(self._parts))
        if text or self._visual:
            self.blocks.append(
                {
                    "text": text,
                    "tag": self._block_tag or "text",
                    "marked": self._marked,
                    "visual": self._visual,
                    "links": list(self._links),
                    "depth": self._block_depth,
                }
            )
        self._parts = []
        self._links = []
        self._block_tag = None
        self._marked = False
        self._visual = False
        self._block_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored += 1
            return
        attributes = dict(attrs)
        if tag == "title":
            self._in_title = True
            return
        if tag in {"ol", "ul"}:
            self._list_depth += 1
        if tag in BLOCK_TAGS:
            if self._parts or self._visual:
                self._flush()
            self._block_tag = tag
            self._block_depth = self._list_depth
        if tag in {"strong", "b", "mark"}:
            self._marked = True
        class_text = (attributes.get("class") or "").casefold()
        style_text = (attributes.get("style") or "").casefold()
        if any(token in class_text for token in {"correct", "answer", "selected", "green"}) or "background" in style_text:
            self._marked = True
        if tag in {"img", "figure", "svg", "canvas"}:
            self._visual = True
        if tag == "a" and attributes.get("href"):
            self._links.append(attributes["href"] or "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag in {"br", "hr"}:
            self._parts.append("\n")
        if tag in {"img", "figure", "svg", "canvas"}:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored = max(0, self._ignored - 1)
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in BLOCK_TAGS:
            self._flush()
        if tag in {"ol", "ul"}:
            self._list_depth = max(0, self._list_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        if self._in_title:
            self.title = clean(f"{self.title} {data}")
        else:
            self._parts.append(data)

    def finish(self) -> None:
        self._flush()


def _html_blocks(text: str) -> tuple[list[dict[str, Any]], str]:
    parser = _HTMLBlockParser()
    parser.feed(text)
    parser.close()
    parser.finish()
    return parser.blocks, parser.title


def _markdown_blocks(text: str) -> tuple[list[dict[str, Any]], str]:
    blocks: list[dict[str, Any]] = []
    title = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line in {"---", "***"}:
            continue
        if line.startswith("<!--") and line.endswith("-->"):
            continue
        heading = re.match(r"^#{1,6}\s+(.*)$", line)
        if heading:
            value = clean(heading.group(1))
            if not title and not QUESTION_RE.match(value) and not QUESTION_ONLY_RE.match(value):
                title = value
            blocks.append({"text": value, "tag": "h", "marked": False, "visual": False, "links": [], "depth": 0})
            continue
        visual = bool(re.match(r"^!\[[^]]*\]\([^)]*\)", line))
        marked = bool(re.match(r"^(?:\*\*|__|\[[xX]\]|[✓✔✅★])", line))
        indentation = len(raw_line) - len(raw_line.lstrip(" \t"))
        expanded_indentation = len(raw_line[:indentation].expandtabs(4))
        bullet = bool(re.match(r"^[ \t]*[-*+]\s+", raw_line))
        depth = max(1, expanded_indentation // 2 + 1) if bullet else 0
        if line.startswith("|") and line.endswith("|"):
            cells = [clean(cell) for cell in line.strip("|").split("|")]
            property_name = cells[0].casefold() if cells else ""
            if len(cells) >= 2 and property_name in {"with ratio", "for revision", "canonical url", "url", "notion url"}:
                blocks.append({"text": f"{cells[0]}: {cells[1]}", "tag": "td", "marked": False, "visual": False, "links": [], "depth": 0})
            else:
                for cell in cells:
                    if cell and not re.fullmatch(r":?-{3,}:?", cell):
                        blocks.append({"text": cell, "tag": "td", "marked": False, "visual": False, "links": [], "depth": 0})
            continue
        blocks.append(
            {
                "text": clean(re.sub(r"^[-*+]\s+", "", line)),
                "tag": "li" if re.match(r"^[-*+]\s+", line) else "p",
                "marked": marked,
                "visual": visual,
                "links": [],
                "depth": depth,
            }
        )
    return blocks, title


def _property(block: str) -> tuple[str, str] | None:
    match = PROPERTY_RE.match(block)
    if not match:
        return None
    return match.group("key").strip().casefold(), clean(match.group("value"))


def _strip_option_decoration(value: str) -> tuple[str, bool]:
    marked = False
    value = value.strip()
    if re.match(r"^(?:\[[xX]\]|[✓✔✅★])", value):
        marked = True
        value = re.sub(r"^(?:\[[xX]\]|[✓✔✅★])\s*", "", value)
    if value.endswith("[correct]") or value.endswith("(correct)"):
        marked = True
        value = re.sub(r"\s*(?:\[correct\]|\(correct\))$", "", value, flags=re.I)
    return clean(value), marked


def _option_is_marked(value: str, option_match: re.Match[str], block: dict[str, Any]) -> bool:
    """Detect an explicit source highlight before or after an option."""

    if block.get("marked"):
        return True
    prefix = value[: option_match.start("label")]
    if re.search(r"(?:\[[xX]\]|[✓✔✅★*])\s*$", prefix):
        return True
    return _strip_option_decoration(option_match.group("text"))[1]


def _new_record(
    subject: str,
    number: int,
    stem: str,
    filename: str,
    title: str,
    canonical_url: str | None,
    metadata: dict[str, str | bool],
    parser_issues: list[str] | None = None,
    source_filename: str | None = None,
) -> dict[str, Any]:
    source: dict[str, Any] = {
        "filename": source_filename or filename,
        "pages": [],
        "answerPages": [],
        "kind": "notion",
        "locator": f"{title} / Question {number}" if title else f"Question {number}",
    }
    if title:
        source["title"] = title
    if canonical_url:
        source["url"] = canonical_url
    if metadata:
        source["metadata"] = metadata
    return {
        "id": f"notion-{subject}-{number:04d}",
        "subject": subject,
        "originalNumber": number,
        "stem": clean(stem),
        "choices": [],
        "correctChoice": None,
        "explanation": "",
        "choiceRationales": {},
        "sources": [source],
        "status": "needs_review",
        "issues": list(parser_issues or []),
        "_raw": "",
        "_namespace": "notion",
        "_source_kind": "notion",
    }


def _finish(record: dict[str, Any] | None, records: list[dict[str, Any]]) -> None:
    if record is None:
        return
    record["stem"] = clean(record.get("stem", ""))
    record["explanation"] = clean(record.get("explanation", ""))
    record["choiceRationales"] = {
        label: clean(text)
        for label, text in record.get("choiceRationales", {}).items()
        if clean(text)
    }
    record["_raw"] = "\n".join(
        [record["stem"]]
        + [f"{choice['label']}. {choice['text']}" for choice in record["choices"]]
    )
    if not record["choiceRationales"]:
        record.pop("choiceRationales", None)
    records.append(record)


def parse_export(
    path: str | Path,
    subject: str,
    canonical_url: str | None = None,
    title: str | None = None,
    source_filename: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return records plus a source-level parsing report for one local export."""

    source_path = Path(path)
    if not source_path.is_file():
        raise ValueError(f"Notion parser expects a file: {source_path}")
    text = source_path.read_text(encoding="utf-8-sig")
    if source_path.suffix.casefold() in {".html", ".htm"}:
        blocks, detected_title = _html_blocks(text)
    else:
        blocks, detected_title = _markdown_blocks(text)
    page_title = clean(title or detected_title or source_path.stem)
    source_name = source_filename or source_path.name
    explicit_url = safe_url(canonical_url)
    if not explicit_url:
        for block in blocks:
            explicit_url = next(
                (safe_url(link) for link in block.get("links", []) if safe_url(link)),
                None,
            )
            if explicit_url:
                break
    properties: dict[str, str | bool] = {}
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_choice: dict[str, Any] | None = None
    mode = "stem"
    next_number = 1
    malformed_blocks = 0
    pending_property: str | None = None
    option_depth: int | None = None

    def set_property(key: str, value: str) -> None:
        nonlocal explicit_url
        if key in {"with ratio", "for revision"}:
            parsed = boolean_property(value)
            if parsed is not None:
                properties["withRatio" if key == "with ratio" else "forRevision"] = parsed
            return
        if key in {"canonical url", "url", "notion url"} and not explicit_url:
            explicit_url = safe_url(value)

    for block in blocks:
        text_value = clean(str(block.get("text", "")))
        if not text_value:
            continue
        if current is None and pending_property:
            parsed_value = (
                boolean_property(text_value)
                if pending_property in {"with ratio", "for revision"}
                else safe_url(text_value)
            )
            if (
                parsed_value is not None
                and (
                    pending_property in {"with ratio", "for revision"}
                    or bool(parsed_value)
                )
            ):
                set_property(pending_property, text_value)
                pending_property = None
                continue
            if pending_property in {"with ratio", "for revision"}:
                # Notion pages often export a checkbox label without its
                # value. Treat the label as true, but do not swallow the next
                # metadata block (for example, "Subject ...").
                set_property(pending_property, "true")
            pending_property = None
        property_pair = _property(text_value)
        if property_pair and current is None:
            set_property(*property_pair)
            continue
        if current is None and text_value.casefold() in {"with ratio", "for revision", "canonical url", "url", "notion url"}:
            pending_property = text_value.casefold()
            continue
        if current is None:
            answer_match = ANSWER_RE.match(text_value)
            if answer_match:
                continue

        question_match = QUESTION_RE.match(text_value) or QUESTION_ONLY_RE.match(text_value)
        option_match = OPTION_RE.match(text_value)
        if option_match and current is not None:
            label = option_match.group("label").upper()
            block_depth = int(block.get("depth", 0))
            if option_depth is not None and block_depth != option_depth:
                option_match = None
            elif current["choices"]:
                previous_label = current["choices"][-1]["label"]
                expected_label = chr(ord(previous_label) + 1)
                # Nested rationale lists often reuse a./b./c. markers. Only
                # the next ordered label at the option list's depth starts a
                # new scored choice; the rest remains rationale prose.
                if label != expected_label:
                    option_match = None
        if question_match and not option_match:
            _finish(current, records)
            number = int(question_match.group("number"))
            stem = question_match.groupdict().get("stem") or ""
            current = _new_record(
                subject,
                number,
                stem,
                source_path.name,
                page_title,
                explicit_url,
                dict(properties),
                source_filename=source_name,
            )
            if has_multiple_indicator(stem):
                current["_multiple_explicit"] = True
            current_choice = None
            mode = "stem"
            option_depth = None
            next_number = max(next_number, number + 1)
            continue
        if option_match:
            if current is None:
                current = _new_record(
                    subject,
                    next_number,
                    "",
                    source_path.name,
                    page_title,
                    explicit_url,
                    dict(properties),
                    ["missing_question_number"],
                    source_filename=source_name,
                )
                next_number += 1
            label = option_match.group("label").upper()
            if option_depth is None:
                option_depth = int(block.get("depth", 0))
            option_text, decorated = _strip_option_decoration(option_match.group("text"))
            marked = _option_is_marked(text_value, option_match, block) or decorated
            choice = {"label": label, "text": option_text}
            if any(existing["label"] == label for existing in current["choices"]):
                current["issues"].append("repeated_choice_label")
            current["choices"].append(choice)
            current_choice = choice
            mode = "choice"
            if marked:
                current.setdefault("_highlighted", []).append(label)
            continue

        multiple_answer_match = MULTI_ANSWER_RE.match(text_value)
        if multiple_answer_match and current is not None:
            labels = parse_multiple_answer(text_value)
            if labels is None:
                current["issues"].append("malformed_multiple_answer_key")
            else:
                if current.get("correctChoice"):
                    current["issues"].append("conflicting_answer_sources")
                current["answerMode"] = "multiple"
                current["correctChoice"] = None
                current["correctChoices"] = labels
                current["_multiple_explicit"] = True
            current_choice = None
            mode = "answer"
            continue
        if (
            current is not None
            and MULTI_ANSWER_PREFIX_RE.match(text_value)
            and not multiple_answer_match
            and (
                has_multiple_indicator(current.get("stem"))
                or re.match(
                    r"^(?:correct\s+)?(?:answers|keys|correct\s+choices?)\s*[:=\-]",
                    text_value,
                    re.IGNORECASE,
                )
            )
        ):
            current["issues"].append("malformed_multiple_answer_key")
            current_choice = None
            mode = "answer"
            continue
        answer_match = ANSWER_RE.match(text_value)
        if answer_match and current is not None:
            answer = answer_match.group("answer").upper()
            if current.get("correctChoice") and current["correctChoice"] != answer:
                current["issues"].append("conflicting_answer_sources")
            current["correctChoice"] = answer
            mode = "answer"
            continue
        explanation_match = EXPLANATION_RE.match(text_value)
        if explanation_match and current is not None:
            mode = "explanation"
            remainder = clean(explanation_match.group("text"))
            if remainder:
                current["explanation"] = clean(f"{current['explanation']}\n{remainder}")
            current_choice = None
            continue
        rationale_match = RATIONALE_RE.match(text_value)
        if rationale_match and current_choice is not None:
            text_value = clean(rationale_match.group("text"))
        if current is None:
            if block.get("tag") in {"h", "h1", "h2", "h3", "h4"}:
                continue
            malformed_blocks += 1
            continue
        if not current["choices"]:
            current["stem"] = clean(f"{current['stem']}\n{text_value}")
        elif mode == "explanation":
            current["explanation"] = clean(f"{current['explanation']}\n{text_value}")
        elif current_choice is not None:
            label = current_choice["label"]
            current["choiceRationales"][label] = clean(
                f"{current['choiceRationales'].get(label, '')}\n{text_value}"
            )
        else:
            current["explanation"] = clean(f"{current['explanation']}\n{text_value}")

    if current is None and pending_property in {"with ratio", "for revision"}:
        set_property(pending_property, "true")
    _finish(current, records)
    # Re-parse the answer highlights from the source-local choice metadata. The
    # parser stores them on the current record while it is active; the loop
    # above intentionally keeps all source text lossless.
    # A second lightweight pass associates marked blocks with question records.
    record_index = -1
    for block in blocks:
        value = clean(str(block.get("text", "")))
        question_match = QUESTION_RE.match(value) or QUESTION_ONLY_RE.match(value)
        if question_match and not OPTION_RE.match(value):
            record_index += 1
        if block.get("visual") and 0 <= record_index < len(records):
            records[record_index]["issues"].append("source_visual_requires_review")
    for record in records:
        marks = record.pop("_highlighted", [])
        if len(set(marks)) > 1 and has_multiple_indicator(record.get("stem")):
            record["answerMode"] = "multiple"
            record["correctChoice"] = None
            record["correctChoices"] = list(dict.fromkeys(marks))
            record["_multiple_explicit"] = True
        elif len(set(marks)) == 1 and not record.get("correctChoice"):
            record["correctChoice"] = marks[0]
        elif len(set(marks)) > 1:
            record["issues"].append("conflicting_answer_highlights")
        if marks and record.get("answerMode") == "multiple":
            if set(record.get("correctChoices", [])) != set(marks):
                record["issues"].append("conflicting_answer_sources")
        elif marks and record.get("correctChoice") and record["correctChoice"] not in marks:
            record["issues"].append("conflicting_answer_sources")
        record["issues"] = sorted(set(record["issues"]))

    report = {
        "filename": source_name,
        "format": "html" if source_path.suffix.casefold() in {".html", ".htm"} else "markdown",
        "title": page_title,
        "url": explicit_url,
        "properties": properties,
        "records": len(records),
        "malformedBlocks": malformed_blocks,
        "reviewStatus": "needs_review",
    }
    return records, report


def parse_export_bundle(
    path: str | Path,
    subject: str,
    canonical_url: str | None = None,
    title: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse every supported file in a local Notion export directory."""

    source_path = Path(path)
    files = discover_export_files(source_path)
    records: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for export_file in files:
        relative_name = (
            export_file.relative_to(source_path).as_posix()
            if source_path.is_dir()
            else export_file.name
        )
        file_records, file_report = parse_export(
            export_file,
            subject,
            canonical_url,
            title,
            source_filename=relative_name,
        )
        records.extend(file_records)
        reports.append(file_report)
    return records, {
        "path": source_path.as_posix(),
        "format": "directory" if source_path.is_dir() else reports[0]["format"],
        "files": reports,
        "records": len(records),
        "malformedBlocks": sum(report["malformedBlocks"] for report in reports),
        "reviewStatus": "needs_review",
    }


# Descriptive alias for callers that do not need to know the export formats.
parse_notion_export = parse_export


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a local Notion export")
    parser.add_argument("path", type=Path)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--url")
    parser.add_argument("--title")
    parser.add_argument("--output", type=Path, help="Write the parsed JSON to this path")
    args = parser.parse_args()
    records, report = parse_export_bundle(args.path, args.subject, args.url, args.title)
    payload = json.dumps({"records": records, "report": report}, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()

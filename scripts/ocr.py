"""Local OCR adapter for scanned source PDFs.

OCR output is evidence for manual review, not a validated answer key. Every
page report carries the source hash, OCR configuration, page number and an
explicit ``needs_review`` status so it cannot silently enter the scored bank.
"""

from __future__ import annotations

import csv
import hashlib
import io
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

import fitz


DEFAULT_SAMPLE_RANGES = ((1, 10), (216, 225), (426, 435))
# At 300 DPI the scanned source's question cell ends before this x coordinate
# on the sampled pages. The answer key and explanation start to its right.
DEFAULT_COLUMN_SPLIT_X = 1130


def expand_page_ranges(
    ranges: Iterable[tuple[int, int]], page_count: int | None = None
) -> list[int]:
    pages: set[int] = set()
    for start, end in ranges:
        if start < 1 or end < start:
            raise ValueError(f"Invalid 1-based page range: {start}-{end}")
        if page_count is not None and end > page_count:
            raise ValueError(f"Page range exceeds PDF length: {start}-{end}")
        pages.update(range(start, end + 1))
    return sorted(pages)


def tesseract_version(binary: str) -> str:
    result = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, check=False
    )
    return (result.stdout or result.stderr).splitlines()[0].strip()


def _render_page_png(
    document: fitz.Document, page_number: int, dpi: int
) -> bytes:
    if dpi < 72 or dpi > 600:
        raise ValueError("OCR DPI must be between 72 and 600")
    page = document[page_number - 1]
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
    # Import Pillow only when OCR is requested so normal PDF extraction keeps
    # working in environments that have PyMuPDF but not the optional OCR stack.
    from PIL import Image  # type: ignore[import-not-found]

    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    image_bytes = io.BytesIO()
    image.save(image_bytes, format="PNG", optimize=True)
    return image_bytes.getvalue()


def _run_tesseract(
    image_bytes: bytes,
    *,
    dpi: int,
    language: str,
    psm: int,
    tesseract: str,
    output: str,
    page_number: int,
) -> bytes:
    if shutil.which(tesseract) is None:
        raise RuntimeError(
            "Tesseract is not installed or is not on PATH; install it before OCR."
        )
    result = subprocess.run(
        [
            tesseract,
            "stdin",
            "stdout",
            "--dpi",
            str(dpi),
            "--psm",
            str(psm),
            "-l",
            language,
            output,
        ],
        input=image_bytes,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Tesseract failed on page {page_number}: {message}")
    return result.stdout


def ocr_page(
    document: fitz.Document,
    page_number: int,
    *,
    dpi: int = 300,
    language: str = "eng",
    psm: int = 6,
    tesseract: str = "tesseract",
) -> str:
    """Render and OCR one 1-based page without trusting its PDF text layer."""

    image_bytes = _render_page_png(document, page_number, dpi)
    result = _run_tesseract(
        image_bytes,
        dpi=dpi,
        language=language,
        psm=psm,
        tesseract=tesseract,
        output="txt",
        page_number=page_number,
    )
    return result.decode("utf-8", errors="replace").strip()


def _layout_token_text(value: str) -> str:
    """Drop isolated scan artifacts while retaining punctuation in words."""

    text = value.strip()
    if not text:
        return ""
    if any(character.isalnum() for character in text):
        return text
    # Isolated table-border artifacts such as `_`, `}`, `:` and `;` are not
    # useful content. Question marks attached to words remain untouched.
    return ""


def _parse_tesseract_tsv(raw: bytes, *, column_split_x: int) -> dict[str, Any]:
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8", errors="replace")), delimiter="\t")
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            word = {
                "text": text,
                "left": int(row["left"]),
                "top": int(row["top"]),
                "width": int(row["width"]),
                "height": int(row["height"]),
                "confidence": float(row["conf"]),
            }
            key = (
                int(row["block_num"]),
                int(row["par_num"]),
                int(row["line_num"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        grouped.setdefault(key, []).append(word)

    lines: list[dict[str, Any]] = []
    for words in grouped.values():
        words.sort(key=lambda word: (word["left"], word["top"]))
        left_words = [word for word in words if word["left"] < column_split_x]
        right_words = [word for word in words if word["left"] >= column_split_x]
        left_text = " ".join(
            visible
            for word in left_words
            if (visible := _layout_token_text(word["text"]))
        )
        right_text = " ".join(
            visible
            for word in right_words
            if (visible := _layout_token_text(word["text"]))
        )
        full_text = " ".join(word["text"] for word in words)
        if not (left_text or right_text or full_text.strip()):
            continue
        lines.append(
            {
                "top": min(word["top"] for word in words),
                "left": min(word["left"] for word in words),
                "text": full_text,
                "leftText": left_text,
                "rightText": right_text,
                "words": words,
            }
        )
    lines.sort(key=lambda line: (line["top"], line["left"]))
    return {
        "format": "tesseract-tsv",
        "lines": lines,
        "columnSplitX": column_split_x,
    }


def ocr_page_layout(
    document: fitz.Document,
    page_number: int,
    *,
    dpi: int = 300,
    language: str = "eng",
    psm: int = 6,
    tesseract: str = "tesseract",
    column_split_x: int = DEFAULT_COLUMN_SPLIT_X,
) -> dict[str, Any]:
    """OCR one page and retain TSV coordinates for table-column recovery."""

    image_bytes = _render_page_png(document, page_number, dpi)
    raw_tsv = _run_tesseract(
        image_bytes,
        dpi=dpi,
        language=language,
        psm=psm,
        tesseract=tesseract,
        output="tsv",
        page_number=page_number,
    )
    layout = _parse_tesseract_tsv(raw_tsv, column_split_x=column_split_x)
    return {
        "text": "\n".join(line["text"] for line in layout["lines"]).strip(),
        "layout": layout,
    }


def ocr_sample(
    path: str | Path,
    pages: Iterable[tuple[int, int]] = DEFAULT_SAMPLE_RANGES,
    *,
    dpi: int = 300,
    language: str = "eng",
    psm: int = 6,
    tesseract: str = "tesseract",
) -> dict:
    source_path = Path(path)
    source_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    range_list = list(pages)
    with fitz.open(source_path) as document:
        page_count = len(document)
        page_numbers = expand_page_ranges(range_list, page_count)
        version = tesseract_version(tesseract) if shutil.which(tesseract) else None
        output = []
        for page_number in page_numbers:
            text = ocr_page(
                document,
                page_number,
                dpi=dpi,
                language=language,
                psm=psm,
                tesseract=tesseract,
            )
            output.append(
                {
                    "page": page_number,
                    "text": text,
                    "status": "needs_review",
                    "issues": [
                        "ocr_text_requires_manual_review",
                        "answer_highlight_requires_manual_review",
                        "option_boundaries_require_manual_review",
                    ],
                }
            )
    return {
        "source": {
            "filename": source_path.name,
            "sha256": source_hash,
            "pages": page_count,
        },
        "ocr": {
            "engine": "tesseract",
            "version": version,
            "language": language,
            "dpi": dpi,
            "psm": psm,
        },
        "sampleRanges": [list(item) for item in range_list],
        "reviewStatus": "needs_review",
        "pages": output,
    }


def ocr_layout_sample(
    path: str | Path,
    pages: Iterable[tuple[int, int]] = DEFAULT_SAMPLE_RANGES,
    *,
    dpi: int = 300,
    language: str = "eng",
    psm: int = 6,
    tesseract: str = "tesseract",
    column_split_x: int = DEFAULT_COLUMN_SPLIT_X,
) -> dict[str, Any]:
    """Create a review-only OCR report with recoverable table columns."""

    source_path = Path(path)
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    range_list = list(pages)
    with fitz.open(source_path) as document:
        page_count = len(document)
        page_numbers = expand_page_ranges(range_list, page_count)
        version = tesseract_version(tesseract) if shutil.which(tesseract) else None
        output = []
        for page_number in page_numbers:
            page_result = ocr_page_layout(
                document,
                page_number,
                dpi=dpi,
                language=language,
                psm=psm,
                tesseract=tesseract,
                column_split_x=column_split_x,
            )
            output.append(
                {
                    "page": page_number,
                    "text": page_result["text"],
                    "layout": page_result["layout"],
                    "status": "needs_review",
                    "issues": [
                        "ocr_text_requires_manual_review",
                        "ocr_layout_requires_manual_review",
                        "answer_highlight_requires_manual_review",
                        "option_boundaries_require_manual_review",
                    ],
                }
            )
    return {
        "source": {
            "filename": source_path.name,
            "sha256": source_hash,
            "pages": page_count,
        },
        "ocr": {
            "engine": "tesseract",
            "version": version,
            "language": language,
            "dpi": dpi,
            "psm": psm,
            "layout": "tsv",
            "columnSplitX": column_split_x,
        },
        "sampleRanges": [list(item) for item in range_list],
        "reviewStatus": "needs_review",
        "pages": output,
    }

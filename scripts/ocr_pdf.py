"""Command-line entry point for the conservative scanned-PDF OCR workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ocr import (
    DEFAULT_COLUMN_SPLIT_X,
    DEFAULT_PSM,
    DEFAULT_SAMPLE_RANGES,
    ocr_layout_sample,
    ocr_sample,
)


def parse_ranges(value: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for item in value.split(","):
        bounds = item.strip().split("-", 1)
        if len(bounds) == 1:
            start = end = int(bounds[0])
        else:
            start, end = (int(bound) for bound in bounds)
        ranges.append((start, end))
    return ranges


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--pages", default="1-10,216-225,426-435")
    parser.add_argument("--output", type=Path, default=Path(".local/ocr-report.json"))
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--language", default="eng")
    parser.add_argument("--psm", type=int, default=DEFAULT_PSM)
    parser.add_argument(
        "--layout",
        action="store_true",
        help="retain Tesseract TSV coordinates and split the question column",
    )
    parser.add_argument("--column-split-x", type=int, default=DEFAULT_COLUMN_SPLIT_X)
    args = parser.parse_args()
    ranges = parse_ranges(args.pages) if args.pages else list(DEFAULT_SAMPLE_RANGES)
    if args.layout:
        report = ocr_layout_sample(
            args.pdf,
            ranges,
            dpi=args.dpi,
            language=args.language,
            psm=args.psm,
            column_split_x=args.column_split_x,
        )
    else:
        report = ocr_sample(
            args.pdf,
            ranges,
            dpi=args.dpi,
            language=args.language,
            psm=args.psm,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "pages": len(report["pages"]), "reviewStatus": report["reviewStatus"]}, indent=2))


if __name__ == "__main__":
    main()

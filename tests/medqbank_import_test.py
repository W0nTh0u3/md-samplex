import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import fitz

from scripts.medqbank_import import (
    _add_answer_block,
    _new_record,
    _resolve_answer,
    _write_question_text,
    parse_medqbank,
)
from scripts.extract import validate


def add_grid(page, rows, *, top=60, bottom=800, left=50, split=280, right=545):
    """Draw a ruled two-column fixture and return each row's coordinates."""

    row_height = (bottom - top) / len(rows)
    boundaries = [top + row_height * index for index in range(len(rows) + 1)]
    for y in boundaries:
        page.draw_line((left, y), (right, y), color=(0, 0, 0), width=0.7)
    for x in (left, split, right):
        page.draw_line((x, top), (x, bottom), color=(0, 0, 0), width=0.7)

    result = []
    for index, (left_text, right_text) in enumerate(rows):
        y0, y1 = boundaries[index], boundaries[index + 1]
        if left_text:
            page.insert_textbox(
                fitz.Rect(left + 6, y0 + 6, split - 6, y1 - 6),
                left_text,
                fontsize=8.5,
                lineheight=1.25,
            )
        if right_text:
            page.insert_textbox(
                fitz.Rect(split + 6, y0 + 6, right - 6, y1 - 6),
                right_text,
                fontsize=8.5,
                lineheight=1.25,
            )
        result.append((y0, y1))
    return result


def insert_question_row(page, rect, stem, options):
    y = rect[0] + 14
    page.insert_text((56, y), stem, fontsize=8.5)
    for index, option in enumerate(options):
        page.insert_text((56, y + 30 + index * 37), option, fontsize=8.5)


class MedqbankImportTests(unittest.TestCase):
    def test_two_column_unlabeled_and_cross_page_continuation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf_path = root / "fixture.pdf"
            image_path = root / "figure.png"
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 80))
            pixmap.clear_with(245)
            pixmap.save(image_path)

            document = fitz.open()
            divider = document.new_page(width=595, height=842)
            divider.insert_text((190, 350), "BIOCHEMISTRY", fontsize=24)

            first = document.new_page(width=595, height=1050)
            boxes = add_grid(
                first,
                [
                    ("", "BIOCHEMISTRY – OCTOBER 2025"),
                    (
                        "Which source choice is correct?\nA. Alpha\nB. Beta\nC. Gamma\nD. Delta",
                        "Beta\nSelectable source explanation.",
                    ),
                    (
                        "",
                        "Second choice\nUnnumbered option explanation.",
                    ),
                    (
                        "Which continuation choice is correct?",
                        "",
                    ),
                    ("", ""),
                ],
                bottom=1000,
            )
            insert_question_row(
                first,
                boxes[2],
                "Which source choice is also correct?",
                ["First choice", "Second choice", "Third choice", "Fourth choice"],
            )
            first.insert_image(
                fitz.Rect(350, boxes[1][0] + 95, 470, boxes[1][0] + 175),
                filename=str(image_path),
            )
            first.insert_image(
                fitz.Rect(190, boxes[1][0] + 147, 250, boxes[1][0] + 185),
                filename=str(image_path),
            )

            continuation = document.new_page(width=595, height=842)
            add_grid(
                continuation,
                [
                    (
                        "A. Alpha\nB. Beta\nC. Gamma\nD. Delta",
                        "Delta\nContinuation explanation.",
                    ),
                ],
                top=60,
                bottom=800,
            )
            # A sizeable visual-only page is retained in the report but cannot
            # become a scored item without a question cell.
            visual_only = document.new_page(width=595, height=842)
            visual_only.insert_image(
                fitz.Rect(100, 150, 420, 370), filename=str(image_path)
            )
            visual_only.insert_image(
                fitz.Rect(100, 150, 420, 370), filename=str(image_path)
            )
            document.save(pdf_path)
            document.close()

            records, report, manifest_path = parse_medqbank(
                pdf_path,
                asset_dir=root / "assets",
                candidate_dir=root / "candidates",
                visual_manifest_path=root / "visual-manifest.json",
            )
            for record in records:
                validate(record)

            by_number = {record["originalNumber"]: record for record in records}
            self.assertEqual(report["sectionsFound"], 1)
            self.assertEqual(report["sectionRecordCounts"]["biochemistry"], 3)
            self.assertEqual(by_number[1]["correctChoice"], "B")
            self.assertEqual(by_number[1]["explanation"], "Selectable source explanation.")
            self.assertEqual(
                by_number[1]["sources"][0]["metadata"]["sectionDate"],
                "October 2025",
            )
            self.assertIn("source_visual_requires_review", by_number[1]["issues"])
            self.assertEqual(by_number[2]["correctChoice"], "B")
            self.assertEqual(
                [choice["text"] for choice in by_number[2]["choices"]],
                ["First choice", "Second choice", "Third choice", "Fourth choice"],
            )
            self.assertEqual(by_number[3]["correctChoice"], "D")
            self.assertEqual(by_number[3]["sources"][0]["pages"], [2, 3])
            self.assertEqual(by_number[3]["sources"][0]["answerPages"], [3])
            self.assertNotIn("question_options_unresolved", by_number[3]["issues"])
            self.assertFalse(
                any("row" in item for item in report["visualOnlyRows"]),
                "a blank table row must not be called visual-only because another row has an image",
            )
            self.assertIn(
                {"page": 4, "reason": "visual_page_without_question_table"},
                report["visualOnlyRows"],
            )
            self.assertEqual(len(report["unassignedVisuals"]), 1)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["assets"]), 1)
            asset = manifest["assets"][0]
            self.assertEqual(asset["visibility"], "feedback")
            self.assertEqual(
                hashlib.sha256(Path(asset["localPath"]).read_bytes()).hexdigest(),
                asset["sha256"],
            )
            self.assertEqual(asset["source"]["pages"], [2])
            self.assertTrue(asset["alt"])
            self.assertEqual(report["questionVisualCandidateCount"], 1)
            candidate = report["questionVisualCandidates"][0]
            self.assertEqual(candidate["questionId"], by_number[1]["id"])
            self.assertEqual(
                hashlib.sha256(Path(candidate["path"]).read_bytes()).hexdigest(),
                candidate["sha256"],
            )

    def test_missing_ambiguous_and_multiple_response_keys_fail_closed(self):
        choices = [
            ("A", "Alpha"),
            ("B", "Beta"),
            ("C", "Gamma"),
            ("D", "Delta"),
        ]
        missing = _new_record("biochemistry", 1, "source.pdf", 5, "October 2025")
        _write_question_text(missing, "Which answer is supported?", choices)
        _add_answer_block(missing, "source.pdf", 5, "Not an option\nSource explanation.")
        self.assertIsNone(missing["correctChoice"])
        self.assertIn("answer_text_did_not_match_unique_choice", missing["issues"])
        self.assertIn("Source explanation", missing["explanation"])

        no_key = _new_record("biochemistry", 4, "source.pdf", 8, "October 2025")
        _write_question_text(no_key, "Which answer is supported?", choices)
        validate(no_key)
        self.assertIsNone(no_key["correctChoice"])
        self.assertIn("missing_answer", no_key["issues"])
        self.assertEqual(no_key["status"], "needs_review")

        ambiguous = _new_record("biochemistry", 2, "source.pdf", 6, "October 2025")
        duplicate_choices = [("A", "Same"), ("B", "Same"), ("C", "Third"), ("D", "Fourth")]
        _write_question_text(ambiguous, "Which answer is supported?", duplicate_choices)
        _add_answer_block(ambiguous, "source.pdf", 6, "Same\nSource explanation.")
        self.assertIsNone(ambiguous["correctChoice"])
        self.assertIn("ambiguous_answer_text_matches_multiple_choices", ambiguous["issues"])

        multiple = _new_record("biochemistry", 3, "source.pdf", 7, "October 2025")
        _write_question_text(
            multiple,
            "Select all that apply to this source question?",
            choices,
        )
        _add_answer_block(multiple, "source.pdf", 7, "Alpha\nSource explanation.")
        self.assertIsNone(multiple["correctChoice"])
        self.assertIn("multiple_response_requires_review", multiple["issues"])


if __name__ == "__main__":
    unittest.main()

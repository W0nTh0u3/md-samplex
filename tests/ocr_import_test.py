import unittest

from scripts.ocr_import import _is_layout_noise_line, parse_ocr_report


class OcrImportTests(unittest.TestCase):
    def test_explicit_key_and_option_sequence_stay_review_only(self):
        report = {
            "source": {
                "filename": "scanned.pdf",
                "sha256": "a" * 64,
                "pages": 1,
            },
            "ocr": {
                "engine": "tesseract",
                "version": "tesseract test",
                "language": "eng",
                "dpi": 300,
                "psm": 6,
            },
            "reviewStatus": "needs_review",
            "pages": [
                {
                    "page": 1,
                    "text": (
                        "1. Which choice is correct? B B. Correct option\n"
                        "The source rationale explains the answer.\n"
                        "A. First option\n"
                        "B. Correct option\n"
                        "C. Third option\n"
                        "D. Fourth option\n"
                        "Reference: source"
                    ),
                    "status": "needs_review",
                    "issues": ["ocr_text_requires_manual_review"],
                }
            ],
        }

        output = parse_ocr_report(report, sections=[("test", 1, 1)])
        record = output["records"][0]

        self.assertEqual(record["correctChoice"], "B")
        self.assertEqual("".join(choice["label"] for choice in record["choices"]), "ABCD")
        self.assertIn("source rationale", record["explanation"])
        self.assertEqual(record["status"], "needs_review")
        self.assertIn("ocr_layout_requires_manual_review", record["issues"])
        self.assertEqual(record["sources"][0]["pages"], [1])
        self.assertEqual(output["report"]["total"], 100)
        self.assertEqual(output["report"]["placeholders"], 99)
        self.assertTrue(output["report"]["allNeedsReview"])

    def test_layout_columns_keep_options_out_of_rationale(self):
        lines = [
            {
                "top": 100,
                "left": 100,
                "text": "1. Which choice is correct? B B. Correct option",
                "leftText": "1. Which choice is correct?",
                "rightText": "B B. Correct option",
                "words": [],
            },
            {
                "top": 150,
                "left": 100,
                "text": "A. First option The rationale starts here.",
                "leftText": "A. First option",
                "rightText": "The rationale starts here.",
                "words": [],
            },
            {
                "top": 200,
                "left": 100,
                "text": "B. Correct option More rationale.",
                "leftText": "B. Correct option",
                "rightText": "More rationale.",
                "words": [],
            },
            {
                "top": 250,
                "left": 100,
                "text": "C. Third option",
                "leftText": "C. Third option",
                "rightText": "",
                "words": [],
            },
            {
                "top": 300,
                "left": 100,
                "text": "D. Fourth option",
                "leftText": "D. Fourth option",
                "rightText": "Reference: source",
                "words": [],
            },
        ]
        report = {
            "source": {
                "filename": "scanned.pdf",
                "sha256": "b" * 64,
                "pages": 1,
            },
            "ocr": {
                "engine": "tesseract",
                "version": "tesseract test",
                "language": "eng",
                "dpi": 300,
                "psm": 6,
                "layout": "tsv",
                "columnSplitX": 1130,
            },
            "reviewStatus": "needs_review",
            "pages": [
                {
                    "page": 1,
                    "text": "\n".join(line["text"] for line in lines),
                    "layout": {"columnSplitX": 1130, "lines": lines},
                    "ocr": {
                        "engine": "tesseract",
                        "version": "tesseract test",
                        "language": "eng",
                        "dpi": 300,
                        "psm": 4,
                        "layout": "tsv",
                        "columnSplitX": 1130,
                    },
                    "status": "needs_review",
                    "issues": [],
                }
            ],
        }

        output = parse_ocr_report(report, sections=[("test", 1, 1)])
        record = output["records"][0]

        self.assertEqual(record["stem"], "Which choice is correct?")
        self.assertEqual(
            [(choice["label"], choice["text"]) for choice in record["choices"]],
            [
                ("A", "First option"),
                ("B", "Correct option"),
                ("C", "Third option"),
                ("D", "Fourth option"),
            ],
        )
        self.assertEqual(record["correctChoice"], "B")
        self.assertEqual(record["sources"][0]["metadata"]["ocrPsm"], "4")
        self.assertEqual(
            record["sources"][0]["metadata"]["ocrConfigurations"][0]["pages"],
            [1],
        )
        self.assertIn("rationale starts here", record["explanation"])
        self.assertNotIn("rationale", " ".join(choice["text"] for choice in record["choices"]))

    def test_comma_question_separator_recovers_ocr_boundary(self):
        report = {
            "source": {
                "filename": "scanned.pdf",
                "sha256": "c" * 64,
                "pages": 1,
            },
            "ocr": {
                "engine": "tesseract",
                "version": "tesseract test",
                "language": "eng",
                "dpi": 300,
                "psm": 4,
            },
            "reviewStatus": "needs_review",
            "pages": [
                {
                    "page": 1,
                    "text": (
                        "1, Which choice is correct? A A. First option\n"
                        "A. First option\n"
                        "B. Second option\n"
                        "C. Third option\n"
                        "D. Fourth option\n"
                    ),
                    "status": "needs_review",
                    "issues": ["ocr_text_requires_manual_review"],
                }
            ],
        }

        output = parse_ocr_report(report, sections=[("test", 1, 1)])
        record = output["records"][0]

        self.assertEqual(output["report"]["candidateRecords"], 1)
        self.assertEqual(output["report"]["placeholders"], 99)
        self.assertEqual(record["rawQuestionNumber"], 1)
        self.assertEqual(record["stem"], "Which choice is correct?")
        self.assertEqual(record["correctChoice"], "A")
        self.assertIn("ocr_question_boundary_requires_manual_review", record["issues"])

    def test_layout_noise_uses_reported_column_split(self):
        line = {
            "layout": True,
            "text": "x",
            "columnSplitX": 900,
            "words": [{"left": 1000, "confidence": 40}],
        }

        self.assertFalse(_is_layout_noise_line(line))
        line["words"][0]["left"] = 800
        self.assertTrue(_is_layout_noise_line(line))


if __name__ == "__main__":
    unittest.main()

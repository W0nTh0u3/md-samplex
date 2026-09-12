import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from scripts.extract import validate
from scripts.notion_import import discover_export_files, parse_export, parse_export_bundle


ROOT = Path(__file__).resolve().parents[1]


class NotionImportTests(unittest.TestCase):
    def parse(self, filename, subject="biochemistry"):
        records, report = parse_export(
            ROOT / "scripts" / filename,
            subject,
            "https://example.com/notion-export",
        )
        for record in records:
            validate(record)
        return records, report

    def test_per_choice_rationales_and_metadata_are_preserved(self):
        records, report = self.parse("notion-fixture-per-option-rationales.md")
        self.assertEqual(report["format"], "markdown")
        self.assertEqual(records[0]["correctChoice"], "B")
        self.assertEqual(set(records[0]["choiceRationales"]), {"A", "B", "C", "D"})
        self.assertEqual(records[0]["sources"][0]["url"], "https://example.com/notion-export")
        self.assertEqual(records[0]["sources"][0]["metadata"], {"withRatio": False, "forRevision": True})
        self.assertEqual(records[0]["status"], "validated")

    def test_overall_explanation_and_correct_choice_fallback(self):
        records, _ = self.parse("notion-fixture-overall-explanation.md")
        self.assertEqual(records[0]["status"], "validated")
        self.assertNotIn("choiceRationales", records[0])
        self.assertIn("one overall explanation", records[0]["explanation"])

    def test_missing_rationales_and_malformed_formats_fail_closed(self):
        missing, _ = self.parse("notion-fixture-missing-rationales.md")
        self.assertIn("incomplete_choice_rationales", missing[0]["issues"])
        malformed, _ = self.parse("notion-fixture-malformed.md")
        self.assertIn("multiple_response_requires_review", malformed[0]["issues"])
        self.assertEqual(malformed[0]["status"], "needs_review")

    def test_explicit_multiple_key_is_set_valued_and_ambiguous_key_is_quarantined(self):
        records, _ = self.parse("notion-fixture-multiple.md")
        multiple, malformed = records
        self.assertEqual(multiple["answerMode"], "multiple")
        self.assertIsNone(multiple["correctChoice"])
        self.assertEqual(multiple["correctChoices"], ["A", "C"])
        self.assertEqual(multiple["status"], "validated")
        self.assertIn("malformed_multiple_answer_key", malformed["issues"])
        self.assertEqual(malformed["status"], "needs_review")

    def test_html_answer_highlight_is_an_explicit_key(self):
        records, report = self.parse("notion-fixture-answer-highlight.html")
        self.assertEqual(report["format"], "html")
        self.assertEqual(records[0]["correctChoice"], "A")
        self.assertEqual(records[0]["status"], "validated")

    def test_html_green_highlight_and_nested_rationale_lists_are_preserved(self):
        records, _ = self.parse("notion-fixture-nested-rationales.html")
        record = records[0]
        self.assertEqual(record["correctChoice"], "A")
        self.assertEqual("".join(choice["label"] for choice in record["choices"]), "ABCD")
        self.assertIn("Nested source note", record["choiceRationales"]["B"])
        self.assertNotIn("repeated_choice_label", record["issues"])
        self.assertEqual(record["status"], "validated")

    def test_bare_notion_checkbox_metadata_does_not_swallow_subject_text(self):
        records, report = self.parse("notion-fixture-bare-properties.md")
        self.assertEqual(report["properties"], {"withRatio": True})
        self.assertEqual(records[0]["sources"][0]["metadata"], {"withRatio": True})
        self.assertEqual(records[0]["status"], "validated")

    def test_duplicate_fixture_keeps_a_normalized_fingerprint(self):
        records, _ = self.parse("notion-fixture-duplicate.md")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["_raw"].replace(" ", ""), records[1]["_raw"].replace(" ", ""))

    def test_directory_exports_are_sorted_and_keep_relative_source_locators(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "Biochemistry"
            nested.mkdir()
            first = nested / "02-page.md"
            second = root / "01-page.md"
            fixture = (ROOT / "scripts" / "notion-fixture-overall-explanation.md").read_text(
                encoding="utf-8"
            )
            first.write_text(fixture, encoding="utf-8")
            second.write_text(fixture.replace("## 2.", "## 1."), encoding="utf-8")

            self.assertEqual(discover_export_files(root), [second, first])
            records, report = parse_export_bundle(
                root,
                "biochemistry",
                "https://example.com/notion-export",
            )

            self.assertEqual(report["format"], "directory")
            self.assertEqual(report["records"], 2)
            self.assertEqual(
                {record["sources"][0]["filename"] for record in records},
                {"01-page.md", "Biochemistry/02-page.md"},
            )


if __name__ == "__main__":
    unittest.main()

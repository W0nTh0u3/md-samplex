import unittest

from scripts.notion_public_import import parse_snapshot


def _entry(value):
    return {"value": {"value": value, "role": "reader"}}


def _fixture_snapshot(with_green=True, option_highlight=False):
    page_id = "page-biochemistry"
    question_id = "question-1"
    column_list_id = "column-list-1"
    column_id = "column-1"
    option_ids = ["option-a", "option-b", "option-c", "option-d"]
    rationale_ids = ["rationale-a", "rationale-b", "rationale-c", "rationale-d"]
    labels = ["A. Alpha", "B. Beta", "C. Gamma", "D. Delta"]
    blocks = {
        page_id: _entry(
            {
                "id": page_id,
                "type": "page",
                "properties": {"title": [["1 - Biochemistry (Practice Test)"]]},
                "content": [question_id],
            }
        ),
        question_id: _entry(
            {
                "id": question_id,
                "type": "numbered_list",
                "properties": {"title": [["Which option is supported by the source?"]]},
                "content": [column_list_id],
            }
        ),
        column_list_id: _entry(
            {"id": column_list_id, "type": "column_list", "content": [column_id]}
        ),
        column_id: _entry(
            {"id": column_id, "type": "column", "content": option_ids}
        ),
    }
    for option_id, rationale_id, label in zip(option_ids, rationale_ids, labels):
        option = {
            "id": option_id,
            "type": "toggle",
            "properties": {"title": [[label]]},
            "content": [rationale_id],
        }
        if with_green and option_highlight and label.startswith("B."):
            option["format"] = {"block_color": "green_background"}
        blocks[option_id] = _entry(option)
        rationale = {
            "id": rationale_id,
            "type": "text",
            "properties": {"title": [[f"Rationale for {label[0]}"]]},
        }
        if with_green and not option_highlight and label.startswith("B."):
            rationale["format"] = {"block_color": "teal_background"}
        blocks[rationale_id] = _entry(rationale)
    return {
        "source": {"url": "https://example.com/public", "sha256": "fixture"},
        "pages": [{"pageId": page_id, "blocks": blocks}],
    }


class NotionPublicImportTests(unittest.TestCase):
    def test_public_snapshot_preserves_rationales_and_explicit_green_key(self):
        records, report = parse_snapshot(_fixture_snapshot())

        self.assertEqual(report["pages"], 1)
        self.assertEqual(report["records"], 1)
        record = records[0]
        self.assertEqual(record["originalNumber"], 1)
        self.assertEqual(record["correctChoice"], "B")
        self.assertEqual(set(record["choiceRationales"]), {"A", "B", "C", "D"})
        self.assertEqual(record["explanation"], "Rationale for B")
        self.assertIn("public_snapshot_requires_review", record["issues"])
        self.assertEqual(record["status"], "needs_review")

    def test_public_snapshot_does_not_infer_a_missing_highlight(self):
        records, report = parse_snapshot(_fixture_snapshot(with_green=False))

        self.assertEqual(report["issues"]["missing_answer"], 1)
        self.assertIsNone(records[0]["correctChoice"])
        self.assertEqual(records[0]["status"], "needs_review")

    def test_public_snapshot_accepts_option_level_highlight(self):
        records, _ = parse_snapshot(_fixture_snapshot(option_highlight=True))

        self.assertEqual(records[0]["correctChoice"], "B")

    def test_verified_public_snapshot_can_enter_structural_validation(self):
        records, report = parse_snapshot(_fixture_snapshot(), review_only=False)

        self.assertEqual(report["reviewStatus"], "source_annotations_verified")
        self.assertEqual(records[0]["status"], "validated")
        self.assertNotIn("public_snapshot_requires_review", records[0]["issues"])


if __name__ == "__main__":
    unittest.main()

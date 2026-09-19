import unittest

from scripts.ocr_review import _audit_candidate


def audit_context(answer="B"):
    return {
        "number": 1,
        "start": {"rawNumber": 1},
        "pages": [7],
        "answer": {"key": answer} if answer else None,
        "choices": [
            {"label": "A", "text": "First option"},
            {"label": "B", "text": "Correct option"},
            {"label": "C", "text": "Third option"},
            {"label": "D", "text": "Fourth option"},
        ],
    }


def audit_record(answer="B", choices=None):
    return {
        "id": "ocr-ple-test-0001",
        "originalNumber": 1,
        "rawQuestionNumber": 1,
        "stem": "Which option is supported by the source?",
        "rawText": "Which option is supported by the source?",
        "choices": choices
        or [
            {"label": "A", "text": "First option"},
            {"label": "B", "text": "Correct option"},
            {"label": "C", "text": "Third option"},
            {"label": "D", "text": "Fourth option"},
        ],
        "correctChoice": answer,
        "sources": [{"pages": [7]}],
    }


class OcrReviewTests(unittest.TestCase):
    def test_source_answer_pairing_is_checked_without_clinical_inference(self):
        result = _audit_candidate(audit_record(answer="A"), audit_context(answer="B"))

        self.assertEqual(result["status"], "mismatch")
        self.assertIn("source_answer_key_mismatch_requires_review", result["issues"])
        self.assertEqual(result["sourceAnswerKey"], "B")
        self.assertEqual(result["storedAnswerKey"], "A")

    def test_incomplete_source_choices_remain_needs_review(self):
        choices = [
            {"label": "A", "text": "First option"},
            {"label": "B", "text": ""},
            {"label": "C", "text": "Third option"},
            {"label": "D", "text": "Fourth option"},
        ]
        result = _audit_candidate(
            audit_record(answer="B", choices=choices),
            {**audit_context(answer="B"), "choices": choices},
        )

        self.assertEqual(result["status"], "needs_review")
        self.assertIn("source_choice_set_incomplete_requires_review", result["issues"])
        self.assertTrue(result["checks"]["answerKeyPairing"])

    def test_missing_source_answer_is_unresolved_not_guessed(self):
        result = _audit_candidate(audit_record(answer=None), audit_context(answer=None))

        self.assertEqual(result["status"], "needs_review")
        self.assertIn("source_answer_key_unresolved_requires_review", result["issues"])
        self.assertIsNone(result["sourceAnswerKey"])


if __name__ == "__main__":
    unittest.main()

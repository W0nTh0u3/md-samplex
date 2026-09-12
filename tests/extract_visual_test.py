import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.extract import (
    _manifest_asset_path,
    apply_visual_manifest,
    load_visual_manifest,
    validate,
)

ROOT = Path(__file__).resolve().parents[1]


def record(question_id, stem):
    return {
        "id": question_id,
        "subject": "biochemistry",
        "originalNumber": 1,
        "stem": "",
        "choices": [],
        "correctChoice": None,
        "explanation": "The source explanation is retained.",
        "sources": [{"filename": "source.pdf", "pages": [12], "answerPages": [13]}],
        "status": "needs_review",
        "issues": [],
        "_raw": "\n".join(
            [
                stem,
                "A. First supported finding",
                "B. Distractor finding",
                "C. Second supported finding",
                "D. Another distractor",
            ]
        ),
        "_namespace": "fixture",
    }


class VisualManifestTests(unittest.TestCase):
    def test_public_asset_paths_resolve_inside_the_repository_asset_root(self):
        self.assertEqual(
            _manifest_asset_path("/assets/diagram.png"),
            ROOT / "public" / "assets" / "diagram.png",
        )

    def manifest(self, root, assets, questions=None, shared_cases=None):
        path = root / "visual-manifest.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "assets": assets,
                    "questions": questions or [],
                    "sharedCases": shared_cases or [],
                }
            ),
            encoding="utf-8",
        )
        return path

    def asset(self, root, asset_id="neutral", *, answer_marked=False):
        image = root / f"{asset_id}.png"
        image.write_bytes(b"verified clinical visual")
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        return {
            "id": asset_id,
            "path": f"/assets/{asset_id}.png",
            "localPath": str(image),
            "sha256": digest,
            "kind": "diagram",
            "alt": "A source diagram showing the relevant findings.",
            "caption": "Verified source diagram",
            "source": {"filename": "source.pdf", "pages": [12]},
            **({"answerMarked": True} if answer_marked else {}),
        }

    def test_verified_visual_and_multiple_key_can_promote_a_record(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.manifest(
                root,
                [self.asset(root)],
                [
                    {
                        "questionId": "visual-q",
                        "visualIds": ["neutral"],
                        "requiredVisualIds": ["neutral"],
                        "verified": True,
                        "answerMode": "multiple",
                        "correctChoices": ["A", "C"],
                    }
                ],
            )
            manifest = load_visual_manifest(manifest_path)
            records = [
                record(
                    "visual-q",
                    "Select all that apply to the diagram shown below.",
                )
            ]
            validate(records[0])
            self.assertIn("required_figure_or_table_requires_review", records[0]["issues"])

            inventory = {}
            apply_visual_manifest(records, manifest, inventory)
            validate(records[0])

            self.assertEqual(records[0]["status"], "validated")
            self.assertEqual(records[0]["answerMode"], "multiple")
            self.assertIsNone(records[0]["correctChoice"])
            self.assertEqual(records[0]["correctChoices"], ["A", "C"])
            self.assertEqual(records[0]["visuals"][0]["id"], "neutral")
            self.assertEqual(
                records[0]["visuals"][0]["sourceLocator"],
                "source.pdf pages 12",
            )
            self.assertEqual(inventory["visuals"]["assets"][0]["id"], "neutral")

    def test_answer_marked_visual_is_feedback_only_and_cannot_satisfy_dependency(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.manifest(
                root,
                [self.asset(root, answer_marked=True)],
                [
                    {
                        "questionId": "marked-q",
                        "requiredVisualIds": ["neutral"],
                        "verified": True,
                        "answerMode": "multiple",
                        "correctChoices": ["A", "C"],
                    }
                ],
            )
            manifest = load_visual_manifest(manifest_path)
            records = [record("marked-q", "Select all that apply to the diagram shown below.")]
            validate(records[0])
            apply_visual_manifest(records, manifest, {})
            validate(records[0])

            self.assertEqual(records[0]["status"], "needs_review")
            self.assertIn("answer_marked_visual_feedback_only", records[0]["issues"])
            self.assertIn("visual_dependency_requires_review", records[0]["issues"])
            self.assertEqual(records[0]["visuals"][0]["visibility"], "feedback")

    def test_unverified_and_missing_assets_remain_review_variants(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid_asset = self.asset(root, "missing")
            invalid_asset["sha256"] = "0" * 64
            manifest_path = self.manifest(
                root,
                [invalid_asset],
                [
                    {
                        "questionId": "review-q",
                        "requiredVisualIds": ["missing"],
                        "verified": False,
                    }
                ],
            )
            manifest = load_visual_manifest(manifest_path)
            records = [record("review-q", "Which finding is supported by the source?")]
            validate(records[0])
            inventory = {}
            apply_visual_manifest(records, manifest, inventory)

            self.assertEqual(records[0]["status"], "needs_review")
            self.assertIn("visual_dependency_requires_review", records[0]["issues"])
            self.assertTrue(manifest["errors"])
            self.assertEqual(inventory["visuals"]["dependencies"][0]["invalid"][0]["id"], "missing")

    def test_valid_but_unverified_visual_cannot_enter_the_question_view(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.manifest(
                root,
                [self.asset(root)],
                [
                    {
                        "questionId": "unverified-q",
                        "requiredVisualIds": ["neutral"],
                        "verified": False,
                    }
                ],
            )
            manifest = load_visual_manifest(manifest_path)
            records = [
                record(
                    "unverified-q",
                    "Select all that apply to the diagram shown below.",
                )
            ]
            validate(records[0])
            apply_visual_manifest(records, manifest, {})
            validate(records[0])

            self.assertEqual(records[0]["status"], "needs_review")
            self.assertIn("visual_dependency_requires_review", records[0]["issues"])

    def test_duplicate_asset_ids_fail_closed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.manifest(
                root,
                [self.asset(root), self.asset(root)],
                [
                    {
                        "questionId": "duplicate-q",
                        "requiredVisualIds": ["neutral"],
                        "verified": True,
                    }
                ],
            )
            manifest = load_visual_manifest(manifest_path)
            records = [record("duplicate-q", "Which finding is supported by the source?")]
            validate(records[0])
            apply_visual_manifest(records, manifest, {})
            validate(records[0])

            self.assertEqual(records[0]["status"], "needs_review")
            self.assertTrue(manifest["errors"])
            self.assertIn("visual_dependency_requires_review", records[0]["issues"])

    def test_answer_marked_shared_case_visual_cannot_satisfy_required_context(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.manifest(
                root,
                [self.asset(root, answer_marked=True)],
                shared_cases=[
                    {
                        "sharedCaseId": "case-1",
                        "requiredVisualIds": ["neutral"],
                        "verified": True,
                    }
                ],
            )
            manifest = load_visual_manifest(manifest_path)
            shared_case_record = record(
                "case-q",
                "Which finding is supported by the source?",
            )
            shared_case_record["sharedCase"] = {
                "id": "case-1",
                "text": "A shared source case.",
            }
            validate(shared_case_record)
            apply_visual_manifest([shared_case_record], manifest, {})
            validate(shared_case_record)

            self.assertEqual(shared_case_record["status"], "needs_review")
            self.assertIn(
                "shared_case_visual_dependency_requires_review",
                shared_case_record["issues"],
            )
            self.assertIn(
                "answer_marked_visual_feedback_only",
                shared_case_record["issues"],
            )
            self.assertEqual(
                shared_case_record["sharedCase"]["visuals"][0]["visibility"],
                "feedback",
            )

    def test_answer_contract_rejects_multi_character_choice_labels(self):
        invalid = record(
            "invalid-key",
            "Which finding is supported by the source?",
        )
        invalid["answerMode"] = "multiple"
        invalid["correctChoices"] = ["AB"]
        invalid["_multiple_explicit"] = True
        validate(invalid)

        self.assertIn("invalid_multiple_key", invalid["issues"])
        self.assertEqual(invalid["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()

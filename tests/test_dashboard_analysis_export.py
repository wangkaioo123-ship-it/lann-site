import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.run_server_batch import COMMANDS
from services.dashboard_analysis_export import (
    EXPORT_SCHEMA_VERSION,
    DashboardAnalysisExportError,
    publish_dashboard_analysis_export,
)
from services.professional_analysis import build_analysis_catalog


RUN_ID = "0123456789abcdef0123"
MONTH = "2026-07"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def valid_source(root: Path) -> tuple[Path, Path]:
    source_root = root / "source"
    run_root = source_root / MONTH / RUN_ID
    operating_hash = "1" * 64
    workforce_hash = "2" * 64
    contract_hash = "3" * 64
    manifest = {
        "schema_version": "franchise-operating-run/v0.1",
        "run_id": RUN_ID,
        "run_month": MONTH,
        "status": "ready_for_business_review",
        "generated_at": "2026-08-01T00:00:00+00:00",
        "rule_version": "franchise-operating-monthly/v0.1",
        "candidate_rule_version": "franchise-operating-check/v0.1",
        "review_schema_version": "franchise-operating-review/v0.1",
        "business_review_schema_version": "franchise-operating-business-review/v0.2",
        "three_month_operating_schema_version": "franchise-store-three-month-operating/v0.1",
        "analysis_catalog_schema_version": "professional-analysis-catalog/v0.1",
        "analysis_record_schema_version": "professional-analysis-record/v0.1",
        "workforce_contract_version": "store-workforce-monthly-contract/v1",
        "inputs": {
            "operating": {
                "path": "operating.csv",
                "sha256": operating_hash,
                "row_count": 1,
            },
            "workforce": {
                "path": "workforce.csv",
                "sha256": workforce_hash,
                "row_count": 1,
                "data_version": "store-workforce-monthly/v1",
                "source_commit": "a" * 40,
                "contract_sha256": contract_hash,
            },
            "candidate_freeze": None,
        },
        "candidate_count": 0,
        "dashboard_write_allowed": False,
        "outputs": {
            "gate": "data_gate.json",
            "review_json": "review.json",
            "review_markdown": "review.md",
            "business_review_json": "business_review.json",
            "business_review_markdown": "business_review.md",
            "analysis_catalog_json": "analysis_catalog.json",
            "candidate_csv": None,
        },
    }
    business = {
        "schema_version": "franchise-operating-business-review/v0.2",
        "status": "ready_for_business_review",
        "target_month": MONTH,
        "dashboard_write_allowed": False,
        "data_gate": {"operating": {"ready": True}, "workforce": {"ready": True}},
        "stores": [],
    }
    review = {
        "schema_version": "franchise-operating-review/v0.1",
        "status": "ready_for_business_review",
        "target_month": MONTH,
        "dashboard_write_allowed": False,
        "candidate_count": 0,
        "candidates": [],
    }
    catalog = build_analysis_catalog(business, manifest)
    write_json(source_root / "latest_success.json", {
        "run_id": RUN_ID,
        "run_month": MONTH,
        "status": "ready_for_business_review",
        "path": "/internal/path/not/exported",
    })
    write_json(run_root / "manifest.json", manifest)
    write_json(run_root / "business_review.json", business)
    write_json(run_root / "analysis_catalog.json", catalog)
    write_json(run_root / "review.json", review)
    (run_root / "not-exported.txt").write_text("private", encoding="utf-8")
    summary = root / "site_performance_summary_bi_feishu_rent.csv"
    summary.write_text("store_id,revenue\nL0001,100000\n", encoding="utf-8")
    return source_root, summary


class DashboardAnalysisExportTests(unittest.TestCase):
    def test_publishes_only_allowlisted_run_files_and_normalized_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, summary = valid_source(root)
            export = root / "export"
            manifest = publish_dashboard_analysis_export(
                source,
                export,
                summary,
                now=datetime(2026, 9, 2, tzinfo=timezone.utc),
            )
            review_root = export / "franchise_operating_reviews"
            pointer = json.loads((review_root / "latest_success.json").read_text(encoding="utf-8"))
            exported_names = {
                path.name for path in (review_root / MONTH / RUN_ID).iterdir()
            }

            self.assertEqual(manifest["schema_version"], EXPORT_SCHEMA_VERSION)
            self.assertFalse(manifest["dashboard_write_allowed"])
            self.assertEqual(pointer["run_id"], RUN_ID)
            self.assertNotIn("path", pointer)
            self.assertEqual(
                exported_names,
                {"manifest.json", "business_review.json", "analysis_catalog.json", "review.json"},
            )
            self.assertTrue((export / "site_performance_summary_bi_feishu_rent.csv").is_file())
            self.assertEqual(len(manifest["files"]), 4)
            self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest["files"]))

    def test_rejects_write_enabled_bundle_and_preserves_previous_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, summary = valid_source(root)
            export = root / "export"
            previous_pointer = {"run_month": "2026-06", "run_id": "a" * 20}
            write_json(export / "franchise_operating_reviews" / "latest_success.json", previous_pointer)
            business_path = source / MONTH / RUN_ID / "business_review.json"
            business = json.loads(business_path.read_text(encoding="utf-8"))
            business["dashboard_write_allowed"] = True
            write_json(business_path, business)

            with self.assertRaises(DashboardAnalysisExportError):
                publish_dashboard_analysis_export(source, export, summary)

            current = json.loads(
                (export / "franchise_operating_reviews" / "latest_success.json").read_text(encoding="utf-8")
            )
            self.assertEqual(current, previous_pointer)

    def test_rejects_mutation_of_existing_immutable_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, summary = valid_source(root)
            export = root / "export"
            publish_dashboard_analysis_export(source, export, summary)
            target = export / "franchise_operating_reviews" / MONTH / RUN_ID / "review.json"
            target.write_text("{}", encoding="utf-8")

            with self.assertRaises(DashboardAnalysisExportError):
                publish_dashboard_analysis_export(source, export, summary)

    def test_export_manifest_hash_matches_normalized_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, _ = valid_source(root)
            export = root / "export"
            manifest = publish_dashboard_analysis_export(source, export, summary_path=None)
            pointer_bytes = (
                export / "franchise_operating_reviews" / "latest_success.json"
            ).read_bytes()
            self.assertEqual(
                manifest["latest_success_sha256"],
                hashlib.sha256(pointer_bytes).hexdigest(),
            )
            self.assertEqual(manifest["summary"]["status"], "not_published")

    def test_rejects_export_root_that_contains_staging_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, summary = valid_source(root)
            with self.assertRaises(DashboardAnalysisExportError):
                publish_dashboard_analysis_export(source, root, summary)

    def test_rejects_arbitrary_summary_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, _ = valid_source(root)
            arbitrary = root / "other.csv"
            arbitrary.write_text("private", encoding="utf-8")
            with self.assertRaises(DashboardAnalysisExportError):
                publish_dashboard_analysis_export(source, root / "export", arbitrary)

    def test_server_batch_publishes_only_after_review_build(self):
        modules = [command[2] for command in COMMANDS]
        self.assertEqual(modules[-2:], [
            "scripts.build_franchise_operating_review",
            "scripts.publish_dashboard_analysis_export",
        ])


if __name__ == "__main__":
    unittest.main()

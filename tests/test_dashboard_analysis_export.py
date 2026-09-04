import hashlib
import csv
import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

from scripts.run_server_batch import COMMANDS
from services.dashboard_analysis_export import (
    EXPORT_SCHEMA_VERSION,
    SUMMARY_COLUMNS,
    SUMMARY_FILE_NAME,
    DashboardAnalysisExportError,
    publish_dashboard_analysis_export as _publish_dashboard_analysis_export,
)
from services.professional_analysis import build_analysis_catalog


RUN_ID = "0123456789abcdef0123"
MONTH = "2026-07"


def valid_source_data():
    return {
        "sync_status": "fresh",
        "stale": False,
        "package_id": "package-2026-07-v1",
        "data_period": MONTH,
        "generated_at": "2026-09-01T08:00:00+08:00",
        "manifest_sha256": "f" * 64,
    }


def publish_dashboard_analysis_export(*args, **kwargs):
    kwargs.setdefault("source_data", valid_source_data())
    return _publish_dashboard_analysis_export(*args, **kwargs)


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
                "column_count": 25,
                "data_version": "store-workforce-monthly/v1",
                "source_commit": "a" * 40,
                "contract_path": "contract.json",
                "contract_sha256": contract_hash,
                "column_mapping": {},
            },
            "candidate_freeze": None,
        },
        "candidate_count": 0,
        "candidate_order": [],
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
        "run_mode": "full_scope_scan",
        "data_cutoff": {"operating_complete_month": MONTH, "workforce_dates": ["2026-08-18"]},
        "data_gate": {
            "operating": {"ready": True, "latest_month": MONTH, "coverage": 1.0, "field_completeness": 1.0, "message": "passed", "rule_version": "franchise-operating-check/v0.1"},
            "workforce": workforce_gate(),
            "workforce_confidence_in_participating_stores": [],
            "review_issues": [],
        },
        "coverage": {"scope_store_count": 0, "workforce_covered_scope_store_count": 0, "participating_store_count": 0, "excluded_store_count": 0},
        "ranking": {"basis": "test", "note": "not a score"},
        "three_month_operating_contract": {
            "schema_version": "franchise-store-three-month-operating/v0.1", "month_count": 3,
            "window_end_month": MONTH, "definition": "test",
            "ratio_policy": {"authoritative_calculation": "known_occupancy_cost_total / operating_revenue", "value_tolerance": 0.00000001, "source_comparison_tolerance": 0.000051, "source_ratio_role": "diagnostic_only"},
            "cost_scope": {"known_occupancy_cost_total_source": "test", "base_rent_and_property_fee_split_available": False, "management_fee_available": False, "financial_profit_calculated": False, "excluded_components": []},
        },
        "candidate_count": 0,
        "fixed_nine_comparison": {"historical_reference_month": "2026-07", "historical_reference_count": 9, "historical_reference_rule_version": "franchise-operating-check/v0.1", "current_month": MONTH, "current_rule_version": "franchise-operating-check/v0.1", "same_month_as_reference": True, "same_rule_version_as_reference": True, "current_candidate_freeze_applied": False, "input_version_check": "sha", "current_mode": "full_scope_scan", "note": "test"},
        "evidence_legend": {"facts": "facts", "statistical_differences": "diff", "proxy_metrics": "proxy", "possible_explanations": "hypothesis", "evidence_gaps": "gaps"},
        "stores": [],
        "excluded_stores": [],
    }
    review = {
        "schema_version": "franchise-operating-review/v0.1",
        "status": "ready_for_business_review",
        "target_month": MONTH,
        "dashboard_write_allowed": False,
        "candidate_count": 0,
        "candidate_order": [],
        "data_gate": {"operating": copy.deepcopy(business["data_gate"]["operating"]), "workforce": workforce_gate(), "issues": []},
        "summary": {"personnel_cross_evidence": {}, "business_decline_without_personnel_support": [], "note": "test"},
        "candidates": [],
        "next_owner": "加盟服务业务 Review",
    }
    catalog = build_analysis_catalog(business, manifest)
    write_json(source_root / "latest_success.json", {
        "run_id": RUN_ID,
        "run_month": MONTH,
        "status": "ready_for_business_review",
        "path": str(run_root),
    })
    write_json(run_root / "manifest.json", manifest)
    write_json(run_root / "business_review.json", business)
    write_json(run_root / "analysis_catalog.json", catalog)
    write_json(run_root / "review.json", review)
    (run_root / "not-exported.txt").write_text("private", encoding="utf-8")
    summary = root / "site_performance_summary_bi_feishu_rent.csv"
    with summary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SUMMARY_COLUMNS)
        writer.writerow(["L0001"] + [""] * (len(SUMMARY_COLUMNS) - 1))
    return source_root, summary


def workforce_gate():
    return {
        "ready": True, "target_month": MONTH, "data_cutoff_dates": ["2026-08-18"],
        "source_row_count": 1, "source_store_count": 1, "source_months": [MONTH],
        "scope_store_count": 0, "covered_scope_store_count": 0, "missing_scope_stores": [],
        "scope_coverage": 1.0, "mapping_completeness": 1.0, "field_completeness": 1.0,
        "confidence_levels": [], "candidate_store_count": 0, "missing_candidate_stores": [],
        "trend_only_months": [], "limitations": [], "issues": [], "message": "passed",
    }


class DashboardAnalysisExportTests(unittest.TestCase):
    def test_requires_source_data_for_integrated_ready_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, summary = valid_source(root)
            with self.assertRaisesRegex(DashboardAnalysisExportError, "source_data"):
                _publish_dashboard_analysis_export(source, root / "export", summary)
            self.assertFalse((root / "export" / "franchise_operating_reviews" / "latest_success.json").exists())

    def test_rejects_non_boolean_or_false_ready_gates(self):
        invalid_values = ("true", "false", 1, 0, None, False)
        for gate_name in ("operating", "workforce"):
            for invalid in invalid_values:
                with self.subTest(gate=gate_name, value=invalid), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    source, summary = valid_source(root)
                    business_path = source / MONTH / RUN_ID / "business_review.json"
                    business = json.loads(business_path.read_text(encoding="utf-8"))
                    business["data_gate"][gate_name]["ready"] = invalid
                    write_json(business_path, business)
                    with self.assertRaisesRegex(DashboardAnalysisExportError, "ready"):
                        publish_dashboard_analysis_export(source, root / "export", summary)

    def test_source_data_is_identical_in_manifest_and_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, summary = valid_source(root)
            source_data = valid_source_data()
            manifest = publish_dashboard_analysis_export(
                source, root / "export", summary, source_data=source_data
            )
            pointer = json.loads(
                (root / "export" / "franchise_operating_reviews" / "latest_success.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["source_data"], pointer["source_data"])

    def test_export_schema_requires_source_data(self):
        schema = json.loads(
            (Path(__file__).parents[1] / "ai" / "schemas" / "site_dashboard_analysis_export.v0.1.schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("source_data", schema["required"])
        self.assertFalse(schema["properties"]["source_data"].get("nullable", False))

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
                {"manifest.json", "business_review.json", "analysis_catalog.json", "review.json", "export_manifest.json", "site_performance_summary_bi_feishu_rent.csv"},
            )
            self.assertFalse((export / "site_performance_summary_bi_feishu_rent.csv").exists())
            self.assertTrue((review_root / MONTH / RUN_ID / "site_performance_summary_bi_feishu_rent.csv").is_file())
            self.assertEqual(len(manifest["files"]), 4)
            self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest["files"]))

    def test_preserves_remote_data_freshness_for_dashboard(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, summary = valid_source(root)
            export = root / "export"
            source_data = {
                "sync_status": "fallback_last_success",
                "stale": True,
                "package_id": "2026-07-retry",
                "data_period": "2026-07",
                "generated_at": "2026-09-01T08:00:00+08:00",
                "manifest_sha256": "f" * 64,
            }
            manifest = publish_dashboard_analysis_export(
                source,
                export,
                summary,
                source_data=source_data,
            )
            pointer = json.loads(
                (export / "franchise_operating_reviews" / "latest_success.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["source_data"], source_data)
            self.assertEqual(pointer["source_data"], source_data)

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

    def test_pointer_requires_status_month_and_run_id(self):
        for missing in ("status", "run_month", "run_id"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source, summary = valid_source(root)
                pointer_path = source / "latest_success.json"
                pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
                pointer.pop(missing)
                write_json(pointer_path, pointer)
                with self.assertRaises(DashboardAnalysisExportError):
                    publish_dashboard_analysis_export(source, root / "export", summary)

    def test_rejects_latest_success_path_outside_source_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, summary = valid_source(root)
            pointer_path = source / "latest_success.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["path"] = str(root / "outside" / RUN_ID)
            write_json(pointer_path, pointer)
            with self.assertRaisesRegex(DashboardAnalysisExportError, "path"):
                publish_dashboard_analysis_export(source, root / "export", summary)

    def test_rejects_extra_personnel_contract_and_financial_json_fields(self):
        mutations = (
            ("personnel", "business_review.json", lambda payload: payload.update(personnel_name="private")),
            ("contract", "manifest.json", lambda payload: payload["inputs"]["workforce"].update(contract_number="private")),
            ("financial", "review.json", lambda payload: payload.update(financial_profit=123)),
        )
        for label, filename, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); source, summary = valid_source(root)
                path = source / MONTH / RUN_ID / filename
                payload = json.loads(path.read_text(encoding="utf-8")); mutate(payload); write_json(path, payload)
                with self.assertRaises(DashboardAnalysisExportError):
                    publish_dashboard_analysis_export(source, root / "export", summary)

    def test_rejects_summary_missing_extra_duplicate_or_arbitrary_columns(self):
        variants = (
            list(SUMMARY_COLUMNS[:-1]),
            [*SUMMARY_COLUMNS, "salary"],
            [*SUMMARY_COLUMNS[:-1], SUMMARY_COLUMNS[0]],
            ["arbitrary"],
        )
        for headers in variants:
            with self.subTest(headers=headers[-2:]), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); source, summary = valid_source(root)
                with summary.open("w", encoding="utf-8-sig", newline="") as handle:
                    csv.writer(handle).writerow(headers)
                with self.assertRaises(DashboardAnalysisExportError):
                    publish_dashboard_analysis_export(source, root / "export", summary)

    def test_schema_paths_are_fixed_to_allowlisted_run_files(self):
        schema = json.loads((Path(__file__).parents[1] / "ai" / "schemas" / "site_dashboard_analysis_export.v0.1.schema.json").read_text(encoding="utf-8"))
        paths = {
            schema["$defs"][item["$ref"].split("/")[-1]]["allOf"][1]["properties"]["path"]["const"]
            for item in schema["properties"]["files"]["prefixItems"]
        }
        self.assertEqual(paths, {"manifest.json", "business_review.json", "analysis_catalog.json", "review.json"})
        self.assertNotIn("../business_review.json", paths)

    def test_tampered_file_or_same_run_content_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source, summary = valid_source(root); export = root / "export"
            publish_dashboard_analysis_export(source, export, summary)
            run = export / "franchise_operating_reviews" / MONTH / RUN_ID
            (run / "business_review.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(DashboardAnalysisExportError):
                publish_dashboard_analysis_export(source, export, summary)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source, summary = valid_source(root); export = root / "export"
            publish_dashboard_analysis_export(source, export, summary)
            with summary.open("a", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerow(["L0002"] + [""] * (len(SUMMARY_COLUMNS) - 1))
            with self.assertRaises(DashboardAnalysisExportError):
                publish_dashboard_analysis_export(source, export, summary)

    def test_rejects_arbitrary_or_escaping_run_paths(self):
        for value in ("../business_review.json", "other.json"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); source, summary = valid_source(root)
                path = source / MONTH / RUN_ID / "manifest.json"
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["outputs"]["business_review_json"] = value
                write_json(path, payload)
                with self.assertRaises(DashboardAnalysisExportError):
                    publish_dashboard_analysis_export(source, root / "export", summary)

    def test_pointer_failure_keeps_previous_snapshot_fully_consistent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source, summary = valid_source(root); export = root / "export"
            review_root = export / "franchise_operating_reviews"
            old_run = review_root / "2026-06" / ("a" * 20)
            old_run.mkdir(parents=True)
            (old_run / "export_manifest.json").write_bytes(b"old-manifest")
            (old_run / "site_performance_summary_bi_feishu_rent.csv").write_bytes(b"old-summary")
            write_json(review_root / "latest_success.json", {"run_month": "2026-06", "run_id": "a" * 20})
            old_pointer = (review_root / "latest_success.json").read_bytes()
            old_manifest = (old_run / "export_manifest.json").read_bytes()
            old_summary = (old_run / "site_performance_summary_bi_feishu_rent.csv").read_bytes()

            original_atomic = __import__("services.dashboard_analysis_export", fromlist=["_atomic_bytes"])._atomic_bytes
            def fail_pointer(path, content):
                if Path(path).name == "latest_success.json":
                    raise OSError("simulated pointer failure")
                return original_atomic(path, content)
            with patch("services.dashboard_analysis_export._atomic_bytes", side_effect=fail_pointer):
                with self.assertRaises(OSError):
                    publish_dashboard_analysis_export(source, export, summary)
            self.assertEqual((review_root / "latest_success.json").read_bytes(), old_pointer)
            self.assertEqual((old_run / "export_manifest.json").read_bytes(), old_manifest)
            self.assertEqual((old_run / "site_performance_summary_bi_feishu_rent.csv").read_bytes(), old_summary)
            self.assertFalse((review_root / MONTH / RUN_ID).exists())

    def test_accepts_real_generated_nonempty_bundle(self):
        from scripts.build_franchise_operating_review import build
        from tests.test_franchise_operating_check import monthly_rows
        from tests.test_franchise_operating_review import HEADERS, workforce_contract, workforce_rows
        from tests.test_franchise_review_display import add_display_fields, write_rows

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            operating_rows = add_display_fields(monthly_rows(revenues=(300000,) * 6))
            operating = root / "operating.csv"; workforce = root / "workforce.csv"; contract = root / "contract.json"
            write_rows(operating, list(operating_rows[0]), operating_rows)
            write_rows(workforce, HEADERS, workforce_rows(headcounts=(8,) * 7))
            contract.write_text(json.dumps(workforce_contract()), encoding="utf-8")
            source = root / "franchise_operating_reviews"
            manifest, _, _ = build(
                operating_path=operating, workforce_path=workforce, output_root=source,
                target_month=MONTH, workforce_contract=contract,
                now=datetime(2026, 8, 26, tzinfo=timezone.utc),
            )
            summary = root / SUMMARY_FILE_NAME
            with summary.open("w", encoding="utf-8-sig", newline="") as handle:
                csv.writer(handle).writerow(SUMMARY_COLUMNS)
            exported = publish_dashboard_analysis_export(source, root / "export", summary)
            self.assertEqual(exported["source_run"]["run_id"], manifest["run_id"])

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

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import scripts.build_analysis_calibration_summary as calibration_script
from scripts.build_analysis_calibration_summary import build_from_files
from services.analysis_feedback import (
    CALIBRATION_SCHEMA_VERSION,
    FEEDBACK_SCHEMA_VERSION,
    build_calibration_summary,
)
from services.professional_analysis import (
    ANALYSIS_CATALOG_SCHEMA_VERSION,
    ANALYSIS_RECORD_SCHEMA_VERSION,
    build_analysis_catalog,
    validate_analysis_catalog,
)


def business_review():
    stores = []
    for index, confidence in ((1, "中"), (2, "低")):
        stores.append(
            {
                "store_id": f"L{index:04d}",
                "store_name": f"测试门店{index}",
                "operating_status": "正常营业",
                "candidate_triggered": index == 1,
                "candidate_id": "candidate-1" if index == 1 else None,
                "trigger_codes": ["revenue_decline"] if index == 1 else [],
                "candidate_rule_check": {"triggered": index == 1, "reason": "test"},
                "latest_month_facts": {
                    "month": "2026-07",
                    "revenue": 200000 + index,
                    "rent_ratio": 0.1,
                },
                "recent_three_month_operating": {
                    "schema_version": "franchise-store-three-month-operating/v0.1",
                    "months": [
                        {
                            "month": "2026-07",
                            "rent_to_sales_ratio": {
                                "value": 0.2,
                                "status": "known",
                                "source_value": 0.1,
                            },
                        }
                    ],
                },
                "statistical_differences": {"revenue": {"change": -0.1 * index}},
                "personnel_history": {
                    "available": True,
                    "target_month": "2026-07",
                    "evidence_role": "可作交叉证据" if confidence == "中" else "仅作辅助证据",
                    "confidence_level": confidence,
                    "coverage_status": "complete",
                    "event_coverage_status": "complete",
                    "cutoff_date": "2026-08-18",
                    "month_start_headcount": 8,
                    "month_end_headcount": 7,
                    "month_average_headcount": 7.5,
                    "average_headcount_change": -0.1,
                    "workdays_per_average_therapist": 24,
                    "note": "只作交叉证据",
                },
                "possible_explanations": ["需要核查现场事实"],
                "evidence_gaps": ["现场原因"],
                "peer_evidence": {"used_for_candidate": False},
                "revenue_change_rank": index,
            }
        )
    return {
        "schema_version": "franchise-operating-business-review/v0.2",
        "status": "ready_for_business_review",
        "target_month": "2026-07",
        "dashboard_write_allowed": False,
        "data_gate": {"operating": {"ready": True}, "workforce": {"ready": True}},
        "stores": stores,
    }


def manifest():
    return {
        "run_id": "0123456789abcdefabcd",
        "run_month": "2026-07",
        "generated_at": "2026-08-29T00:00:00+00:00",
        "rule_version": "franchise-operating-monthly/v0.1",
        "candidate_rule_version": "franchise-operating-check/v0.1",
        "inputs": {
            "operating": {"sha256": "a" * 64, "row_count": 100},
            "workforce": {
                "sha256": "b" * 64,
                "row_count": 50,
                "data_version": "store-workforce-monthly/v1",
                "source_commit": "c" * 40,
                "contract_sha256": "d" * 64,
            },
        },
        "workforce_contract_version": "store-workforce-monthly-contract/v1",
    }


def empty_feedback(export_id="export-1"):
    return {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "export_id": export_id,
        "source_system": "lann-dashboard",
        "exported_at": "2026-08-29T01:00:00+00:00",
        "feedbacks": [],
    }


def feedback_for(record, feedback_id="feedback-1", status="accepted"):
    return {
        "feedback_id": feedback_id,
        "analysis_id": record["analysis_id"],
        "canonical_object": copy.deepcopy(record["canonical_object"]),
        "analysis_period": copy.deepcopy(record["analysis_period"]),
        "rule_version": record["rule_version"],
        "review": {
            "status": status,
            "reviewed_at": "2026-08-29T01:00:00+00:00",
            "reviewer_id": "dashboard-user-1",
            "note": None,
            "special_cause": "商场临时闭店" if status == "known_special_cause" else None,
        },
        "actions": None,
        "outcome": None,
    }


class ProfessionalAnalysisFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.catalog = build_analysis_catalog(business_review(), manifest())

    def test_catalog_has_common_identity_and_clear_evidence_layers(self):
        catalog = validate_analysis_catalog(self.catalog)
        self.assertEqual(catalog["schema_version"], ANALYSIS_CATALOG_SCHEMA_VERSION)
        self.assertEqual(catalog["analysis_record_schema_version"], ANALYSIS_RECORD_SCHEMA_VERSION)
        self.assertFalse(catalog["dashboard_write_allowed"])
        self.assertEqual(len(catalog["records"]), 2)
        record = catalog["records"][0]
        self.assertEqual(record["canonical_object"]["canonical_id"], "L0001")
        self.assertEqual(record["analysis_period"]["start"], "2026-07")
        self.assertEqual(record["rule_version"], "franchise-operating-check/v0.1")
        self.assertEqual(record["input_identity"]["source_run_id"], manifest()["run_id"])
        self.assertEqual(
            {row["source"] for row in record["input_identity"]["input_fingerprints"]},
            {"operating", "workforce", "workforce_contract"},
        )
        self.assertIn("direct_facts", record["evidence"])
        self.assertIn("statistical_differences", record["evidence"])
        self.assertIn("proxy_metrics", record["evidence"])
        self.assertIn("hypotheses", record["evidence"])
        latest = record["evidence"]["direct_facts"]["latest_month"]
        self.assertNotIn("rent_ratio", latest)
        self.assertEqual(latest["rent_to_sales_ratio"]["value"], 0.2)
        self.assertEqual(latest["source_rent_ratio_diagnostic"], 0.1)
        self.assertFalse(record["dashboard_write_allowed"])

    def test_analysis_id_binds_normalized_complete_input_identity(self):
        base_catalog = self.catalog
        base_id = base_catalog["records"][0]["analysis_id"]
        mutations = (
            (
                "sha256",
                lambda payload: payload["inputs"]["operating"].update(
                    sha256="e" * 64
                ),
            ),
            (
                "data_version",
                lambda payload: payload["inputs"]["workforce"].update(
                    data_version="store-workforce-monthly/v2"
                ),
            ),
            (
                "source_commit",
                lambda payload: payload["inputs"]["workforce"].update(
                    source_commit="f" * 40
                ),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                changed_manifest = copy.deepcopy(manifest())
                mutate(changed_manifest)
                changed = build_analysis_catalog(business_review(), changed_manifest)
                self.assertNotEqual(changed["records"][0]["analysis_id"], base_id)

        tampered = copy.deepcopy(base_catalog)
        tampered["records"][0]["input_identity"]["input_fingerprints"][0][
            "sha256"
        ] = "e" * 64
        with self.assertRaisesRegex(ValueError, "输入身份摘要"):
            validate_analysis_catalog(tampered)

    def test_input_identity_requires_all_sources_but_ignores_source_order(self):
        missing = copy.deepcopy(self.catalog)
        missing["records"][0]["input_identity"]["input_fingerprints"] = [
            row
            for row in missing["records"][0]["input_identity"]["input_fingerprints"]
            if row["source"] != "workforce_contract"
        ]
        with self.assertRaisesRegex(ValueError, "缺少必要输入指纹"):
            validate_analysis_catalog(missing)

        reordered = copy.deepcopy(self.catalog)
        original_ids = [record["analysis_id"] for record in reordered["records"]]
        for record in reordered["records"]:
            record["input_identity"]["input_fingerprints"].reverse()
        validate_analysis_catalog(reordered)
        self.assertEqual(
            [record["analysis_id"] for record in reordered["records"]], original_ids
        )

    def test_no_feedback_and_partial_feedback_keep_unknowns_explicit(self):
        no_feedback = build_calibration_summary(
            self.catalog,
            empty_feedback(),
            "2026-08-29T02:00:00+00:00",
        )
        self.assertEqual(no_feedback["schema_version"], CALIBRATION_SCHEMA_VERSION)
        self.assertEqual(no_feedback["counts"]["total_analyses"], 2)
        self.assertEqual(no_feedback["counts"]["reviewed_analyses"], 0)
        self.assertEqual(len(no_feedback["unreviewed_analyses"]), 2)
        self.assertFalse(no_feedback["calibration_policy"]["automatic_rule_change_allowed"])

        partial = empty_feedback("export-partial")
        partial["feedbacks"] = [feedback_for(self.catalog["records"][0])]
        summary = build_calibration_summary(
            self.catalog,
            partial,
            "2026-08-29T02:00:00+00:00",
        )
        self.assertEqual(summary["counts"]["reviewed_analyses"], 1)
        self.assertEqual(summary["counts"]["review_statuses"]["accepted"], 1)
        self.assertEqual(len(summary["unreviewed_analyses"]), 1)
        self.assertEqual(len(summary["unknown_action_linkage"]), 1)
        self.assertEqual(len(summary["missing_outcomes"]), 1)

    def test_data_missing_special_cause_actions_and_outcomes_are_separate(self):
        payload = empty_feedback("export-complete")
        data_missing = feedback_for(
            self.catalog["records"][0], "feedback-data", "data_missing"
        )
        data_missing["actions"] = []
        special = feedback_for(
            self.catalog["records"][1], "feedback-special", "known_special_cause"
        )
        special["actions"] = [
            {
                "action_id": "action-1",
                "status": "completed",
                "summary": "核对商场闭店日期",
                "updated_at": "2026-08-30T00:00:00+00:00",
            }
        ]
        special["outcome"] = {
            "outcome_id": "outcome-1",
            "status": "inconclusive",
            "summary": "后续月份尚不足以判断",
            "observed_at": "2026-09-30T00:00:00+00:00",
            "source_reference": "dashboard://review/outcome-1",
        }
        payload["feedbacks"] = [data_missing, special]
        original = copy.deepcopy(self.catalog)
        summary = build_calibration_summary(
            self.catalog,
            payload,
            "2026-10-01T00:00:00+00:00",
        )
        self.assertEqual(summary["counts"]["review_statuses"]["data_missing"], 1)
        self.assertEqual(summary["counts"]["review_statuses"]["known_special_cause"], 1)
        self.assertEqual(summary["counts"]["analyses_with_actions"], 1)
        self.assertEqual(summary["counts"]["analyses_with_outcomes"], 1)
        self.assertEqual(len(summary["missing_outcomes"]), 1)
        self.assertEqual(self.catalog, original)

    def test_wrong_analysis_object_period_or_rule_is_rejected(self):
        base = feedback_for(self.catalog["records"][0])
        mutations = (
            ("analysis", lambda row: row.update(analysis_id="ana_" + "0" * 24)),
            (
                "object",
                lambda row: row["canonical_object"].update(canonical_id="L9999"),
            ),
            ("period", lambda row: row["analysis_period"].update(start="2026-06", end="2026-06")),
            ("rule", lambda row: row.update(rule_version="other/v1")),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                row = copy.deepcopy(base)
                mutate(row)
                payload = empty_feedback(f"export-{label}")
                payload["feedbacks"] = [row]
                with self.assertRaises(ValueError):
                    build_calibration_summary(
                        self.catalog, payload, "2026-08-29T02:00:00+00:00"
                    )

    def test_display_name_change_does_not_break_canonical_identity(self):
        row = feedback_for(self.catalog["records"][0])
        row["canonical_object"]["display_name"] = "门店新展示名"
        payload = empty_feedback("export-renamed")
        payload["feedbacks"] = [row]
        summary = build_calibration_summary(
            self.catalog, payload, "2026-08-29T02:00:00+00:00"
        )
        self.assertEqual(summary["counts"]["reviewed_analyses"], 1)

        row_without_name = feedback_for(self.catalog["records"][1], "feedback-no-name")
        row_without_name["canonical_object"].pop("display_name")
        payload_without_name = empty_feedback("export-no-name")
        payload_without_name["feedbacks"] = [row_without_name]
        summary_without_name = build_calibration_summary(
            self.catalog, payload_without_name, "2026-08-29T02:00:00+00:00"
        )
        self.assertEqual(summary_without_name["counts"]["reviewed_analyses"], 1)

    def test_unknown_status_and_conflicting_duplicates_are_rejected(self):
        row = feedback_for(self.catalog["records"][0])
        unknown = copy.deepcopy(row)
        unknown["review"]["status"] = "auto_fix_rule"
        payload = empty_feedback("export-unknown")
        payload["feedbacks"] = [unknown]
        with self.assertRaisesRegex(ValueError, "状态不支持"):
            build_calibration_summary(
                self.catalog, payload, "2026-08-29T02:00:00+00:00"
            )

        exact = empty_feedback("export-idempotent")
        exact["feedbacks"] = [row, copy.deepcopy(row)]
        summary = build_calibration_summary(
            self.catalog, exact, "2026-08-29T02:00:00+00:00"
        )
        self.assertEqual(summary["counts"]["reviewed_analyses"], 1)
        self.assertEqual(summary["counts"]["idempotent_duplicate_feedback_rows"], 1)

        conflict = copy.deepcopy(row)
        conflict["review"]["note"] = "conflict"
        conflicting = empty_feedback("export-conflict")
        conflicting["feedbacks"] = [row, conflict]
        with self.assertRaisesRegex(ValueError, "冲突内容"):
            build_calibration_summary(
                self.catalog, conflicting, "2026-08-29T02:00:00+00:00"
            )

    def test_read_failure_preserves_latest_success_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog_path = root / "analysis_catalog.json"
            feedback_path = root / "feedback.json"
            output_root = root / "output"
            catalog_path.write_text(
                json.dumps(self.catalog, ensure_ascii=False), encoding="utf-8"
            )
            feedback_path.write_text(
                json.dumps(empty_feedback(), ensure_ascii=False), encoding="utf-8"
            )
            manifest_payload, _, duplicate = build_from_files(
                catalog_path,
                feedback_path,
                output_root,
                now=datetime(2026, 8, 29, tzinfo=timezone.utc),
            )
            self.assertFalse(duplicate)
            repeated_manifest, repeated_dir, repeated = build_from_files(
                catalog_path,
                feedback_path,
                output_root,
                now=datetime(2026, 8, 29, 1, tzinfo=timezone.utc),
            )
            self.assertTrue(repeated)
            self.assertEqual(repeated_manifest["summary_id"], manifest_payload["summary_id"])
            self.assertTrue((repeated_dir / "calibration_summary.json").is_file())
            feedback_path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                build_from_files(
                    catalog_path,
                    feedback_path,
                    output_root,
                    now=datetime(2026, 8, 30, tzinfo=timezone.utc),
                )
            latest = json.loads(
                (output_root / "latest_success.json").read_text(encoding="utf-8")
            )
            attempt = json.loads(
                (output_root / "last_attempt.json").read_text(encoding="utf-8")
            )
        self.assertEqual(latest["summary_id"], manifest_payload["summary_id"])
        self.assertEqual(attempt["status"], "blocked_by_feedback_input")
        self.assertEqual(attempt["failure_source"], "feedback")
        self.assertTrue(attempt["stale"])
        self.assertEqual(attempt["error_type"], "JSONDecodeError")
        self.assertEqual(attempt["latest_success"]["summary_id"], latest["summary_id"])
        self.assertFalse(attempt["dashboard_write_allowed"])

    def test_catalog_and_output_failures_are_classified_and_preserve_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog_path = root / "analysis_catalog.json"
            feedback_path = root / "feedback.json"
            output_root = root / "output"
            catalog_path.write_text(
                json.dumps(self.catalog, ensure_ascii=False), encoding="utf-8"
            )
            feedback_path.write_text(
                json.dumps(empty_feedback(), ensure_ascii=False), encoding="utf-8"
            )
            successful_manifest, _, _ = build_from_files(
                catalog_path,
                feedback_path,
                output_root,
                now=datetime(2026, 8, 29, tzinfo=timezone.utc),
            )

            invalid_catalog = copy.deepcopy(self.catalog)
            invalid_catalog["records"][0]["input_identity"]["input_fingerprints"][0][
                "sha256"
            ] = "e" * 64
            catalog_path.write_text(
                json.dumps(invalid_catalog, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "输入身份摘要"):
                build_from_files(
                    catalog_path,
                    feedback_path,
                    output_root,
                    now=datetime(2026, 8, 30, tzinfo=timezone.utc),
                )
            catalog_attempt = json.loads(
                (output_root / "last_attempt.json").read_text(encoding="utf-8")
            )
            self.assertEqual(catalog_attempt["status"], "blocked_by_analysis_catalog")
            self.assertEqual(catalog_attempt["failure_source"], "catalog")
            self.assertTrue(catalog_attempt["stale"])
            self.assertEqual(
                catalog_attempt["latest_success"]["summary_id"],
                successful_manifest["summary_id"],
            )

            catalog_path.write_text(
                json.dumps(self.catalog, ensure_ascii=False), encoding="utf-8"
            )
            feedback_path.write_text(
                json.dumps(empty_feedback("export-output-failure"), ensure_ascii=False),
                encoding="utf-8",
            )
            original_write_json = calibration_script._write_json

            def fail_summary_write(path, payload):
                if Path(path).name == "calibration_summary.json":
                    raise OSError("simulated output failure")
                return original_write_json(path, payload)

            with patch.object(
                calibration_script, "_write_json", side_effect=fail_summary_write
            ):
                with self.assertRaisesRegex(OSError, "simulated output failure"):
                    build_from_files(
                        catalog_path,
                        feedback_path,
                        output_root,
                        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
                    )
            output_attempt = json.loads(
                (output_root / "last_attempt.json").read_text(encoding="utf-8")
            )
            self.assertEqual(output_attempt["status"], "blocked_by_output")
            self.assertEqual(output_attempt["failure_source"], "output")
            self.assertTrue(output_attempt["stale"])
            self.assertIn("simulated output failure", output_attempt["reason"])
            self.assertEqual(
                output_attempt["latest_success"]["summary_id"],
                successful_manifest["summary_id"],
            )

    def test_schema_files_publish_exact_versions_and_guardrails(self):
        schema_root = Path(__file__).resolve().parents[1] / "ai" / "schemas"
        catalog_schema = json.loads(
            (schema_root / "professional_analysis_catalog.v0.1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        feedback_schema = json.loads(
            (schema_root / "professional_analysis_feedback.v0.1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        summary_schema = json.loads(
            (
                schema_root
                / "professional_analysis_calibration_summary.v0.1.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            catalog_schema["properties"]["schema_version"]["const"],
            ANALYSIS_CATALOG_SCHEMA_VERSION,
        )
        self.assertFalse(
            catalog_schema["properties"]["dashboard_write_allowed"]["const"]
        )
        self.assertEqual(
            feedback_schema["properties"]["schema_version"]["const"],
            FEEDBACK_SCHEMA_VERSION,
        )
        self.assertFalse(
            summary_schema["properties"]["calibration_policy"]["properties"]
            ["automatic_rule_change_allowed"]["const"]
        )


if __name__ == "__main__":
    unittest.main()

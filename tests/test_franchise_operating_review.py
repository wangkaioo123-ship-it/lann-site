import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from scripts.build_franchise_operating_review import build
from services.franchise_operating_check import build_operating_check_candidates
from services.franchise_operating_review import (
    EVIDENCE_AUXILIARY,
    EVIDENCE_INSUFFICIENT,
    EVIDENCE_STRONG,
    build_review,
)
from services.workforce_monthly import build_workforce_gate, load_workforce_monthly
from tests.test_franchise_operating_check import monthly_rows


HEADERS = [
    "store_id", "month", "therapist_headcount_start", "therapist_headcount_end", "therapist_headcount_avg",
    "therapist_hires", "therapist_exits", "permanent_transfer_in", "permanent_transfer_out",
    "short_support_in", "short_support_out", "short_support_in_person_days", "short_support_out_person_days",
    "therapist_net_change", "manager_change_candidate", "manager_change_candidate_count",
    "manager_change_first_date", "snapshot_coverage_days", "expected_snapshot_days", "snapshot_coverage_status",
    "event_coverage_status", "store_coverage_status", "data_trust_level", "data_cutoff_date", "data_version",
]
CONTRACT_PATH = Path(__file__).resolve().parents[1] / "config" / "store_workforce_monthly.v1.contract.json"


def workforce_contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def workforce_rows(headcounts=(8, 8, 8, 8, 7, 7, 6), confidence="medium"):
    months = ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07")
    rows = []
    for index, month in enumerate(months):
        count = headcounts[index]
        rows.append(
            {
                "store_id": "L0001", "month": f"{month}-01", "therapist_headcount_start": count,
                "therapist_headcount_end": count, "therapist_headcount_avg": count,
                "therapist_hires": 0, "therapist_exits": 2 if month == "2026-06" else 0,
                "permanent_transfer_in": 0, "permanent_transfer_out": 2 if month == "2026-07" else 0,
                "short_support_in": 1 if month == "2026-07" else 0, "short_support_out": 0,
                "short_support_in_person_days": 3 if month == "2026-07" else 0,
                "short_support_out_person_days": 0,
                "therapist_net_change": -1 if month in {"2026-06", "2026-07"} else 0,
                "manager_change_candidate": "false", "manager_change_candidate_count": 0,
                "manager_change_first_date": "", "snapshot_coverage_days": 31,
                "expected_snapshot_days": 31, "snapshot_coverage_status": "complete",
                "event_coverage_status": "complete", "store_coverage_status": "franchise",
                "data_trust_level": confidence, "data_cutoff_date": "2026-08-18",
                "data_version": "store-workforce-monthly/v1",
            }
        )
    return rows


def write_csv(path, headers, rows):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def write_operating(path, rows):
    headers = list(rows[0])
    write_csv(path, headers, rows)


class FranchiseOperatingReviewTests(unittest.TestCase):
    def test_workforce_contract_does_not_guess_unconfirmed_production_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, workforce_rows())
            dataset = load_workforce_monthly(path)
        self.assertEqual(dataset["rows"], [])
        self.assertIn("缺少经数据发布方确认的人员生产契约", "；".join(dataset["issues"]))

    def test_workforce_contract_and_gate_accept_medium_confidence(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, workforce_rows())
            dataset = load_workforce_monthly(path, workforce_contract())
            gate = build_workforce_gate(dataset, "2026-07", {"L0001"}, ["L0001"])
        self.assertEqual(dataset["column_count"], 25)
        self.assertTrue(gate["ready"])
        self.assertEqual(gate["confidence_levels"], ["中"])
        self.assertEqual(gate["source_store_count"], 1)
        self.assertEqual(gate["source_months"], [
            "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07",
        ])
        self.assertEqual(gate["missing_scope_stores"], [])

    def test_production_unavailable_sample_keeps_blank_headcount_and_blocks_strong_use(self):
        values = [
            "L0012", "2026-01-01", "", "", "", "0", "0", "0", "0", "0", "0", "0", "0", "",
            "false", "0", "", "0", "31", "unavailable", "complete", "franchise", "low",
            "2026-08-18", "store-workforce-monthly/v1",
        ]
        row = dict(zip(HEADERS, values))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, [row])
            dataset = load_workforce_monthly(path, workforce_contract())
            gate = build_workforce_gate(dataset, "2026-01", {"L0012"}, ["L0012"])
        parsed = dataset["rows"][0]
        self.assertIsNone(parsed["month_start_headcount"])
        self.assertIsNone(parsed["month_end_headcount"])
        self.assertIsNone(parsed["month_average_headcount"])
        self.assertEqual(parsed["exit_count"], 0)
        self.assertEqual(parsed["event_coverage_status"], "complete")
        self.assertEqual(parsed["coverage_status"], "unavailable")
        self.assertEqual(parsed["confidence_level"], "低")
        self.assertFalse(gate["ready"])
        self.assertIn("字段完整度不足", gate["message"])
        self.assertIn("可信等级不足", gate["message"])
        self.assertIn("人数快照覆盖不足", gate["message"])

    def test_workforce_contract_rejects_header_order_drift(self):
        headers = list(HEADERS)
        headers[0], headers[1] = headers[1], headers[0]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, headers, workforce_rows())
            dataset = load_workforce_monthly(path, workforce_contract())
        self.assertEqual(dataset["rows"], [])
        self.assertIn("首个差异列 1", "；".join(dataset["issues"]))

    def test_workforce_contract_rejects_data_version_drift(self):
        rows = workforce_rows()
        rows[-1]["data_version"] = "store-workforce-monthly/v2"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, rows)
            dataset = load_workforce_monthly(path, workforce_contract())
        self.assertEqual(dataset["rows"], [])
        self.assertIn("data_version 不符合正式契约", "；".join(dataset["issues"]))

    def test_workforce_gate_rejects_low_confidence(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, workforce_rows(confidence="低"))
            gate = build_workforce_gate(load_workforce_monthly(path, workforce_contract()), "2026-07", {"L0001"}, ["L0001"])
        self.assertFalse(gate["ready"])
        self.assertIn("可信等级不足", gate["message"])

    def test_june_low_confidence_is_auxiliary_and_never_strong(self):
        operating_rows = monthly_rows()
        for row, month in zip(
            operating_rows,
            ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"),
        ):
            row["月份"] = month
        operating = build_operating_check_candidates(
            operating_rows,
            today=date(2026, 8, 25),
            target_month="2026-06",
        )
        candidate = operating["stores"]["L0001"]["candidate"]
        self.assertIsNotNone(candidate)
        rows = workforce_rows(confidence="low")[:6]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, rows)
            dataset = load_workforce_monthly(path, workforce_contract())
            gate = build_workforce_gate(dataset, "2026-06", {"L0001"}, ["L0001"])
            review = build_review(
                operating_rows,
                operating,
                dataset,
                gate,
                [{"store_id": "L0001", "store_name": "测试门店", "candidate_id": candidate["candidate_id"]}],
            )
        self.assertTrue(gate["ready"])
        self.assertIn("只作辅助证据", "；".join(gate["limitations"]))
        self.assertEqual(review["status"], "ready_for_business_review")
        self.assertEqual(review["candidates"][0]["evidence_class"], EVIDENCE_AUXILIARY)
        self.assertFalse(review["candidates"][0]["personnel_indicators"]["target_month_direct_signal"])

    def test_personal_level_header_is_rejected(self):
        headers = HEADERS[:-1] + ["employee_id"]
        rows = workforce_rows()
        for row in rows:
            row.pop("data_version")
            row["employee_id"] = "forbidden"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, headers, rows)
            dataset = load_workforce_monthly(path, workforce_contract())
        self.assertTrue(any("个人级字段" in issue for issue in dataset["issues"]))

    def test_personal_level_staff_name_variant_is_rejected(self):
        headers = HEADERS[:-1] + ["staff_name"]
        rows = workforce_rows()
        for row in rows:
            row.pop("data_version")
            row["staff_name"] = "forbidden"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, headers, rows)
            dataset = load_workforce_monthly(path, workforce_contract())
        self.assertTrue(any("个人级字段" in issue for issue in dataset["issues"]))

    def test_future_month_is_reported_as_trend_only(self):
        rows = workforce_rows()
        rows.append({**rows[-1], "month": "2026-08-01"})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, rows)
            gate = build_workforce_gate(load_workforce_monthly(path, workforce_contract()), "2026-07", {"L0001"}, ["L0001"])
        self.assertTrue(gate["ready"])
        self.assertEqual(gate["trend_only_months"], ["2026-08"])

    def test_review_separates_direct_facts_proxy_and_hypothesis(self):
        operating_rows = monthly_rows()
        operating = build_operating_check_candidates(operating_rows, today=date(2026, 8, 17))
        candidate = operating["stores"]["L0001"]["candidate"]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, workforce_rows())
            dataset = load_workforce_monthly(path, workforce_contract())
            gate = build_workforce_gate(dataset, "2026-07", {"L0001"}, ["L0001"])
            review = build_review(
                operating_rows, operating, dataset, gate,
                [{"store_id": "L0001", "store_name": "测试门店", "candidate_id": candidate["candidate_id"]}],
            )
        item = review["candidates"][0]
        self.assertEqual(item["evidence_class"], EVIDENCE_STRONG)
        self.assertIn("direct_facts", item)
        self.assertIn("proxy_metrics", item)
        self.assertIn("hypothesis", item)
        self.assertNotIn("导致", json.dumps(review, ensure_ascii=False))
        self.assertFalse(review["dashboard_write_allowed"])

    def test_stable_headcount_does_not_claim_personnel_support(self):
        operating_rows = monthly_rows()
        operating = build_operating_check_candidates(operating_rows, today=date(2026, 8, 17))
        candidate = operating["stores"]["L0001"]["candidate"]
        rows = workforce_rows(headcounts=(8,) * 7)
        for row in rows:
            for field in (
                "therapist_exits", "permanent_transfer_out", "short_support_in", "therapist_net_change",
                "short_support_in_person_days", "short_support_out_person_days",
            ):
                row[field] = 0
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, rows)
            dataset = load_workforce_monthly(path, workforce_contract())
            gate = build_workforce_gate(dataset, "2026-07", {"L0001"}, ["L0001"])
            review = build_review(
                operating_rows, operating, dataset, gate,
                [{"store_id": "L0001", "store_name": "测试门店", "candidate_id": candidate["candidate_id"]}],
            )
        self.assertEqual(review["candidates"][0]["evidence_class"], EVIDENCE_INSUFFICIENT)

    def test_pre_july_headcount_trend_is_only_auxiliary_without_target_month_signal(self):
        operating_rows = monthly_rows()
        operating = build_operating_check_candidates(operating_rows, today=date(2026, 8, 17))
        candidate = operating["stores"]["L0001"]["candidate"]
        rows = workforce_rows(headcounts=(8, 8, 8, 8, 6, 6, 6))
        for row in rows:
            for field in (
                "therapist_hires", "therapist_exits", "permanent_transfer_in", "permanent_transfer_out",
                "short_support_in", "short_support_out", "short_support_in_person_days", "short_support_out_person_days",
            ):
                row[field] = 0
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, rows)
            dataset = load_workforce_monthly(path, workforce_contract())
            gate = build_workforce_gate(dataset, "2026-07", {"L0001"}, ["L0001"])
            review = build_review(
                operating_rows, operating, dataset, gate,
                [{"store_id": "L0001", "store_name": "测试门店", "candidate_id": candidate["candidate_id"]}],
            )
        self.assertEqual(review["candidates"][0]["evidence_class"], "有辅助证据")
        self.assertFalse(review["candidates"][0]["personnel_indicators"]["target_month_direct_signal"])

    def test_july_end_headcount_change_against_auxiliary_june_is_not_strong_alone(self):
        operating_rows = monthly_rows()
        operating = build_operating_check_candidates(operating_rows, today=date(2026, 8, 17))
        candidate = operating["stores"]["L0001"]["candidate"]
        rows = workforce_rows()
        for row in rows:
            for field in (
                "therapist_hires", "therapist_exits", "permanent_transfer_in", "permanent_transfer_out",
                "short_support_in", "short_support_out", "short_support_in_person_days", "short_support_out_person_days",
            ):
                row[field] = 0
        rows[-2]["data_trust_level"] = "low"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, rows)
            dataset = load_workforce_monthly(path, workforce_contract())
            gate = build_workforce_gate(dataset, "2026-07", {"L0001"}, ["L0001"])
            review = build_review(
                operating_rows, operating, dataset, gate,
                [{"store_id": "L0001", "store_name": "测试门店", "candidate_id": candidate["candidate_id"]}],
            )
        self.assertTrue(gate["ready"])
        self.assertEqual(review["candidates"][0]["evidence_class"], "有辅助证据")
        self.assertFalse(review["candidates"][0]["personnel_indicators"]["target_month_direct_signal"])

    def test_failed_workforce_gate_outputs_no_candidates(self):
        operating_rows = monthly_rows()
        operating = build_operating_check_candidates(operating_rows, today=date(2026, 8, 17))
        candidate = operating["stores"]["L0001"]["candidate"]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, workforce_rows(confidence="低"))
            dataset = load_workforce_monthly(path, workforce_contract())
            gate = build_workforce_gate(dataset, "2026-07", {"L0001"}, ["L0001"])
            review = build_review(
                operating_rows, operating, dataset, gate,
                [{"store_id": "L0001", "store_name": "测试门店", "candidate_id": candidate["candidate_id"]}],
            )
        self.assertEqual(review["status"], "blocked_by_data_gate")
        self.assertEqual(review["candidates"], [])

    def test_review_requires_workforce_months_aligned_to_operating_window(self):
        operating_rows = monthly_rows()
        operating = build_operating_check_candidates(operating_rows, today=date(2026, 8, 17))
        candidate = operating["stores"]["L0001"]["candidate"]
        rows = [row for row in workforce_rows() if row["month"] != "2026-05-01"]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, rows)
            dataset = load_workforce_monthly(path, workforce_contract())
            gate = build_workforce_gate(dataset, "2026-07", {"L0001"}, ["L0001"])
            review = build_review(
                operating_rows, operating, dataset, gate,
                [{"store_id": "L0001", "store_name": "测试门店", "candidate_id": candidate["candidate_id"]}],
            )
        self.assertEqual(review["status"], "blocked_by_data_gate")
        self.assertIn("缺少 2026-05", "；".join(review["data_gate"]["issues"]))

    def test_review_rejects_missing_historical_personnel_fields(self):
        operating_rows = monthly_rows()
        operating = build_operating_check_candidates(operating_rows, today=date(2026, 8, 17))
        candidate = operating["stores"]["L0001"]["candidate"]
        rows = workforce_rows()
        rows[4]["therapist_exits"] = ""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workforce.csv"
            write_csv(path, HEADERS, rows)
            dataset = load_workforce_monthly(path, workforce_contract())
            gate = build_workforce_gate(dataset, "2026-07", {"L0001"}, ["L0001"])
            review = build_review(
                operating_rows, operating, dataset, gate,
                [{"store_id": "L0001", "store_name": "测试门店", "candidate_id": candidate["candidate_id"]}],
            )
        self.assertEqual(review["status"], "blocked_by_data_gate")
        self.assertIn("2026-05/exit_count", "；".join(review["data_gate"]["issues"]))

    def test_same_inputs_are_idempotent_and_do_not_create_second_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            operating_path = root / "operating.csv"
            workforce_path = root / "workforce.csv"
            output_root = root / "out"
            freeze_path = root / "freeze.json"
            operating_rows = monthly_rows()
            write_operating(operating_path, operating_rows)
            write_csv(workforce_path, HEADERS, workforce_rows())
            contract_path = root / "workforce-contract.json"
            contract_path.write_text(json.dumps(workforce_contract()), encoding="utf-8")
            candidate = build_operating_check_candidates(operating_rows, today=date(2026, 8, 17))["stores"]["L0001"]["candidate"]
            freeze_path.write_text(
                json.dumps(
                    {
                        "schema_version": "franchise-operating-candidate-freeze/v0.1",
                        "target_month": "2026-07",
                        "candidate_order": [{"store_id": "L0001", "store_name": "测试门店", "candidate_id": candidate["candidate_id"]}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            first, first_dir, first_duplicate = build(
                operating_path, workforce_path, output_root, "2026-07", freeze_path,
                workforce_contract=contract_path,
                today=date(2026, 8, 17), now=datetime(2026, 8, 18, tzinfo=timezone.utc),
            )
            second, second_dir, second_duplicate = build(
                operating_path, workforce_path, output_root, "2026-07", freeze_path,
                workforce_contract=contract_path,
                today=date(2026, 8, 17), now=datetime(2026, 8, 19, tzinfo=timezone.utc),
            )
        self.assertFalse(first_duplicate)
        self.assertTrue(second_duplicate)
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(first_dir, second_dir)
        self.assertEqual(first["generated_at"], second["generated_at"])
        self.assertEqual(first["inputs"]["workforce"]["data_version"], "store-workforce-monthly/v1")
        self.assertEqual(first["inputs"]["workforce"]["source_commit"], "64080775db87793e5308e3a9e7d0a1a58dba4d23")
        self.assertRegex(first["inputs"]["workforce"]["contract_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()

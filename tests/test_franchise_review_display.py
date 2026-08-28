import copy
import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from scripts.build_franchise_operating_review import build
from services.franchise_operating_check import build_operating_check_candidates
from services.franchise_review_display import (
    BUSINESS_REVIEW_SCHEMA_VERSION,
    RATIO_SOURCE_COMPARISON_TOLERANCE,
    RATIO_VALUE_TOLERANCE,
    THREE_MONTH_OPERATING_SCHEMA_VERSION,
    _three_month_operating_contract,
    build_business_review,
    validate_three_month_operating_contract,
    write_business_review_browser,
)
from services.workforce_monthly import build_workforce_gate, load_workforce_monthly
from tests.test_franchise_operating_check import monthly_rows
from tests.test_franchise_operating_review import HEADERS, workforce_contract, workforce_rows


def add_display_fields(rows, visits=600, ticket=500, productivity=0.8):
    for row in rows:
        row["订单客次"] = str(visits)
        row["客单价_折扣后"] = str(ticket)
        row["理疗师生产率"] = str(productivity)
        row["营收数据来源"] = "canonical-test"
        row["营收数据完整性"] = "完整月"
        revenue = float(row["实际营收"])
        rent_ratio = float(row["租售比"])
        row["月租金"] = str(revenue * rent_ratio)
        row["租金状态"] = "当年已定"
        row["租金来源文件"] = "lease-register-test"
        row["租金备注"] = "测试租金物业合计"
    return rows


def write_rows(path, headers, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def workforce_for(store_ids, confidence="medium"):
    result = []
    for store_id in store_ids:
        for row in workforce_rows(headcounts=(8,) * 7, confidence=confidence):
            cloned = dict(row)
            cloned["store_id"] = store_id
            result.append(cloned)
    return result


class FranchiseReviewDisplayTests(unittest.TestCase):
    def build_review(self, operating_rows, workforce_raw):
        operating = build_operating_check_candidates(
            operating_rows, today=date(2026, 8, 26), target_month="2026-07"
        )
        with tempfile.TemporaryDirectory() as temp:
            workforce_path = Path(temp) / "workforce.csv"
            write_rows(workforce_path, HEADERS, workforce_raw)
            dataset = load_workforce_monthly(workforce_path, workforce_contract())
            scope = {
                row["点位ID"]
                for row in operating_rows
                if row["月份"] == "2026-07" and row.get("点位ID")
            }
            candidates = [
                store_id
                for store_id, result in operating["stores"].items()
                if result.get("candidate")
            ]
            gate = build_workforce_gate(dataset, "2026-07", scope, candidates)
            return build_business_review(operating_rows, operating, dataset, gate)

    def test_zero_candidates_still_lists_every_participating_store(self):
        stable_1 = add_display_fields(
            monthly_rows(
                "L0001",
                revenues=(300000,) * 6,
                customers=(500,) * 6,
                new_customers=(120,) * 6,
                old_customers=(380,) * 6,
                workdays=(200,) * 6,
                therapist_output=(1500,) * 6,
            )
        )
        stable_2 = add_display_fields(
            monthly_rows(
                "L0002",
                revenues=(260000,) * 6,
                customers=(450,) * 6,
                new_customers=(100,) * 6,
                old_customers=(350,) * 6,
                workdays=(180,) * 6,
                therapist_output=(1440,) * 6,
            ),
            visits=520,
        )
        review = self.build_review(stable_1 + stable_2, workforce_for(("L0001", "L0002")))
        self.assertEqual(review["status"], "ready_for_business_review")
        self.assertEqual(review["candidate_count"], 0)
        self.assertEqual(review["coverage"]["participating_store_count"], 2)
        self.assertEqual([row["store_id"] for row in review["stores"]], ["L0001", "L0002"])
        self.assertIn("不能解释为门店没有经营问题", review["fixed_nine_comparison"]["note"])
        self.assertTrue(review["fixed_nine_comparison"]["same_rule_version_as_reference"])
        self.assertTrue(review["fixed_nine_comparison"]["same_month_as_reference"])
        self.assertFalse(review["fixed_nine_comparison"]["current_candidate_freeze_applied"])
        self.assertIn("SHA-256", review["fixed_nine_comparison"]["input_version_check"])

    def test_store_view_has_month_facts_changes_and_rule_distance_without_score(self):
        stable = add_display_fields(
            monthly_rows(
                revenues=(300000,) * 6,
                customers=(500,) * 6,
                new_customers=(120,) * 6,
                old_customers=(380,) * 6,
                workdays=(200,) * 6,
                therapist_output=(1500,) * 6,
            )
        )
        review = self.build_review(stable, workforce_for(("L0001",)))
        store = review["stores"][0]
        self.assertEqual(store["latest_month_facts"]["revenue"], 300000)
        self.assertEqual(store["latest_month_facts"]["service_visits"], 600)
        self.assertEqual(store["latest_month_facts"]["discounted_average_ticket"], 500)
        self.assertEqual(store["statistical_differences"]["revenue"]["change"], 0)
        revenue_gate = store["candidate_rule_check"]["operating_combination_decline"]["revenue"]
        self.assertFalse(revenue_gate["met"])
        self.assertEqual(revenue_gate["distance_to_threshold"], 0.08)
        serialized = json.dumps(review, ensure_ascii=False)
        self.assertNotIn('"risk_score"', serialized)
        self.assertNotIn("导致", serialized)

    def test_recent_three_month_contract_keeps_combined_cost_without_guessing_split(self):
        rows = add_display_fields(
            monthly_rows(
                revenues=(300000, 300000, 300000, 270000, 250000, 240000),
                rent_ratios=(0.20, 0.20, 0.20, 0.22, 0.24, 0.25),
            )
        )
        review = self.build_review(rows, workforce_for(("L0001",)))
        contract = review["stores"][0]["recent_three_month_operating"]
        validate_three_month_operating_contract(contract, "2026-07")
        self.assertEqual(contract["schema_version"], THREE_MONTH_OPERATING_SCHEMA_VERSION)
        self.assertEqual(
            [row["month"] for row in contract["months"]],
            ["2026-05", "2026-06", "2026-07"],
        )
        july = contract["months"][-1]
        self.assertEqual(july["operating_revenue"]["amount_yuan"], 240000)
        self.assertEqual(july["known_occupancy_cost_total"]["amount_yuan"], 60000)
        self.assertEqual(july["known_occupancy_cost_total"]["status"], "known_combined_unallocated")
        self.assertEqual(
            july["known_occupancy_cost_total"]["included_components"],
            ["base_rent", "property_fee"],
        )
        self.assertIsNone(july["base_rent"]["amount_yuan"])
        self.assertIsNone(july["property_fee"]["amount_yuan"])
        self.assertEqual(july["base_rent"]["status"], "unknown_unallocated_from_combined_amount")
        self.assertIsNone(july["management_fee"]["amount_yuan"])
        self.assertEqual(july["rent_to_sales_ratio"]["value"], 0.25)
        self.assertEqual(july["rent_to_sales_ratio"]["source_value"], 0.25)
        self.assertEqual(july["rent_to_sales_ratio"]["source_value_status"], "matched")
        self.assertFalse(july["rent_to_sales_ratio"]["source_value_mismatch"])
        self.assertEqual(
            july["rent_to_sales_ratio"]["numerator_scope"],
            "base_rent_plus_property_fee_combined",
        )
        self.assertEqual(july["data_cutoff"]["cutoff_date"], "2026-07-31")
        self.assertEqual(july["data_source"]["operating_revenue"], "canonical-test")
        self.assertEqual(july["data_source"]["occupancy_cost"], "lease-register-test")
        self.assertFalse(
            review["three_month_operating_contract"]["cost_scope"]["financial_profit_calculated"]
        )
        self.assertNotIn('"profit"', json.dumps(contract, ensure_ascii=False))

    def test_contradictory_source_ratio_is_diagnostic_and_amount_ratio_is_authoritative(self):
        rows = add_display_fields(
            monthly_rows(revenues=(100000,) * 6, rent_ratios=(0.6,) * 6)
        )
        rows[-1]["租售比"] = "0.1"
        review = self.build_review(rows, workforce_for(("L0001",)))
        contract = review["stores"][0]["recent_three_month_operating"]
        july = contract["months"][-1]

        self.assertEqual(july["operating_revenue"]["amount_yuan"], 100000)
        self.assertEqual(july["known_occupancy_cost_total"]["amount_yuan"], 60000)
        self.assertEqual(july["rent_to_sales_ratio"]["value"], 0.6)
        self.assertEqual(july["rent_to_sales_ratio"]["source_value"], 0.1)
        self.assertEqual(
            july["rent_to_sales_ratio"]["source_value_status"],
            "source_value_mismatch",
        )
        self.assertTrue(july["rent_to_sales_ratio"]["source_value_mismatch"])
        self.assertIn("不一致", july["rent_to_sales_ratio"]["quality_note"])
        validate_three_month_operating_contract(contract, "2026-07")

        wrong_formal_value = copy.deepcopy(contract)
        wrong_formal_value["months"][-1]["rent_to_sales_ratio"]["value"] = 0.1
        with self.assertRaisesRegex(ValueError, "正式租售比.*不一致"):
            validate_three_month_operating_contract(wrong_formal_value, "2026-07")

    def test_zero_or_missing_revenue_never_produces_formal_ratio(self):
        for label, latest_revenue in (("zero", "0"), ("missing", "")):
            with self.subTest(label=label):
                rows = [
                    {
                        "月份": month,
                        "实际营收": "100000" if month != "2026-07" else latest_revenue,
                        "月租金": "60000",
                        "租售比": "0.1",
                        "月度Gate纳入": "是",
                    }
                    for month in ("2026-05", "2026-06", "2026-07")
                ]
                contract = _three_month_operating_contract(rows, "2026-07")
                july_ratio = contract["months"][-1]["rent_to_sales_ratio"]
                self.assertIsNone(july_ratio["value"])
                self.assertEqual(july_ratio["status"], "unknown")
                self.assertEqual(july_ratio["source_value"], 0.1)
                self.assertEqual(july_ratio["source_value_status"], "not_comparable")
                self.assertIsNone(july_ratio["source_value_mismatch"])

    def test_source_ratio_tolerance_accepts_four_decimal_rounding(self):
        rows = [
            {
                "月份": month,
                "实际营收": "3",
                "月租金": "1",
                "租售比": "0.3333",
                "月度Gate纳入": "是",
            }
            for month in ("2026-05", "2026-06", "2026-07")
        ]
        contract = _three_month_operating_contract(rows, "2026-07")
        ratio = contract["months"][-1]["rent_to_sales_ratio"]
        self.assertEqual(ratio["value"], 0.33333333)
        self.assertEqual(ratio["source_value_status"], "matched")
        self.assertFalse(ratio["source_value_mismatch"])
        self.assertLessEqual(ratio["absolute_difference"], RATIO_SOURCE_COMPARISON_TOLERANCE)

    def test_recent_three_month_contract_uses_null_not_zero_when_cost_is_unknown(self):
        rows = add_display_fields(monthly_rows(revenues=(300000,) * 6, rent_ratios=(0.2,) * 6))
        for row in rows[-3:]:
            row["月租金"] = ""
            row["租金状态"] = "缺租金"
            row["租金来源文件"] = ""
        review = self.build_review(rows, workforce_for(("L0001",)))
        months = review["stores"][0]["recent_three_month_operating"]["months"]
        for month in months:
            self.assertIsNone(month["base_rent"]["amount_yuan"])
            self.assertIsNone(month["property_fee"]["amount_yuan"])
            self.assertIsNone(month["known_occupancy_cost_total"]["amount_yuan"])
            self.assertEqual(month["known_occupancy_cost_total"]["status"], "unknown")
            self.assertIsNone(month["rent_to_sales_ratio"]["value"])
            self.assertEqual(month["rent_to_sales_ratio"]["source_value"], 0.2)
            self.assertEqual(month["rent_to_sales_ratio"]["source_value_status"], "not_comparable")
            self.assertEqual(
                month["data_quality"]["completeness_status"],
                "complete_operating_cost_unknown",
            )

    def test_three_month_schema_file_matches_runtime_contract(self):
        schema_path = (
            Path(__file__).resolve().parents[1]
            / "ai"
            / "schemas"
            / "franchise_store_three_month_operating.v0.1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            THREE_MONTH_OPERATING_SCHEMA_VERSION,
        )
        self.assertEqual(schema["properties"]["months"]["minItems"], 3)
        self.assertEqual(schema["properties"]["months"]["maxItems"], 3)
        ratio_schema = schema["$defs"]["month_record"]["properties"]["rent_to_sales_ratio"]
        self.assertEqual(
            ratio_schema["properties"]["value_tolerance"]["const"],
            RATIO_VALUE_TOLERANCE,
        )
        self.assertEqual(
            ratio_schema["properties"]["source_comparison_tolerance"]["const"],
            RATIO_SOURCE_COMPARISON_TOLERANCE,
        )
        required = set(schema["$defs"]["month_record"]["required"])
        self.assertTrue(
            {
                "month",
                "operating_revenue",
                "base_rent",
                "property_fee",
                "known_occupancy_cost_total",
                "rent_to_sales_ratio",
                "data_cutoff",
                "data_source",
                "data_quality",
            }.issubset(required)
        )

    def test_three_month_contract_rejects_month_gap_or_guessed_cost_split(self):
        rows = add_display_fields(monthly_rows(revenues=(300000,) * 6, rent_ratios=(0.2,) * 6))
        review = self.build_review(rows, workforce_for(("L0001",)))
        contract = review["stores"][0]["recent_three_month_operating"]

        month_gap = copy.deepcopy(contract)
        month_gap["months"][0]["month"] = "2026-04"
        with self.assertRaisesRegex(ValueError, "连续3个完整自然月"):
            validate_three_month_operating_contract(month_gap, "2026-07")

        guessed_split = copy.deepcopy(contract)
        guessed_split["months"][-1]["base_rent"]["amount_yuan"] = 30000
        guessed_split["months"][-1]["base_rent"]["status"] = "known"
        with self.assertRaisesRegex(ValueError, "不得写入候选拆分值"):
            validate_three_month_operating_contract(guessed_split, "2026-07")

    def test_low_trust_personnel_is_only_auxiliary(self):
        rows = add_display_fields(
            monthly_rows(
                revenues=(300000,) * 6,
                customers=(500,) * 6,
                new_customers=(120,) * 6,
                old_customers=(380,) * 6,
                workdays=(200,) * 6,
                therapist_output=(1500,) * 6,
            )
        )
        review = self.build_review(rows, workforce_for(("L0001",), confidence="low"))
        self.assertEqual(review["status"], "ready_for_business_review")
        self.assertEqual(review["stores"][0]["personnel_history"]["evidence_role"], "仅作辅助证据")
        self.assertIn("不得输出较强人员结论", review["stores"][0]["personnel_history"]["note"])

    def test_end_to_end_writes_business_outputs_even_when_candidate_count_is_zero(self):
        operating_rows = add_display_fields(
            monthly_rows(
                revenues=(300000,) * 6,
                customers=(500,) * 6,
                new_customers=(120,) * 6,
                old_customers=(380,) * 6,
                workdays=(200,) * 6,
                therapist_output=(1500,) * 6,
            )
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            operating_path = root / "operating.csv"
            workforce_path = root / "workforce.csv"
            contract_path = root / "contract.json"
            output_root = root / "out"
            write_rows(operating_path, list(operating_rows[0]), operating_rows)
            write_rows(workforce_path, HEADERS, workforce_for(("L0001",)))
            contract_path.write_text(json.dumps(workforce_contract()), encoding="utf-8")
            manifest, run_dir, duplicate = build(
                operating_path=operating_path,
                workforce_path=workforce_path,
                output_root=output_root,
                target_month="2026-07",
                workforce_contract=contract_path,
                today=date(2026, 8, 26),
                now=datetime(2026, 8, 26, tzinfo=timezone.utc),
            )
            business = json.loads((run_dir / "business_review.json").read_text(encoding="utf-8"))
            html_text = (output_root / "business_review.html").read_text(encoding="utf-8")
        self.assertFalse(duplicate)
        self.assertEqual(manifest["business_review_schema_version"], BUSINESS_REVIEW_SCHEMA_VERSION)
        self.assertEqual(
            manifest["three_month_operating_schema_version"],
            THREE_MONTH_OPERATING_SCHEMA_VERSION,
        )
        self.assertEqual(business["candidate_count"], 0)
        self.assertEqual(len(business["stores"]), 1)
        self.assertIn("2026-07", html_text)

    def test_browser_index_switches_between_june_and_july(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for month in ("2026-06", "2026-07"):
                run_dir = root / month / f"run-{month}"
                run_dir.mkdir(parents=True)
                review = {
                    "schema_version": BUSINESS_REVIEW_SCHEMA_VERSION,
                    "target_month": month,
                    "stores": [],
                }
                (run_dir / "business_review.json").write_text(json.dumps(review), encoding="utf-8")
                manifest = {
                    "run_id": f"run-{month}",
                    "run_month": month,
                    "generated_at": f"{month}-28T00:00:00+00:00",
                    "status": "ready_for_business_review",
                    "dashboard_write_allowed": False,
                    "business_review_schema_version": BUSINESS_REVIEW_SCHEMA_VERSION,
                    "three_month_operating_schema_version": THREE_MONTH_OPERATING_SCHEMA_VERSION,
                    "outputs": {"business_review_json": "business_review.json"},
                }
                (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            index = write_business_review_browser(root)
            html_text = (root / "business_review.html").read_text(encoding="utf-8")
        self.assertEqual(index["months"], ["2026-06", "2026-07"])
        self.assertIn("2026-06", html_text)
        self.assertIn("2026-07", html_text)

    def test_browser_escapes_script_terminator_and_never_uses_inner_html(self):
        malicious_name = "测试店</script><script>window.injected=true</script>"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "2026-07" / "run-2026-07"
            run_dir.mkdir(parents=True)
            review = {
                "schema_version": BUSINESS_REVIEW_SCHEMA_VERSION,
                "target_month": "2026-07",
                "stores": [{"store_id": "L0001", "store_name": malicious_name}],
            }
            (run_dir / "business_review.json").write_text(json.dumps(review), encoding="utf-8")
            manifest = {
                "run_id": "run-2026-07",
                "run_month": "2026-07",
                "generated_at": "2026-08-26T00:00:00+00:00",
                "status": "ready_for_business_review",
                "dashboard_write_allowed": False,
                "business_review_schema_version": BUSINESS_REVIEW_SCHEMA_VERSION,
                "three_month_operating_schema_version": THREE_MONTH_OPERATING_SCHEMA_VERSION,
                "outputs": {"business_review_json": "business_review.json"},
            }
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            write_business_review_browser(root)
            html_text = (root / "business_review.html").read_text(encoding="utf-8")
        self.assertNotIn("</script><script>window.injected", html_text)
        self.assertIn("<\\/script><script>window.injected", html_text)
        self.assertNotIn("innerHTML", html_text)

    def test_browser_index_keeps_full_store_payload_without_truncation(self):
        stores = [{"store_id": f"L{index:04d}", "store_name": f"门店{index}"} for index in range(1, 121)]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "2026-07" / "run-2026-07"
            run_dir.mkdir(parents=True)
            review = {
                "schema_version": BUSINESS_REVIEW_SCHEMA_VERSION,
                "target_month": "2026-07",
                "stores": stores,
            }
            (run_dir / "business_review.json").write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
            manifest = {
                "run_id": "run-2026-07",
                "run_month": "2026-07",
                "generated_at": "2026-08-26T00:00:00+00:00",
                "status": "ready_for_business_review",
                "dashboard_write_allowed": False,
                "business_review_schema_version": BUSINESS_REVIEW_SCHEMA_VERSION,
                "three_month_operating_schema_version": THREE_MONTH_OPERATING_SCHEMA_VERSION,
                "outputs": {"business_review_json": "business_review.json"},
            }
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            index = write_business_review_browser(root)
        self.assertEqual(len(index["runs"][0]["review"]["stores"]), 120)
        self.assertEqual(index["runs"][0]["review"]["stores"][-1]["store_id"], "L0120")


if __name__ == "__main__":
    unittest.main()

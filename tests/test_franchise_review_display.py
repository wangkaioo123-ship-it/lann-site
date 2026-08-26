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
    build_business_review,
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
                    "outputs": {"business_review_json": "business_review.json"},
                }
                (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            index = write_business_review_browser(root)
            html_text = (root / "business_review.html").read_text(encoding="utf-8")
        self.assertEqual(index["months"], ["2026-06", "2026-07"])
        self.assertIn("2026-06", html_text)
        self.assertIn("2026-07", html_text)


if __name__ == "__main__":
    unittest.main()

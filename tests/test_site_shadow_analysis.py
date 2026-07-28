import copy
import json
import unittest
from pathlib import Path

from scripts.build_site_shadow_analysis import build_analysis


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "ai" / "evals" / "site_shadow_analysis" / "sijing_input.json"


def load_fixture():
    with FIXTURE.open(encoding="utf-8") as file:
        return json.load(file)


class SiteShadowAnalysisTests(unittest.TestCase):
    def test_sijing_business_boundaries(self):
        result = build_analysis(load_fixture())

        self.assertEqual(
            result["current_stage"]["summary"],
            "租金、前期工程初筛和经营可行性勘察已完成；待专业工程现场勘察",
        )
        self.assertEqual(result["current_stage"]["engineer_site_survey"], "未开始")
        self.assertEqual(result["current_stage"]["contract_engineering_confirmation"], "未开始")
        self.assertIn("不构成盈利保证", result["risk_assessments"][0]["qualification"])
        self.assertFalse(result["writeback_allowed"])
        self.assertTrue(result["human_confirmation_required"])
        self.assertEqual(result["source_registry"][0]["source_id"], "mall-intro")

    def test_customer_site_state_does_not_pollute_customer_state(self):
        result = build_analysis(load_fixture())
        declined = [
            row for row in result["customer_matches"] if row["site_match_state"] == "已放弃该场地"
        ]

        self.assertEqual(len(declined), 3)
        self.assertTrue(all(row["customer_state"] == "继续考察LANN项目" for row in declined))
        self.assertEqual(result["matching_summary"]["recommended_count"], 5)
        self.assertEqual(result["matching_summary"]["considering_count"], 2)

    def test_considering_customers_are_ordered_and_use_correct_deadline(self):
        result = build_analysis(load_fixture())
        considering = [
            row for row in result["customer_matches"] if row["site_match_state"] == "考察该场地"
        ]

        self.assertEqual([row["customer_id"] for row in considering], ["customer-04", "customer-05"])
        self.assertEqual(considering[0]["decision_days"], 14)
        self.assertEqual(considering[0]["decision_deadline"], "2026-08-03")
        self.assertEqual(considering[1]["decision_days"], 7)
        self.assertEqual(considering[1]["decision_deadline"], "2026-07-29")

    def test_overdue_is_pending_not_abandoned(self):
        packet = load_fixture()
        packet["as_of_date"] = "2026-08-05"
        result = build_analysis(packet)
        considering = [
            row for row in result["customer_matches"] if row["site_match_state"] == "考察该场地"
        ]

        self.assertTrue(
            all(row["decision_status"] == "超期未决-待负责人确认" for row in considering)
        )
        self.assertTrue(all(row["site_match_state"] == "考察该场地" for row in considering))
        self.assertTrue(all(row["customer_state"] == "考察中" for row in considering))
        self.assertIn("由负责人确认超期未决客户状态，不自动写为放弃", result["next_actions"])

    def test_explicit_deadline_supports_due_follow_up_and_next_day_overdue(self):
        packet = load_fixture()
        packet["as_of_date"] = "2026-07-26"
        packet["customer_matches"] = [
            {
                "customer_id": "customer-pending",
                "customer_state": "考察中",
                "site_match_state": "考察该场地",
                "decision_deadline": "2026-07-26",
                "next_follow_up_date": "2026-07-27",
                "source_refs": ["customer-status"],
            }
        ]

        due = build_analysis(packet)["customer_matches"][0]
        self.assertEqual(due["decision_status"], "期限已到-待负责人跟进")
        self.assertEqual(due["next_follow_up_date"], "2026-07-27")
        self.assertIsNone(due["decision_days"])

        packet["as_of_date"] = "2026-07-27"
        overdue = build_analysis(packet)["customer_matches"][0]
        self.assertEqual(overdue["decision_status"], "超期未决-待负责人确认")
        self.assertEqual(overdue["site_match_state"], "考察该场地")
        self.assertEqual(overdue["customer_state"], "考察中")

    def test_rules_are_not_tied_to_sijing_name(self):
        packet = copy.deepcopy(load_fixture())
        packet["candidate"]["candidate_id"] = "another-site"
        packet["candidate"]["candidate_name"] = "另一个候选场地"
        result = build_analysis(packet)

        self.assertEqual(result["candidate"]["candidate_name"], "另一个候选场地")
        self.assertEqual(
            result["current_stage"]["summary"],
            "租金、前期工程初筛和经营可行性勘察已完成；待专业工程现场勘察",
        )

    def test_facts_must_reference_known_sources(self):
        packet = load_fixture()
        packet["facts"][0]["source_refs"] = ["unknown-source"]

        with self.assertRaisesRegex(ValueError, "引用未知来源"):
            build_analysis(packet)

    def test_plan_opinion_cannot_be_put_in_facts(self):
        packet = load_fixture()
        packet["facts"][1]["fact_kind"] = "AI推断"

        with self.assertRaisesRegex(ValueError, "人工判断必须进入judgments"):
            build_analysis(packet)

    def test_internal_state_cannot_enable_dashboard_write(self):
        packet = load_fixture()
        packet["intake_control"]["external_writes"]["dashboard_allowed"] = True

        with self.assertRaisesRegex(ValueError, "不得允许dashboard写入"):
            build_analysis(packet)


if __name__ == "__main__":
    unittest.main()

import copy
import json
import unittest
from pathlib import Path

from scripts.build_site_record_candidate import build_site_record
from scripts.build_site_shadow_analysis import build_analysis
from scripts.validate_site_record import validate_site_record


ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "ai" / "evals" / "site_shadow_analysis" / "sijing_input.json"
SCHEMA_PATH = ROOT / "ai" / "schemas" / "site_record.v0.1.schema.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class SiteRecordCandidateBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = load_json(INPUT_PATH)
        cls.schema = load_json(SCHEMA_PATH)

    def test_shadow_analysis_builds_valid_review_candidate(self):
        packet = copy.deepcopy(self.packet)
        packet["facts"].extend(
            [
                {
                    "fact_id": "fact-unit-code",
                    "category": "铺位",
                    "field": "铺位号",
                    "value": "L4015a",
                    "fact_kind": "资料可证实事实",
                    "source_refs": ["unit-plan"],
                    "confidence": "高",
                },
                {
                    "fact_id": "fact-floor",
                    "category": "铺位",
                    "field": "所在楼层",
                    "value": "L4",
                    "fact_kind": "资料可证实事实",
                    "source_refs": ["unit-plan"],
                    "confidence": "高",
                },
                {
                    "fact_id": "fact-area",
                    "category": "铺位",
                    "field": "使用面积",
                    "value": 260,
                    "fact_kind": "资料可证实事实",
                    "source_refs": ["unit-plan"],
                    "confidence": "高",
                },
            ]
        )

        record = build_site_record(build_analysis(packet))

        validate_site_record(record, self.schema)
        self.assertEqual(record["current_stage"]["value"], "可推荐")
        self.assertEqual(record["current_stage"]["confirmation_status"], "待负责人确认")
        self.assertEqual(record["unit"]["value"], {"floor": "L4", "unit_code": "L4015a"})
        self.assertEqual(record["area_sqm"]["value"], 260)
        self.assertEqual(record["responsible_owner"]["value"], None)
        self.assertEqual(record["ownership_model"]["value"], "待定")
        self.assertEqual(record["engineering_precheck"]["value"], "已完成-无明显阻断")
        self.assertEqual(record["operating_feasibility_visit"]["value"], "已完成-值得推进")
        self.assertFalse(record.get("next_follow_up_date"))

    def test_conflicting_objective_facts_stay_out_of_candidate(self):
        packet = copy.deepcopy(self.packet)
        packet["facts"].extend(
            [
                {
                    "fact_id": "fact-area-a",
                    "category": "铺位",
                    "field": "使用面积",
                    "value": 260,
                    "fact_kind": "资料可证实事实",
                    "source_refs": ["unit-plan"],
                    "confidence": "高",
                },
                {
                    "fact_id": "fact-area-b",
                    "category": "铺位",
                    "field": "使用面积",
                    "value": 280,
                    "fact_kind": "资料可证实事实",
                    "source_refs": ["lease-terms"],
                    "confidence": "高",
                },
            ]
        )

        record = build_site_record(build_analysis(packet))

        validate_site_record(record, self.schema)
        self.assertNotIn("area_sqm", record)
        self.assertIn(
            "资料中的使用面积存在冲突，需人工核对",
            record["pending_verifications"]["value"],
        )

    def test_builder_rejects_shadow_result_that_allows_writeback(self):
        analysis = build_analysis(copy.deepcopy(self.packet))
        analysis["writeback_allowed"] = True

        with self.assertRaisesRegex(ValueError, "禁止正式写回"):
            build_site_record(analysis)

    def test_builder_rejects_non_dashboard_stage(self):
        analysis = build_analysis(copy.deepcopy(self.packet))
        analysis["current_stage"]["workflow_stage"] = "等待客户决定"

        with self.assertRaisesRegex(ValueError, "八阶段契约"):
            build_site_record(analysis)

    def test_owner_judgment_keeps_owner_confirmation_boundary(self):
        record = build_site_record(build_analysis(copy.deepcopy(self.packet)))

        validate_site_record(record, self.schema)
        self.assertEqual(record["owner_current_judgment"]["record_layer"], "负责人确认")
        self.assertEqual(record["owner_current_judgment"]["confirmation_status"], "已确认")
        self.assertIn("王凯", record["owner_current_judgment"]["confirmed_by"])

    def test_duplicate_high_blockers_are_deduplicated(self):
        packet = copy.deepcopy(self.packet)
        duplicate = {
            "risk_id": "risk-blocker-duplicate",
            "risk_type": "工程风险",
            "level": "高",
            "statement": "存在明确阻断，等待负责人处理。",
            "owner": "工程负责人",
            "source_refs": ["engineering-standard"],
        }
        packet["risk_assessments"] = [
            {**duplicate, "risk_id": "risk-blocker-a"},
            {**duplicate, "risk_id": "risk-blocker-b"},
        ]

        record = build_site_record(build_analysis(packet))

        validate_site_record(record, self.schema)
        self.assertEqual(record["current_blockers"]["value"], [duplicate["statement"]])


if __name__ == "__main__":
    unittest.main()

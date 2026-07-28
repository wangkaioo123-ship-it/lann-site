import copy
import json
import unittest
from pathlib import Path

from scripts.validate_site_record import validate_site_record


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "ai" / "schemas" / "site_record.v0.1.schema.json"
SAMPLE_PATH = (
    ROOT
    / "ai"
    / "evals"
    / "site_record"
    / "generic_candidate_record.json"
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class SiteRecordSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_json(SCHEMA_PATH)
        cls.sample = load_json(SAMPLE_PATH)

    def test_generic_candidate_fixture_passes_schema_contract(self):
        validate_site_record(self.sample, self.schema)
        business_fields = set(self.schema["properties"]) - {"schema_version"}
        core_fields = set(self.schema["required"]) - {"schema_version"}
        self.assertEqual(len(business_fields), 22)
        self.assertEqual(len(core_fields), 10)
        for field in ("mall_name", "city", "unit", "area_sqm"):
            self.assertEqual(self.sample[field]["record_layer"], "原始资料事实")
            self.assertEqual(self.sample[field]["confirmation_status"], "无需确认")
            self.assertIsNone(self.sample[field]["confirmed_by"])
        self.assertIsNone(self.sample["responsible_owner"]["value"])
        self.assertEqual(
            self.sample["responsible_owner"]["confirmation_status"], "待负责人确认"
        )
        self.assertEqual(self.sample["ownership_model"]["value"], "待定")
        self.assertEqual(
            self.sample["ownership_model"]["confirmation_status"], "待负责人确认"
        )
        self.assertEqual(self.sample["current_stage"]["value"], "待研判")

    def test_missing_object_id_stage_or_next_action_fails(self):
        for field in ("site_id", "current_stage", "next_action"):
            with self.subTest(field=field):
                record = copy.deepcopy(self.sample)
                del record[field]
                with self.assertRaisesRegex(ValueError, "缺少核心字段"):
                    validate_site_record(record, self.schema)

    def test_ai_candidate_cannot_masquerade_as_owner_confirmation(self):
        record = copy.deepcopy(self.sample)
        record["ownership_model"].update(
            {
                "record_layer": "AI提取候选事实",
                "confirmation_status": "已确认",
                "confirmed_by": "AI",
            }
        )
        with self.assertRaisesRegex(ValueError, "AI候选不能伪装成负责人确认"):
            validate_site_record(record, self.schema)

    def test_raw_document_fact_cannot_masquerade_as_owner_confirmation(self):
        record = copy.deepcopy(self.sample)
        record["unit"].update(
            {
                "record_layer": "原始资料事实",
                "confirmation_status": "已确认",
                "confirmed_by": "王凯",
            }
        )
        with self.assertRaisesRegex(ValueError, "原始资料事实不得伪装成负责人确认"):
            validate_site_record(record, self.schema)

    def test_customer_match_state_cannot_be_used_as_site_stage(self):
        record = copy.deepcopy(self.sample)
        record["current_stage"]["value"] = "等待客户决定"

        with self.assertRaisesRegex(ValueError, "不在允许枚举中"):
            validate_site_record(record, self.schema)

    def test_dashboard_site_stage_options_are_exact(self):
        stage_schema = self.schema["properties"]["current_stage"]
        value_spec = next(
            item["properties"]["value"]
            for item in stage_schema["allOf"]
            if "properties" in item
        )
        self.assertEqual(
            value_spec["enum"],
            [
                "待研判",
                "招商接洽",
                "条件核验",
                "可推荐",
                "租赁合约推进",
                "已签约",
                "已开业",
                "暂缓关闭",
            ],
        )


if __name__ == "__main__":
    unittest.main()

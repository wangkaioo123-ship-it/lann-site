import copy
import json
import unittest
from pathlib import Path

from scripts.build_site_shadow_analysis import build_analysis
from scripts.convert_neutral_site_input import convert_neutral_packet


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "ai" / "evals" / "site_shadow_analysis" / "sijing_neutral_input.json"


def load_fixture():
    with FIXTURE.open(encoding="utf-8") as file:
        return json.load(file)


class NeutralSiteInputTests(unittest.TestCase):
    def test_bot_files_and_user_note_enter_site_state(self):
        converted = convert_neutral_packet(load_fixture())

        self.assertEqual(converted["candidate"]["candidate_name"], "泗泾招商花园城")
        self.assertEqual(converted["facts"], [])
        self.assertEqual(converted["judgments"], [])
        self.assertTrue(
            any(row["ref"] == "bot-storage://blobs/fixture-sha256.pdf" for row in converted["sources"])
        )
        notes = [row for row in converted["sources"] if row["title"] == "用户文字补充"]
        self.assertEqual(len(notes), 1)
        self.assertIn("租金已经明确", notes[0]["text_content"])

    def test_untranscribed_voice_is_missing_not_fabricated(self):
        converted = convert_neutral_packet(load_fixture())

        self.assertTrue(any("语音来源 source-kai-voice 未转写" in item for item in converted["missing_information"]))
        self.assertFalse(
            any(row.get("text_content") for row in converted["sources"] if row["source_id"] == "source-kai-voice")
        )
        self.assertEqual(converted["facts"], [])

    def test_dashboard_write_boundary_survives_handshake(self):
        converted = convert_neutral_packet(load_fixture())
        result = build_analysis(converted)

        self.assertFalse(converted["intake_control"]["external_writes"]["dashboard_allowed"])
        self.assertFalse(result["intake_control"]["external_writes"]["dashboard_allowed"])
        self.assertFalse(result["writeback_allowed"])
        self.assertTrue(result["human_confirmation_required"])

    def test_contract_conversion_is_not_reported_as_pdf_parsing(self):
        result = build_analysis(convert_neutral_packet(load_fixture()))

        self.assertEqual(result["analysis_status"], "待资料解析")
        self.assertEqual(result["evidence_facts"], [])
        self.assertIn("由lann-site解析可读取来源，形成带引用的资料事实", result["next_actions"])
        self.assertNotIn("安排专业工程人员现场勘察，核实详细工程条件和改造风险", result["next_actions"])

    def test_rejects_package_that_allows_dashboard_write(self):
        packet = copy.deepcopy(load_fixture())
        packet["external_writes"]["dashboard_allowed"] = True

        with self.assertRaisesRegex(ValueError, "不得允许dashboard写入"):
            convert_neutral_packet(packet)


if __name__ == "__main__":
    unittest.main()

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter

from scripts.parse_site_intake_pdfs import (
    classify_pdf,
    compare_with_baseline,
    diagnose_page,
    extract_life_service_chart_fact,
    extract_page_facts,
    low_confidence_candidates,
    normalize_ocr_text,
    parse_neutral_pdf_package,
    render_review_markdown,
)


def neutral_packet(sha256: str, size: int) -> dict:
    return {
        "schema_version": "lann-site-neutral-input/v0.1",
        "package_purpose": "中性资料归集",
        "project": {"id": "site-test", "name": "测试项目", "status": "collecting"},
        "provenance": {
            "source_channel": "feishu_bot",
            "chat_id": "chat-test",
            "created_by": "user-test",
            "created_at": "2026-07-26T09:00:00.000Z",
            "updated_at": "2026-07-26T09:01:00.000Z",
        },
        "sources": [
            {
                "source_id": "source-pdf",
                "source_kind": "file",
                "original_file_name": "测试.pdf",
                "message_id": "message-test",
                "sender": "user-test",
                "received_at": "2026-07-26T09:00:00.000Z",
                "feishu_resource": {"file_key": "file-test", "message_id": "message-test"},
                "storage": {
                    "sha256": sha256,
                    "bytes": size,
                    "mime_type": "application/pdf",
                    "relative_path": "blobs/test.pdf",
                },
                "archive_error": None,
                "transcription": None,
            }
        ],
        "user_notes": [],
        "requested_action": "collect_sources",
        "confirmation": {"input_summary_confirmed": False, "confirmed_at": None},
        "external_writes": {"dashboard_allowed": False, "dashboard_attempted": False},
    }


class SiteIntakePdfParserTests(unittest.TestCase):
    def test_classifies_text_scan_and_mixed_pages(self):
        self.assertEqual(classify_pdf(["足够长的文本" * 4]), "文本型")
        self.assertEqual(classify_pdf(["", ""]), "扫描型或无可提取文字")
        self.assertEqual(classify_pdf(["足够长的文本" * 4, ""]), "图文混合型")

    def test_extracts_only_labelled_values(self):
        facts = extract_page_facts(
            "楼层 L4 铺位号 L4015a 使用面积：260㎡（暂定，以实测报告为准）"
            "租赁期限 5年（不含装修期：1.5个月）"
            "物业管理费单价：30 元/m²/月（含税）"
        )
        by_field = {row["field"]: row for row in facts}
        self.assertEqual(by_field["铺位号"]["value"], "L4015a")
        self.assertEqual(by_field["使用面积"]["value"], "260")
        self.assertEqual(by_field["所在楼层"]["value"], "L4")
        self.assertEqual(by_field["租赁期限"]["value"], "5年（不含装修期1.5个月）")
        self.assertEqual(by_field["物业管理费"]["value"], "30")
        self.assertFalse(any(row["field"] == "动线评分" for row in facts))

    def test_ocr_spacing_is_normalized_for_label_extraction(self):
        text = normalize_ocr_text("店 铺 编 号 ： L4015a 使 用 面 积 ： 260 m2")
        facts = extract_page_facts(text, "windows_media_ocr")
        by_field = {row["field"]: row for row in facts}
        self.assertEqual(by_field["铺位号"]["value"], "L4015a")
        self.assertEqual(by_field["使用面积"]["value"], "260")
        self.assertEqual(by_field["铺位号"]["recognition_method"], "windows_media_ocr")

    def test_low_confidence_marketing_claim_stays_in_manual_review(self):
        rows = low_confidence_candidates(
            "5公里内无竞品，泗泾站蝉联TOP1",
            "source-handbook",
            6,
            "windows_media_ocr",
        )
        self.assertEqual({row["confidence"] for row in rows}, {"低"})
        self.assertTrue(any(row["field"] == "手册声称_5公里内无竞品" for row in rows))
        self.assertTrue(any("外部竞品地图" in row["reason"] for row in rows))

    def test_page_diagnostics_flags_low_text_and_image_dominance(self):
        class Page:
            width = 100
            height = 100
            lines = []
            rects = []
            curves = []
            images = [{"x0": 0, "x1": 100, "top": 0, "bottom": 100}]

        result = diagnose_page(Page(), "很少文字", [])
        self.assertIn("文字层不足", result["quality_flags"])
        self.assertIn("以图片或复杂图形为主", result["quality_flags"])

    def test_life_service_chart_preserves_category_pairs(self):
        categories = ["超市", "便利店", "花店", "美甲美睫", "美发", "美容SPA", "其他"]

        class Page:
            def extract_words(self):
                words = []
                for index, category in enumerate(categories):
                    x = 100 + index * 100
                    words.extend(
                        [
                            {"text": category, "x0": x, "x1": x + 30, "top": 250},
                            {"text": f"{index + 1}.0%", "x0": x - 10, "x1": x + 10, "top": 200},
                            {"text": f"{index + 2}.0%", "x0": x + 20, "x1": x + 40, "top": 200},
                        ]
                    )
                return words

        fact = extract_life_service_chart_fact(Page(), "居住客群 生活服务消费频次占比")
        self.assertEqual(fact["field"], "报告口径_居住客群生活服务消费频次占比")
        self.assertEqual(fact["value"]["美容SPA"], {"区域内": 6.0, "区域外": 7.0})
        self.assertEqual(fact["recognition_method"], "pdfplumber_layout")

    def test_baseline_comparison_reports_only_new_fact_values(self):
        baseline = {"schema_version": "v0.1", "extracted_facts": [{"field": "铺位号", "value": "A1"}]}
        review = {
            "extracted_facts": [
                {"field": "铺位号", "value": "A1"},
                {
                    "field": "报告口径_美业特征",
                    "value": "有外溢",
                    "recognition_method": "pdfplumber_text_layer",
                    "confidence": "中",
                },
            ]
        }
        comparison = compare_with_baseline(review, baseline)
        self.assertEqual(comparison["baseline_fact_count"], 1)
        self.assertEqual(len(comparison["added_facts"]), 1)
        self.assertEqual(comparison["added_facts"][0]["field"], "报告口径_美业特征")

    def test_real_pipeline_keeps_dashboard_guard_and_marks_blank_pdf_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "blobs" / "test.pdf"
            pdf_path.parent.mkdir()
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            with pdf_path.open("wb") as file:
                writer.write(file)
            raw = pdf_path.read_bytes()
            packet = neutral_packet(hashlib.sha256(raw).hexdigest(), len(raw))

            internal, review = parse_neutral_pdf_package(packet, root)

            self.assertFalse(internal["intake_control"]["external_writes"]["dashboard_allowed"])
            self.assertEqual(review["document_inventory"][0]["pdf_type"], "扫描型或无可提取文字")
            self.assertEqual(review["extracted_facts"], [])
            self.assertTrue(
                any(
                    item.startswith("未收到LANN标准工程条件表")
                    for item in internal["missing_information"]
                )
            )
            self.assertIn("未对楼层、铺位、人流动线或生意优劣评分", review["guardrails"])
            self.assertIn("Dashboard写入：禁止", render_review_markdown(review))

    def test_rejects_dashboard_write_permission(self):
        packet = neutral_packet("unused", 0)
        packet = copy.deepcopy(packet)
        packet["external_writes"]["dashboard_allowed"] = True
        with self.assertRaisesRegex(ValueError, "不得允许dashboard写入"):
            parse_neutral_pdf_package(packet, Path("."))


if __name__ == "__main__":
    unittest.main()

import copy
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from scripts.convert_neutral_site_input import convert_neutral_packet
from scripts.parse_site_intake_supplements import apply_supplements


def source_record(
    source_id: str,
    file_name: str,
    relative_path: str,
    mime_type: str,
    raw: bytes,
) -> dict:
    return {
        "source_id": source_id,
        "source_kind": "image" if mime_type.startswith("image/") else "file",
        "original_file_name": file_name,
        "message_id": f"message-{source_id}",
        "sender": "user-test",
        "received_at": "2026-07-26T10:00:00.000Z",
        "feishu_resource": {"message_id": f"message-{source_id}"},
        "storage": {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "mime_type": mime_type,
            "relative_path": relative_path,
        },
        "archive_error": None,
        "transcription": None,
    }


def neutral_packet(sources: list[dict]) -> dict:
    return {
        "schema_version": "lann-site-neutral-input/v0.1",
        "package_purpose": "中性资料归集",
        "project": {"id": "site-test", "name": "测试项目", "status": "collecting"},
        "provenance": {
            "source_channel": "feishu_bot",
            "chat_id": "chat-test",
            "created_by": "user-test",
            "created_at": "2026-07-26T09:00:00.000Z",
            "updated_at": "2026-07-26T10:00:00.000Z",
        },
        "sources": sources,
        "user_notes": [],
        "requested_action": "collect_sources",
        "confirmation": {"input_summary_confirmed": False, "confirmed_at": None},
        "external_writes": {"dashboard_allowed": False, "dashboard_attempted": False},
    }


def empty_review() -> dict:
    return {
        "schema_version": "site-intake-pdf-review/v0.2",
        "manual_review_items": [],
        "missing_information": [],
        "guardrails": [],
        "external_writes": {"dashboard_allowed": False, "dashboard_attempted": False},
    }


def write_fixture_xlsx(path: Path) -> bytes:
    shared = [
        "Lann开店工程条件及场地需求清单",
        "序号",
        "分项工程",
        "项目名称",
        "Lann开店条件要求",
        "备注",
        "物业反馈/回复",
        "土建工程",
        "层高",
        "净高不低于3.2米",
        "暖通工程",
        "新风",
        "新风量不低于1500m³/h",
        "原则上可以，待现场确认",
        "强弱电",
        "电力供应",
        "营业用电60KW",
        "无法提供",
    ]
    shared_xml = "".join(f"<si><t>{value}</t></si>" for value in shared)
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="工程条件" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    rows = [
        '<row r="1"><c r="A1" t="s"><v>0</v></c></row>',
        (
            '<row r="4"><c r="A4" t="s"><v>1</v></c><c r="B4" t="s"><v>2</v></c>'
            '<c r="C4" t="s"><v>3</v></c><c r="D4" t="s"><v>4</v></c>'
            '<c r="E4" t="s"><v>5</v></c><c r="F4" t="s"><v>6</v></c></row>'
        ),
        (
            '<row r="5"><c r="A5"><v>1</v></c><c r="B5" t="s"><v>7</v></c>'
            '<c r="C5" t="s"><v>8</v></c><c r="D5" t="s"><v>9</v></c><c r="F5"/></row>'
        ),
        (
            '<row r="6"><c r="A6"><v>2</v></c><c r="B6" t="s"><v>10</v></c>'
            '<c r="C6" t="s"><v>11</v></c><c r="D6" t="s"><v>12</v></c>'
            '<c r="F6" t="s"><v>13</v></c></row>'
        ),
        (
            '<row r="7"><c r="A7"><v>3</v></c><c r="B7" t="s"><v>14</v></c>'
            '<c r="C7" t="s"><v>15</v></c><c r="D7" t="s"><v>16</v></c>'
            '<c r="F7" t="s"><v>17</v></c></row>'
        ),
    ]
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(rows)}</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{shared_xml}</sst>')
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return path.read_bytes()


class SiteIntakeSupplementTests(unittest.TestCase):
    def test_image_hash_message_and_labelled_candidates_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "blobs" / "screenshot.png"
            image_path.parent.mkdir()
            Image.new("RGB", (80, 40), "white").save(image_path)
            raw = image_path.read_bytes()
            source = source_record(
                "source-image",
                "铺位推荐截图.png",
                "blobs/screenshot.png",
                "image/png",
                raw,
            )
            packet = neutral_packet([source])
            internal = convert_neutral_packet(packet)
            internal["facts"] = [
                {
                    "fact_id": "pdf-fact-unit",
                    "category": "铺位",
                    "field": "铺位号",
                    "value": "L4015a",
                    "fact_kind": "资料可证实事实",
                    "confidence": "高",
                    "recognition_method": "pdf_text_layer",
                    "source_refs": ["source-image"],
                },
                {
                    "fact_id": "pdf-fact-area",
                    "category": "铺位",
                    "field": "使用面积",
                    "value": "260",
                    "fact_kind": "资料可证实事实",
                    "confidence": "高",
                    "recognition_method": "pdf_text_layer",
                    "source_refs": ["source-image"],
                },
                {
                    "fact_id": "pdf-fact-floor",
                    "category": "铺位",
                    "field": "所在楼层",
                    "value": "L4",
                    "fact_kind": "资料可证实事实",
                    "confidence": "高",
                    "recognition_method": "pdf_text_layer",
                    "source_refs": ["source-image"],
                },
            ]
            internal, review = apply_supplements(
                packet,
                root,
                internal,
                empty_review(),
                ocr_cache={
                    "source-image": {
                        "engine": "fixture-ocr",
                        "text": "推荐铺位：L4015a 使用面积：260㎡ 楼层：L4",
                        "lines": [],
                    }
                },
            )

            image_review = review["image_sources"][0]
            self.assertTrue(image_review["hash_verified"])
            self.assertEqual(image_review["message_id"], "message-source-image")
            self.assertEqual(
                {item["field"] for item in review["image_fact_candidates"]},
                {"推荐铺位", "面积", "楼层"},
            )
            self.assertTrue(
                all(item["verification_status"] == "待人工核验" for item in review["image_fact_candidates"])
            )
            self.assertEqual(len(internal["facts"]), 3)
            self.assertEqual(
                {item["comparison_status"] for item in review["image_evidence_comparison"]},
                {"重复印证"},
            )
            self.assertFalse(internal["intake_control"]["external_writes"]["dashboard_allowed"])
            self.assertTrue(any("不据截图判断动线" in item for item in review["guardrails"]))

    def test_low_confidence_unlabelled_image_result_only_enters_manual_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "blobs" / "screenshot.png"
            image_path.parent.mkdir()
            Image.new("RGB", (80, 40), "white").save(image_path)
            raw = image_path.read_bytes()
            source = source_record(
                "source-image",
                "截图.png",
                "blobs/screenshot.png",
                "image/png",
                raw,
            )
            packet = neutral_packet([source])
            _, review = apply_supplements(
                packet,
                root,
                convert_neutral_packet(packet),
                empty_review(),
                ocr_cache={"source-image": {"engine": "fixture-ocr", "text": "L4015a 260㎡"}},
            )

            self.assertEqual(review["image_fact_candidates"], [])
            self.assertEqual({item["confidence"] for item in review["manual_review_items"]}, {"低"})

    def test_engineering_requirements_replies_and_machine_status_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook_path = root / "blobs" / "engineering.xlsx"
            workbook_path.parent.mkdir()
            raw = write_fixture_xlsx(workbook_path)
            source = source_record(
                "source-engineering",
                "Lann开店工程条件2024.xlsx",
                "blobs/engineering.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                raw,
            )
            packet = neutral_packet([source])
            internal, review = apply_supplements(
                packet,
                root,
                convert_neutral_packet(packet),
                empty_review(),
                enable_image_ocr=False,
            )

            workbook = review["engineering_workbooks"][0]
            self.assertEqual(workbook["classification"], "LANN标准要求与项目填写核对表兼有")
            self.assertEqual(workbook["requirement_count"], 3)
            self.assertEqual(workbook["merchant_reply_count"], 2)
            self.assertEqual(workbook["vague_reply_count"], 1)
            self.assertEqual(workbook["key_blocker_count"], 1)
            requirements = workbook["sheets"][0]["requirements"]
            self.assertEqual(requirements[0]["normalized_status_candidate"], "信息不足")
            self.assertEqual(requirements[1]["merchant_reply"], "原则上可以，待现场确认")
            self.assertEqual(requirements[1]["normalized_status_candidate"], "有条件满足")
            self.assertTrue(requirements[1]["machine_interpretation"])
            self.assertEqual(requirements[2]["normalized_status_candidate"], "不满足")
            standard_facts = [
                row for row in internal["facts"] if row["category"] == "LANN标准工程要求"
            ]
            reply_facts = [
                row
                for row in internal["facts"]
                if row["category"] == "商场/铺位实际条件回复原文"
            ]
            self.assertEqual(len(standard_facts), 3)
            self.assertEqual(len(reply_facts), 2)
            self.assertEqual(reply_facts[0]["value"], "原则上可以，待现场确认")
            self.assertEqual(reply_facts[0]["recognition_method"], "xlsx_ooxml_cell_verbatim")
            self.assertTrue(
                any("机器归一化状态仍待人工逐项确认" in item for item in internal["missing_information"])
            )

    def test_rejects_dashboard_write_permission(self):
        packet = neutral_packet([])
        packet = copy.deepcopy(packet)
        packet["external_writes"]["dashboard_allowed"] = True
        internal = convert_neutral_packet({**packet, "external_writes": {"dashboard_allowed": False, "dashboard_attempted": False}})
        with self.assertRaisesRegex(ValueError, "不得允许dashboard写入"):
            apply_supplements(packet, Path("."), internal, empty_review())


if __name__ == "__main__":
    unittest.main()

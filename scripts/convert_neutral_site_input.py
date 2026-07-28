"""Convert lann-work-bot's neutral intake package into lann-site's internal analysis state."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any


NEUTRAL_SCHEMA = "lann-site-neutral-input/v0.1"


def package_date(packet: dict[str, Any]) -> str:
    for value in (packet["provenance"].get("updated_at"), packet["provenance"].get("created_at")):
        candidate = str(value or "")[:10]
        try:
            return date.fromisoformat(candidate).isoformat()
        except ValueError:
            continue
    raise ValueError("provenance缺少可用日期")


def validate_neutral_packet(packet: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "package_purpose",
        "project",
        "provenance",
        "sources",
        "user_notes",
        "requested_action",
        "confirmation",
        "external_writes",
    }
    missing = sorted(required - packet.keys())
    if missing:
        raise ValueError(f"Bot中性输入缺少字段: {', '.join(missing)}")
    if packet["schema_version"] != NEUTRAL_SCHEMA:
        raise ValueError(f"不支持的Bot输入版本: {packet['schema_version']}")
    if packet["external_writes"].get("dashboard_allowed") is not False:
        raise ValueError("Bot中性输入不得允许dashboard写入")
    if packet["external_writes"].get("dashboard_attempted") is not False:
        raise ValueError("Bot中性输入显示已尝试dashboard写入，拒绝接收")
    for field in ("id", "name", "status"):
        if not str(packet["project"].get(field, "")).strip():
            raise ValueError(f"project.{field}不能为空")
    source_ids = [str(row.get("source_id", "")).strip() for row in packet["sources"]]
    if any(not item for item in source_ids):
        raise ValueError("sources存在空source_id")
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("sources存在重复source_id")
    package_date(packet)


def source_type(source: dict[str, Any]) -> str:
    name = str(source.get("original_file_name") or "").lower()
    if str(source.get("source_kind") or "").lower() in {"audio", "voice"}:
        return "语音转写"
    if "工程" in name:
        return "LANN标准工程条件"
    if "铺位" in name or "平面" in name:
        return "铺位图"
    if "租赁" in name or "租金" in name or "商务" in name:
        return "租赁条件"
    if "调研" in name:
        return "调研报告"
    if "商场" in name or "项目介绍" in name:
        return "商场介绍"
    return "其他"


def source_ref(source: dict[str, Any]) -> str:
    storage = source.get("storage") or {}
    if storage.get("relative_path"):
        return f"bot-storage://{storage['relative_path']}"
    message_id = source.get("message_id") or source.get("source_id")
    return f"feishu-message://{message_id}"


def convert_source(source: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    source_id = source["source_id"]
    transcription = source.get("transcription") or {}
    text = str(transcription.get("text") or "").strip()
    archive_error = source.get("archive_error")
    storage = source.get("storage")
    availability = "不可读取" if archive_error else ("可读取" if storage else "缺失")
    converted = {
        "source_id": source_id,
        "source_type": source_type(source),
        "title": source.get("original_file_name") or f"来源 {source_id}",
        "ref": source_ref(source),
        "availability": availability,
    }
    if text:
        converted["text_content"] = text
    if source.get("message_id"):
        converted["message_id"] = source["message_id"]
    if storage:
        if storage.get("sha256"):
            converted["sha256"] = storage["sha256"]
        if storage.get("mime_type"):
            converted["mime_type"] = storage["mime_type"]

    gaps: list[str] = []
    if availability != "可读取":
        gaps.append(f"来源 {source_id} 未形成可读取的本地原文件")
    if converted["source_type"] == "语音转写":
        if not text:
            status = transcription.get("status") or "unknown"
            gaps.append(f"语音来源 {source_id} 未转写（状态：{status}）")
        else:
            gaps.append(f"语音来源 {source_id} 转写已接收，尚未由lann-site结构化")
    elif availability == "可读取":
        gaps.append(f"来源 {source_id} 已接收，但文件内容尚未由lann-site解析")
    return converted, gaps


def convert_neutral_packet(packet: dict[str, Any]) -> dict[str, Any]:
    validate_neutral_packet(packet)
    project = packet["project"]
    provenance = packet["provenance"]
    package_source_id = "bot-package"
    existing_ids = {row["source_id"] for row in packet["sources"]}
    while package_source_id in existing_ids:
        package_source_id = f"_{package_source_id}"

    sources = [
        {
            "source_id": package_source_id,
            "source_type": "其他",
            "title": "lann-work-bot中性输入包",
            "ref": f"feishu-chat://{provenance.get('chat_id') or 'unknown'}/project/{project['id']}",
            "availability": "可读取",
            "text_content": packet["package_purpose"],
        }
    ]
    missing_information = ["项目城市未由Bot中性输入提供"]
    for source in packet["sources"]:
        converted, gaps = convert_source(source)
        sources.append(converted)
        missing_information.extend(gaps)

    for index, note in enumerate(packet["user_notes"], start=1):
        note_id = f"bot-note-{note.get('message_id') or index}"
        while any(row["source_id"] == note_id for row in sources):
            note_id = f"_{note_id}"
        sources.append(
            {
                "source_id": note_id,
                "source_type": "其他",
                "title": "用户文字补充",
                "ref": f"feishu-message://{note.get('message_id') or index}",
                "availability": "可读取",
                "text_content": str(note.get("text") or ""),
            }
        )
        missing_information.append(f"用户文字补充 {note_id} 尚未区分为事实、判断或待确认项")

    missing_information.extend(
        [
            "租金、工程、经营可行性及签约阶段状态尚未由lann-site从资料中提取",
            "客户状态、场地状态和匹配状态尚未提供或尚未结构化",
        ]
    )
    control = {
        "upstream_schema": packet["schema_version"],
        "project_status": project["status"],
        "source_channel": provenance["source_channel"],
        "requested_action": packet["requested_action"],
        "input_summary_confirmed": packet["confirmation"]["input_summary_confirmed"],
        "confirmed_at": packet["confirmation"]["confirmed_at"],
        "external_writes": packet["external_writes"],
    }
    return {
        "schema_version": "0.1",
        "analysis_id": f"neutral-{project['id']}-{package_date(packet).replace('-', '')}",
        "as_of_date": package_date(packet),
        "candidate": {
            "candidate_id": project["id"],
            "candidate_name": project["name"],
            "city": "未知",
        },
        "sources": sources,
        "facts": [],
        "judgments": [],
        "stage_status": {
            "workflow_stage": "待研判",
            "rent": "未确认",
            "engineering_precheck": "未开始",
            "operating_feasibility_visit": "待人工确认",
            "engineer_site_survey": "未开始",
            "contract_engineering_confirmation": "未开始",
            "source_refs": [package_source_id],
        },
        "risk_assessments": [],
        "customer_matches": [],
        "missing_information": list(dict.fromkeys(missing_information)),
        "intake_control": control,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Bot neutral input to Site internal state.")
    parser.add_argument("--input", required=True, help="lann-site-neutral-input/v0.1 JSON.")
    parser.add_argument("--output", required=True, help="Site internal analysis input JSON.")
    args = parser.parse_args()

    with Path(args.input).open(encoding="utf-8") as file:
        packet = json.load(file)
    converted = convert_neutral_packet(packet)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(converted, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"Bot中性输入已接收: {converted['candidate']['candidate_name']}")
    print(f"来源文件及用户补充数: {len(converted['sources']) - 1}")
    print(f"资料事实数: {len(converted['facts'])}（尚未解析PDF内容）")
    print(f"缺口数: {len(converted['missing_information'])}")
    print("dashboard写入: 禁止")


if __name__ == "__main__":
    main()

"""Build a local-only candidate-site shadow analysis from structured evidence."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


NORMAL_DECISION_DAYS = 14
URGENT_DECISION_DAYS = 7
SITE_STAGE_OPTIONS = {
    "待研判",
    "招商接洽",
    "条件核验",
    "可推荐",
    "租赁合约推进",
    "已签约",
    "已开业",
    "暂缓关闭",
}


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def unique_ids(rows: list[dict[str, Any]], field: str, label: str) -> None:
    values = [str(row.get(field, "")).strip() for row in rows]
    if any(not value for value in values):
        raise ValueError(f"{label}存在空{field}")
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"{label}{field}重复: {', '.join(duplicates)}")


def validate_packet(packet: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "analysis_id",
        "as_of_date",
        "candidate",
        "sources",
        "facts",
        "judgments",
        "stage_status",
        "risk_assessments",
        "customer_matches",
        "missing_information",
        "intake_control",
    }
    missing = sorted(required - packet.keys())
    if missing:
        raise ValueError(f"输入缺少字段: {', '.join(missing)}")
    if packet["schema_version"] != "0.1":
        raise ValueError("仅支持 schema_version=0.1")
    external_writes = packet["intake_control"].get("external_writes", {})
    if external_writes.get("dashboard_allowed") is not False:
        raise ValueError("内部分析态不得允许dashboard写入")
    if external_writes.get("dashboard_attempted") is not False:
        raise ValueError("内部分析态显示已尝试dashboard写入，拒绝生成影子结果")

    candidate = packet["candidate"]
    for field in ("candidate_id", "candidate_name", "city"):
        if not str(candidate.get(field, "")).strip():
            raise ValueError(f"candidate.{field}不能为空")
    workflow_stage = packet["stage_status"].get("workflow_stage")
    if workflow_stage not in SITE_STAGE_OPTIONS:
        raise ValueError(
            "stage_status.workflow_stage必须使用Dashboard场地阶段，"
            "不得使用客户或匹配状态"
        )

    unique_ids(packet["sources"], "source_id", "资料来源")
    unique_ids(packet["facts"], "fact_id", "资料事实")
    unique_ids(packet["judgments"], "judgment_id", "人工判断")
    unique_ids(packet["risk_assessments"], "risk_id", "风险判断")
    unique_ids(packet["customer_matches"], "customer_id", "客户匹配")

    source_ids = {row["source_id"] for row in packet["sources"]}
    for collection_name in ("facts", "judgments", "risk_assessments", "customer_matches"):
        for row in packet[collection_name]:
            refs = row.get("source_refs", [])
            unknown = sorted(set(refs) - source_ids)
            if unknown:
                raise ValueError(f"{collection_name}引用未知来源: {', '.join(unknown)}")
    stage_unknown = sorted(set(packet["stage_status"].get("source_refs", [])) - source_ids)
    if stage_unknown:
        raise ValueError(f"stage_status引用未知来源: {', '.join(stage_unknown)}")
    for fact in packet["facts"]:
        if fact.get("fact_kind") != "资料可证实事实":
            raise ValueError("facts只允许资料可证实事实；人工判断必须进入judgments")

    parse_date(packet["as_of_date"])
    for customer in packet["customer_matches"]:
        recommended_at = customer.get("recommended_at")
        explicit_deadline = customer.get("decision_deadline")
        if recommended_at:
            parse_date(recommended_at)
        if explicit_deadline:
            parse_date(explicit_deadline)
        if not recommended_at and not explicit_deadline:
            raise ValueError("客户匹配必须提供recommended_at或decision_deadline")
        if customer.get("next_follow_up_date"):
            parse_date(customer["next_follow_up_date"])


def stage_summary(stage: dict[str, str]) -> str:
    if stage["engineer_site_survey"] == "已完成-存在阻断问题":
        return "专业工程勘察发现阻断问题，等待人工决定是否继续"
    if stage["contract_engineering_confirmation"] == "已确认":
        return "签约前最终工程条件已确认"
    if (
        stage["rent"] in {"区间已确认", "已明确"}
        and stage["engineering_precheck"] == "已完成-无阻断问题"
        and stage["operating_feasibility_visit"] == "已完成-值得推进"
        and stage["engineer_site_survey"] in {"未开始", "已安排"}
    ):
        return "租金、前期工程初筛和经营可行性勘察已完成；待专业工程现场勘察"
    return stage["workflow_stage"]


def customer_result(customer: dict[str, str], as_of: date) -> dict[str, Any]:
    recommended_at = customer.get("recommended_at")
    urgency = customer.get("urgency")
    days = None
    if recommended_at:
        days = URGENT_DECISION_DAYS if urgency == "紧急" else NORMAL_DECISION_DAYS
    deadline = (
        parse_date(customer["decision_deadline"])
        if customer.get("decision_deadline")
        else parse_date(recommended_at) + timedelta(days=days)
    )
    decision_status = customer["site_match_state"]
    if customer["site_match_state"] == "考察该场地":
        if as_of > deadline:
            decision_status = "超期未决-待负责人确认"
        elif as_of == deadline:
            decision_status = "期限已到-待负责人跟进"
        else:
            decision_status = "决策期内考察中"
    return {
        **customer,
        "decision_days": days,
        "decision_deadline": deadline.isoformat(),
        "decision_status": decision_status,
    }


def next_actions(
    stage: dict[str, str],
    customers: list[dict[str, Any]],
    source_summary: dict[str, list[str]],
    packet: dict[str, Any],
    analysis_status: str,
) -> list[str]:
    actions: list[str] = []
    if analysis_status == "待资料解析":
        actions.append("由lann-site解析可读取来源，形成带引用的资料事实")
        if any(row.get("text_content") for row in packet["sources"]):
            actions.append("将用户文字补充或语音转写区分为事实、判断和待确认项")
        if any("未转写" in item for item in packet["missing_information"]):
            actions.append("完成未转写语音的转写，或由用户补充等价文字")
        if not packet["intake_control"]["input_summary_confirmed"]:
            actions.append("等待输入摘要人工确认")
        if source_summary["缺失"] or source_summary["不可读取"]:
            actions.append("补充缺失或不可读取的资料来源")
        return list(dict.fromkeys(actions))
    if stage["engineer_site_survey"] == "未开始":
        actions.append("安排专业工程人员现场勘察，核实详细工程条件和改造风险")
    elif stage["engineer_site_survey"] == "已安排":
        actions.append("完成专业工程现场勘察并记录阻断问题")
    if stage["contract_engineering_confirmation"] != "已确认":
        actions.append("签约前完成最终工程条件确认，并将责任和条件固化到合同条款")
    considering = [row for row in customers if row["site_match_state"] == "考察该场地"]
    if considering:
        actions.append("按推荐时间顺序跟进仍在考察该场地的客户")
    if any(row["decision_status"] == "超期未决-待负责人确认" for row in considering):
        actions.append("由负责人确认超期未决客户状态，不自动写为放弃")
    if source_summary["缺失"] or source_summary["不可读取"]:
        actions.append("补充缺失或不可读取的资料来源")
    return list(dict.fromkeys(actions))


def build_analysis(packet: dict[str, Any]) -> dict[str, Any]:
    validate_packet(packet)
    as_of = parse_date(packet["as_of_date"])
    sources = packet["sources"]
    source_summary = {
        "可读取": [row["source_id"] for row in sources if row["availability"] == "可读取"],
        "缺失": [row["source_id"] for row in sources if row["availability"] == "缺失"],
        "不可读取": [row["source_id"] for row in sources if row["availability"] == "不可读取"],
    }
    customers = sorted(
        (customer_result(row, as_of) for row in packet["customer_matches"]),
        key=lambda row: (
            row.get("recommended_at") or row["decision_deadline"],
            row["customer_id"],
        ),
    )
    considering = [row for row in customers if row["site_match_state"] == "考察该场地"]
    matching_summary = {
        "recommended_count": len(customers),
        "site_declined_count": sum(row["site_match_state"] == "已放弃该场地" for row in customers),
        "considering_count": len(considering),
        "matched_count": sum(row["site_match_state"] == "已匹配" for row in customers),
        "overdue_pending_count": sum(
            row["decision_status"] == "超期未决-待负责人确认" for row in customers
        ),
        "separation_note": "客户状态、场地状态和匹配状态独立；放弃该场地不等于放弃LANN项目。",
    }
    risks = [
        {
            **row,
            "qualification": (
                "仅表示当前经营收益风险判断，不构成盈利保证。"
                if row["risk_type"] == "经营收益风险"
                else "该风险判断需结合后续证据和人工确认。"
            ),
        }
        for row in packet["risk_assessments"]
    ]
    stage = packet["stage_status"]
    analysis_status = (
        "结构化影子分析待人工确认"
        if packet["facts"] or packet["judgments"] or packet["risk_assessments"] or packet["customer_matches"]
        else "待资料解析"
    )
    return {
        "schema_version": "0.1",
        "analysis_id": packet["analysis_id"],
        "analysis_as_of": packet["as_of_date"],
        "analysis_status": analysis_status,
        "candidate": packet["candidate"],
        "intake_control": packet["intake_control"],
        "source_registry": sources,
        "source_summary": source_summary,
        "evidence_facts": packet["facts"],
        "owner_judgments": packet["judgments"],
        "current_stage": {
            **stage,
            "summary": stage_summary(stage),
            "engineering_boundary": "前期工程初筛不等于专业工程现场勘察，也不等于签约前最终工程确认。",
        },
        "risk_assessments": risks,
        "matching_summary": matching_summary,
        "customer_matches": customers,
        "missing_information": list(dict.fromkeys(packet["missing_information"])),
        "next_actions": next_actions(stage, customers, source_summary, packet, analysis_status),
        "human_confirmation_required": True,
        "writeback_allowed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local-only candidate-site shadow analysis.")
    parser.add_argument("--input", required=True, help="Structured input JSON.")
    parser.add_argument("--output", required=True, help="Local shadow output JSON.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    with input_path.open(encoding="utf-8") as file:
        packet = json.load(file)
    result = build_analysis(packet)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"影子分析已生成: {output_path}")
    print(f"项目: {result['candidate']['candidate_name']}")
    print(f"阶段: {result['current_stage']['summary']}")
    print(f"客户匹配: {result['matching_summary']}")
    print("写回正式业务数据: 否")


if __name__ == "__main__":
    main()

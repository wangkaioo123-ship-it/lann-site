"""Build a review-only site_record/v0.1 candidate from Site shadow analysis."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from scripts.validate_site_record import validate_site_record


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

ENGINEERING_PRECHECK_MAP = {
    "未开始": "未开始",
    "进行中": "进行中",
    "已完成-无阻断问题": "已完成-无明显阻断",
    "已完成-存在阻断问题": "已完成-存在阻断",
}

OPERATING_VISIT_MAP = {
    "未开始": "未开始",
    "待人工确认": "待确认",
    "已完成-值得推进": "已完成-值得推进",
    "已完成-不建议推进": "已完成-不建议推进",
}

ENGINEER_SURVEY_MAP = {
    "未开始": "未开始",
    "已安排": "已安排",
    "已完成-无阻断问题": "已完成-无阻断",
    "已完成-存在阻断问题": "已完成-存在阻断",
}


def envelope(
    value: Any,
    *,
    layer: str,
    confirmation_status: str,
    confirmed_by: str | None,
    source_refs: list[str],
) -> dict[str, Any]:
    refs = list(dict.fromkeys(str(ref).strip() for ref in source_refs if str(ref).strip()))
    if not refs:
        raise ValueError("候选字段必须保留至少一个来源引用")
    return {
        "value": value,
        "record_layer": layer,
        "confirmation_status": confirmation_status,
        "confirmed_by": confirmed_by,
        "source_refs": refs,
    }


def candidate_envelope(value: Any, source_refs: list[str]) -> dict[str, Any]:
    return envelope(
        value,
        layer="AI提取候选事实",
        confirmation_status="待负责人确认",
        confirmed_by=None,
        source_refs=source_refs,
    )


def source_ids(analysis: dict[str, Any]) -> list[str]:
    refs = [
        str(row.get("source_id", "")).strip()
        for row in analysis.get("source_registry", [])
        if str(row.get("source_id", "")).strip()
    ]
    return list(dict.fromkeys(refs)) or [f"analysis:{analysis['analysis_id']}"]


def fact_value(
    analysis: dict[str, Any],
    aliases: set[str],
) -> tuple[Any | None, list[str], bool]:
    rows = [
        row
        for row in analysis.get("evidence_facts", [])
        if str(row.get("field", "")).strip() in aliases
    ]
    if not rows:
        return None, [], False

    values: dict[str, Any] = {}
    refs: list[str] = []
    for row in rows:
        value = row.get("value")
        values[json.dumps(value, ensure_ascii=False, sort_keys=True)] = value
        refs.extend(row.get("source_refs", []))
    if len(values) != 1:
        return None, list(dict.fromkeys(refs)), True
    return next(iter(values.values())), list(dict.fromkeys(refs)), False


def matching_status(summary: dict[str, Any]) -> str:
    if int(summary.get("matched_count", 0)) > 0:
        return "已有客户确认"
    if int(summary.get("considering_count", 0)) > 0:
        return (
            "部分客户放弃场地"
            if int(summary.get("site_declined_count", 0)) > 0
            else "等待客户决定"
        )
    if int(summary.get("recommended_count", 0)) == 0:
        return "未开始"
    return "无客户继续"


def evidence_level(analysis: dict[str, Any]) -> str:
    readable = len(analysis.get("source_summary", {}).get("可读取", []))
    unavailable = sum(
        len(analysis.get("source_summary", {}).get(key, []))
        for key in ("缺失", "不可读取")
    )
    facts = len(analysis.get("evidence_facts", []))
    missing = len(analysis.get("missing_information", []))
    if facts > 0 and unavailable == 0 and missing == 0:
        return "高"
    if facts > 0 or readable >= 2:
        return "中"
    return "低"


def build_site_record(analysis: dict[str, Any]) -> dict[str, Any]:
    required = {
        "analysis_id",
        "analysis_as_of",
        "candidate",
        "source_registry",
        "source_summary",
        "evidence_facts",
        "owner_judgments",
        "current_stage",
        "risk_assessments",
        "matching_summary",
        "missing_information",
        "next_actions",
    }
    missing_keys = sorted(required - analysis.keys())
    if missing_keys:
        raise ValueError(f"影子分析缺少字段: {', '.join(missing_keys)}")
    if analysis.get("writeback_allowed") is not False:
        raise ValueError("只允许从禁止正式写回的影子分析生成候选记录")

    candidate = analysis["candidate"]
    stage = analysis["current_stage"]
    workflow_stage = str(stage.get("workflow_stage", "")).strip()
    if workflow_stage not in SITE_STAGE_OPTIONS:
        raise ValueError("影子分析场地阶段不符合Dashboard八阶段契约")

    all_refs = source_ids(analysis)
    stage_refs = list(stage.get("source_refs", [])) or all_refs
    unit_code, unit_refs, unit_conflict = fact_value(
        analysis, {"铺位号", "铺位编号", "商铺编号"}
    )
    floor, floor_refs, floor_conflict = fact_value(
        analysis, {"所在楼层", "楼层", "铺位楼层"}
    )
    area_sqm, area_refs, area_conflict = fact_value(
        analysis, {"使用面积", "租赁面积", "面积"}
    )

    verification_items = list(analysis.get("missing_information", []))
    if unit_conflict:
        verification_items.append("资料中的铺位编号存在冲突，需人工核对")
    if floor_conflict:
        verification_items.append("资料中的铺位楼层存在冲突，需人工核对")
    if area_conflict:
        verification_items.append("资料中的使用面积存在冲突，需人工核对")
    for key, label in (("缺失", "缺失"), ("不可读取", "不可读取")):
        for source_ref in analysis.get("source_summary", {}).get(key, []):
            verification_items.append(f"资料{label}：{source_ref}")

    next_actions = [str(item).strip() for item in analysis.get("next_actions", []) if str(item).strip()]
    next_action = next_actions[0] if next_actions else "等待负责人确认下一动作"

    high_blockers = list(
        dict.fromkeys(
            str(row.get("statement", "")).strip()
            for row in analysis.get("risk_assessments", [])
            if row.get("level") == "高" and "阻断" in str(row.get("statement", ""))
        )
    )
    owner_judgments = analysis.get("owner_judgments", [])
    owner_statement = "；".join(
        str(row.get("statement", "")).strip()
        for row in owner_judgments
        if str(row.get("statement", "")).strip()
    )
    owner_names = list(
        dict.fromkeys(
            str(row.get("owner", "")).strip()
            for row in owner_judgments
            if str(row.get("owner", "")).strip()
        )
    )
    owner_refs = list(
        dict.fromkeys(
            ref
            for row in owner_judgments
            for ref in row.get("source_refs", [])
            if ref
        )
    )

    readable_count = len(analysis.get("source_summary", {}).get("可读取", []))
    fact_count = len(analysis.get("evidence_facts", []))
    verification_count = len(list(dict.fromkeys(verification_items)))
    evidence_summary = (
        f"已登记{len(analysis.get('source_registry', []))}份资料，"
        f"其中{readable_count}份可读取，形成{fact_count}条可证事实；"
        f"仍有{verification_count}项待核验。"
    )

    analysis_time = datetime.combine(
        date.fromisoformat(analysis["analysis_as_of"]),
        time.min,
        tzinfo=timezone.utc,
    ).isoformat().replace("+00:00", "Z")

    record: dict[str, Any] = {
        "schema_version": "site_record/v0.1",
        "site_id": envelope(
            candidate["candidate_id"],
            layer="正式业务状态",
            confirmation_status="已确认",
            confirmed_by="lann-site",
            source_refs=all_refs,
        ),
        "mall_name": envelope(
            candidate["candidate_name"],
            layer="原始资料事实",
            confirmation_status="无需确认",
            confirmed_by=None,
            source_refs=all_refs,
        ),
        "city": envelope(
            candidate["city"],
            layer="原始资料事实",
            confirmation_status="无需确认",
            confirmed_by=None,
            source_refs=all_refs,
        ),
        "responsible_owner": candidate_envelope(None, all_refs),
        "current_stage": candidate_envelope(workflow_stage, stage_refs),
        "ownership_model": candidate_envelope("待定", all_refs),
        "next_action": candidate_envelope(next_action, stage_refs),
        "current_blockers": candidate_envelope(high_blockers, stage_refs),
        "evidence_completeness": envelope(
            {
                "level": evidence_level(analysis),
                "source_count": len(analysis.get("source_registry", [])),
                "pdf_fact_count": fact_count,
                "summary": evidence_summary,
            },
            layer="AI经营判断",
            confirmation_status="无需确认",
            confirmed_by=None,
            source_refs=all_refs,
        ),
        "pending_verifications": envelope(
            list(dict.fromkeys(verification_items)),
            layer="AI经营判断",
            confirmation_status="无需确认",
            confirmed_by=None,
            source_refs=all_refs,
        ),
        "data_updated_at": envelope(
            analysis_time,
            layer="正式业务状态",
            confirmation_status="已确认",
            confirmed_by="lann-site",
            source_refs=all_refs,
        ),
    }

    if unit_code is not None or floor is not None:
        record["unit"] = envelope(
            {"floor": floor, "unit_code": unit_code},
            layer="原始资料事实",
            confirmation_status="无需确认",
            confirmed_by=None,
            source_refs=unit_refs + floor_refs,
        )
    if isinstance(area_sqm, (int, float)) and area_sqm > 0:
        record["area_sqm"] = envelope(
            area_sqm,
            layer="原始资料事实",
            confirmation_status="无需确认",
            confirmed_by=None,
            source_refs=area_refs,
        )

    for field_name, mapping, source_key in (
        ("engineering_precheck", ENGINEERING_PRECHECK_MAP, "engineering_precheck"),
        ("operating_feasibility_visit", OPERATING_VISIT_MAP, "operating_feasibility_visit"),
        ("engineer_site_survey", ENGINEER_SURVEY_MAP, "engineer_site_survey"),
    ):
        source_value = stage.get(source_key)
        if source_value in mapping:
            record[field_name] = candidate_envelope(mapping[source_value], stage_refs)

    matching = analysis.get("matching_summary", {})
    record["franchise_customer_decision"] = envelope(
        {
            "status": matching_status(matching),
            "recommended_count": int(matching.get("recommended_count", 0)),
            "site_declined_count": int(matching.get("site_declined_count", 0)),
            "considering_count": int(matching.get("considering_count", 0)),
            "overdue_pending_count": int(matching.get("overdue_pending_count", 0)),
            "summary": matching.get("separation_note"),
        },
        layer="AI经营判断",
        confirmation_status="无需确认",
        confirmed_by=None,
        source_refs=all_refs,
    )

    if owner_statement and owner_names:
        record["owner_current_judgment"] = envelope(
            owner_statement,
            layer="负责人确认",
            confirmation_status="已确认",
            confirmed_by=" / ".join(owner_names),
            source_refs=owner_refs or all_refs,
        )

    return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a review-only site_record/v0.1 candidate from Site shadow analysis."
    )
    parser.add_argument("--input", required=True, help="Site shadow analysis JSON.")
    parser.add_argument("--output", required=True, help="Candidate site_record/v0.1 JSON.")
    parser.add_argument(
        "--schema",
        default=str(
            Path(__file__).resolve().parents[1]
            / "ai"
            / "schemas"
            / "site_record.v0.1.schema.json"
        ),
        help="site_record/v0.1 schema path.",
    )
    args = parser.parse_args()

    analysis = json.loads(Path(args.input).read_text(encoding="utf-8"))
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    record = build_site_record(analysis)
    validate_site_record(record, schema)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"候选场地记录已生成: {output_path}")
    print(f"项目: {record['mall_name']['value']}")
    print("状态: 待负责人审阅，不写Dashboard、不自动创建字段")


if __name__ == "__main__":
    main()

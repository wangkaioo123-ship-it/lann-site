from __future__ import annotations

from collections import defaultdict

from services.franchise_operating_check import average, month_index, number, relative_change
from services.workforce_monthly import normalize_header


REVIEW_SCHEMA_VERSION = "franchise-operating-review/v0.1"
EVIDENCE_STRONG = "人员侧较强交叉证据"
EVIDENCE_AUXILIARY = "有辅助证据"
EVIDENCE_INSUFFICIENT = "无法支持或证据不足"


def _rows_by_store(rows, id_field, month_field, target_month):
    grouped = defaultdict(list)
    target_index = month_index(target_month)
    for row in rows:
        row_month = row.get(month_field)
        if row.get(id_field) and month_index(row_month) is not None and month_index(row_month) <= target_index:
            grouped[row[id_field]].append(row)
    for store_rows in grouped.values():
        store_rows.sort(key=lambda row: row.get(month_field) or "")
    return grouped


def _metric_change(rows, field):
    selected = rows[-5:]
    if len(selected) < 5:
        return None
    return relative_change(
        average(number(row.get(field)) for row in selected[-2:]),
        average(number(row.get(field)) for row in selected[:3]),
    )


def _sum(rows, field):
    return sum(number(row.get(field)) or 0 for row in rows)


def _optional_sum(rows, field):
    values = [number(row.get(field)) for row in rows]
    return sum(value for value in values if value is not None) if any(value is not None for value in values) else None


def _round(value, digits=4):
    return None if value is None else round(value, digits)


def _direction_pair(headcount_change, metric_change):
    if headcount_change is None or metric_change is None:
        return "数据不足"
    if headcount_change < -0.01 and metric_change < -0.01:
        return "同向下降"
    if headcount_change > 0.01 and metric_change > 0.01:
        return "同向上升"
    if abs(headcount_change) <= 0.01:
        return "人员数量基本稳定"
    return "方向不一致"


def _snapshot_reliable(row):
    return (
        row.get("confidence_level") in {"中", "高"}
        and normalize_header(row.get("coverage_status")) in {"complete", "full", "完整", "已覆盖"}
    )


def _event_coverage_complete(row):
    return normalize_header(row.get("event_coverage_status")) in {"complete", "full", "完整", "已覆盖"}


def _workdays_per_head_change(operating_rows, workforce_rows):
    headcount_by_month = {row["month"]: number(row.get("month_average_headcount")) for row in workforce_rows}
    values = []
    for row in operating_rows[-5:]:
        headcount = headcount_by_month.get(row.get("月份"))
        workdays = number(row.get("理疗师工作人天"))
        values.append(workdays / headcount if workdays is not None and headcount and headcount > 0 else None)
    if len(values) < 5:
        return {"baseline": None, "recent": None, "change": None}
    baseline = average(values[:3])
    recent = average(values[-2:])
    return {"baseline": _round(baseline, 2), "recent": _round(recent, 2), "change": _round(relative_change(recent, baseline))}


def build_store_review(store_id, store_name, candidate, operating_rows, workforce_rows):
    operating_rows = operating_rows[-5:]
    workforce_rows = workforce_rows[-5:]
    latest = workforce_rows[-1]
    previous = workforce_rows[-2] if len(workforce_rows) >= 2 else {}
    baseline_workforce = workforce_rows[:3]
    recent_workforce = workforce_rows[-2:]
    baseline_headcount = average(number(row.get("month_average_headcount")) for row in baseline_workforce)
    recent_headcount = average(number(row.get("month_average_headcount")) for row in recent_workforce)
    headcount_change = relative_change(recent_headcount, baseline_headcount)
    end_headcount_delta = None
    if number(latest.get("month_end_headcount")) is not None and number(previous.get("month_end_headcount")) is not None:
        end_headcount_delta = number(latest.get("month_end_headcount")) - number(previous.get("month_end_headcount"))

    exits_recent = _sum(recent_workforce, "exit_count")
    transfer_out_recent = _sum(recent_workforce, "transfer_out_count")
    max_outflow_month = max(
        (_sum([row], "exit_count") + _sum([row], "transfer_out_count") for row in recent_workforce),
        default=0,
    )
    target_month_outflow = _sum([latest], "exit_count") + _sum([latest], "transfer_out_count")
    concentrated_outflow = max_outflow_month >= 2 or exits_recent + transfer_out_recent >= 3
    support_in_recent = _sum(recent_workforce, "support_in_count")
    support_out_recent = _sum(recent_workforce, "support_out_count")
    support_in_person_days = _optional_sum(recent_workforce, "support_in_person_days")
    support_out_person_days = _optional_sum(recent_workforce, "support_out_person_days")
    personnel_signal = (
        (headcount_change is not None and headcount_change <= -0.08)
        or (end_headcount_delta is not None and end_headcount_delta <= -1)
        or concentrated_outflow
    )
    target_month_direct_signal = (
        target_month_outflow >= 2 and _event_coverage_complete(latest)
    ) or (
        end_headcount_delta is not None
        and end_headcount_delta <= -1
        and (previous.get("month") or "") >= "2026-07"
        and _snapshot_reliable(previous)
        and _snapshot_reliable(latest)
    )
    any_personnel_change = personnel_signal or any(
        value > 0
        for value in (
            _sum(recent_workforce, "hire_count"), exits_recent, _sum(recent_workforce, "transfer_in_count"),
            transfer_out_recent, support_in_recent, support_out_recent,
            support_in_person_days or 0, support_out_person_days or 0,
        )
    ) or bool(latest.get("manager_change_candidate"))

    operating_changes = candidate.get("changes", {})
    co_movement = {
        "营收": _direction_pair(headcount_change, operating_changes.get("实际营收")),
        "总客数": _direction_pair(headcount_change, operating_changes.get("总客数")),
        "理疗师工作人天": _direction_pair(headcount_change, operating_changes.get("理疗师工作人天")),
        "理疗师日均产值": _direction_pair(headcount_change, operating_changes.get("理疗师日均产值")),
    }
    negative_cross_metrics = [name for name, value in co_movement.items() if value == "同向下降"]
    if target_month_direct_signal and "营收" in negative_cross_metrics and len(negative_cross_metrics) >= 2:
        evidence_class = EVIDENCE_STRONG
        hypothesis = (
            "人员侧变化与经营指标出现同向信号，人员承载变化假设获得较强交叉证据；"
            "这仍是相关性，需要核查变化发生时间、原因及门店实际排班。"
        )
    elif any_personnel_change:
        evidence_class = EVIDENCE_AUXILIARY
        hypothesis = (
            "人员数量、流动或短期支援存在变化，但与经营变化的时间或方向不足以形成较强交叉证据；"
            "该信息只用于安排现场核查。"
        )
    else:
        evidence_class = EVIDENCE_INSUFFICIENT
        hypothesis = (
            "现有人员聚合未显示与经营下降同步的明显数量或流动变化，人员数量不足假设被削弱；"
            "仍需核查排班结构、技能结构和获客变化。"
        )

    gaps = ["离职、调动和支援发生的现场原因", "实际排班与技能结构变化", "门店已采取动作及效果"]
    if latest.get("event_coverage_status") in {
        "", "未单列", "不完整", "部分覆盖", "partial", "unavailable", "incomplete", "missing",
    }:
        gaps.append("加盟自管店入职事件覆盖是否完整")
    if normalize_header(latest.get("coverage_status")) not in {"complete", "full", "完整", "已覆盖"}:
        gaps.append("目标月人数快照覆盖是否足以支持人数变化判断")
    if latest.get("manager_change_candidate"):
        gaps.append("店长是否实际发生更换及生效日期")
    if support_in_recent or support_out_recent or support_in_person_days or support_out_person_days:
        gaps.append("短期支援的持续天数与是否形成常态依赖")
    auxiliary_history_note = (
        "2026-01至2026-06只作辅助；"
        if any((row.get("month") or "") < "2026-07" for row in workforce_rows)
        else ""
    )

    return {
        "store_id": store_id,
        "store_name": store_name,
        "candidate_id": candidate.get("candidate_id"),
        "evidence_class": evidence_class,
        "direct_facts": {
            "target_month": latest.get("month"),
            "month_start_headcount": latest.get("month_start_headcount"),
            "month_end_headcount": latest.get("month_end_headcount"),
            "month_average_headcount": latest.get("month_average_headcount"),
            "previous_month_end_headcount": previous.get("month_end_headcount"),
            "end_headcount_delta": _round(end_headcount_delta, 2),
            "recent_2m_average_headcount": _round(recent_headcount, 2),
            "previous_3m_average_headcount": _round(baseline_headcount, 2),
            "average_headcount_change": _round(headcount_change),
            "recent_2m_hires": _round(_sum(recent_workforce, "hire_count"), 2),
            "recent_2m_exits": _round(exits_recent, 2),
            "recent_2m_transfer_in": _round(_sum(recent_workforce, "transfer_in_count"), 2),
            "recent_2m_transfer_out": _round(transfer_out_recent, 2),
            "target_month_exit_and_transfer_out": _round(target_month_outflow, 2),
            "concentrated_exit_or_transfer_out": concentrated_outflow,
            "recent_2m_support_in": _round(support_in_recent, 2),
            "recent_2m_support_out": _round(support_out_recent, 2),
            "recent_2m_support_in_person_days": _round(support_in_person_days, 2),
            "recent_2m_support_out_person_days": _round(support_out_person_days, 2),
            "short_term_support_observed": bool(
                support_in_recent or support_out_recent or support_in_person_days or support_out_person_days
            ),
            "target_month_net_change": latest.get("net_change"),
            "manager_change_candidate": latest.get("manager_change_candidate"),
            "manager_change_candidate_count": latest.get("manager_change_candidate_count"),
            "manager_change_first_date": latest.get("manager_change_first_date"),
            "snapshot_coverage_days": latest.get("snapshot_coverage_days"),
            "expected_snapshot_days": latest.get("expected_snapshot_days"),
            "confidence_level": latest.get("confidence_level"),
            "coverage_status": latest.get("coverage_status"),
            "event_coverage_status": latest.get("event_coverage_status"),
            "store_coverage_status": latest.get("store_coverage_status"),
            "cutoff_date": latest.get("cutoff_date"),
        },
        "personnel_indicators": {
            "target_month_direct_signal": target_month_direct_signal,
            "five_month_personnel_signal": personnel_signal,
            "target_month_event_coverage_complete": _event_coverage_complete(latest),
            "pre_2026_07_history_role": (
                "仅作辅助证据" if any((row.get("month") or "") < "2026-07" for row in workforce_rows) else "不适用"
            ),
            "note": "人员指标是门店月度聚合的确定性整理，不等于个人事件明细或因果结论。",
        },
        "operating_facts": {
            "evidence": candidate.get("evidence"),
            "revenue_change": _round(operating_changes.get("实际营收")),
            "total_customer_change": _round(operating_changes.get("总客数")),
            "new_customer_change": _round(operating_changes.get("新客数")),
            "returning_customer_change": _round(operating_changes.get("老客数")),
            "therapist_workday_change": _round(operating_changes.get("理疗师工作人天")),
            "therapist_productivity_change": _round(operating_changes.get("理疗师日均产值")),
        },
        "proxy_metrics": {
            "workdays_per_average_therapist": _workdays_per_head_change(operating_rows, workforce_rows),
            "headcount_and_operating_metric_direction": co_movement,
            "note": "工作人天/人是聚合代理指标，不等于个人排班或有效服务时长。",
        },
        "hypothesis": hypothesis,
        "evidence_limit": (
            f"人员事实为门店月度聚合；{auxiliary_history_note}"
            f"目标月可信等级为{latest.get('confidence_level') or '未知'}；不能据此认定人员变化是经营结果的原因。"
        ),
        "remaining_field_facts": list(dict.fromkeys(gaps)),
        "questions_for_franchise_service": [
            "人员变化发生在月内什么时间，是否与客次变化时间重合？",
            "离职、调出和短期支援的实际原因是什么？",
            "当前排班、技能结构和点钟承接是否发生变化？",
            "门店已经采取哪些动作，加盟商是否知情，当前效果如何？",
        ],
    }


def build_review(monthly_rows, operating_result, workforce_dataset, workforce_gate, candidate_order):
    target_month = operating_result["global"].get("latest_month")
    operating_by_store = _rows_by_store(monthly_rows, "点位ID", "月份", target_month)
    workforce_by_store = _rows_by_store(workforce_dataset.get("rows", []), "store_id", "month", target_month)
    issues = []
    if not operating_result["global"].get("ready"):
        issues.append(operating_result["global"].get("message") or "经营数据 Gate 未通过")
    if not workforce_gate.get("ready"):
        issues.extend(workforce_gate.get("issues", []))

    candidates = []
    if not issues:
        for order, frozen in enumerate(candidate_order, start=1):
            store_id = frozen["store_id"]
            candidate = (operating_result.get("stores", {}).get(store_id) or {}).get("candidate")
            if not candidate:
                issues.append(f"固定候选 {store_id} 无法由当前经营输入复现")
                continue
            if frozen.get("candidate_id") and candidate.get("candidate_id") != frozen["candidate_id"]:
                issues.append(f"固定候选 {store_id} 的候选ID与当前经营输入不一致")
                continue
            operating_history = operating_by_store.get(store_id, [])[-5:]
            expected_months = [row.get("月份") for row in operating_history]
            workforce_lookup = {
                row.get("month"): row for row in workforce_by_store.get(store_id, [])
            }
            missing_months = [month for month in expected_months if month not in workforce_lookup]
            if len(expected_months) < 5 or missing_months:
                detail = f"，缺少 {', '.join(missing_months)}" if missing_months else ""
                issues.append(f"固定候选 {store_id} 人员历史未覆盖经营对比所需连续5个月{detail}")
                continue
            workforce_history = [workforce_lookup[month] for month in expected_months]
            required_history_fields = (
                "month_average_headcount", "month_end_headcount", "hire_count", "exit_count",
                "transfer_in_count", "transfer_out_count", "support_in_count", "support_out_count",
            )
            incomplete = [
                f"{row['month']}/{field}"
                for row in workforce_history
                for field in required_history_fields
                if row.get(field) is None
            ]
            if incomplete:
                issues.append(
                    f"固定候选 {store_id} 人员历史字段不完整：{', '.join(incomplete[:6])}"
                    + (" 等" if len(incomplete) > 6 else "")
                )
                continue
            review = build_store_review(
                store_id,
                frozen.get("store_name") or operating_by_store[store_id][-1].get("门店名称", ""),
                candidate,
                operating_history,
                workforce_history,
            )
            review["candidate_order"] = order
            candidates.append(review)

    if issues:
        candidates = []
    buckets = {EVIDENCE_STRONG: [], EVIDENCE_AUXILIARY: [], EVIDENCE_INSUFFICIENT: []}
    for candidate in candidates:
        buckets[candidate["evidence_class"]].append(candidate["store_id"])
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "status": "ready_for_business_review" if not issues else "blocked_by_data_gate",
        "target_month": target_month,
        "dashboard_write_allowed": False,
        "candidate_count": len(candidates),
        "candidate_order": [row["store_id"] for row in candidate_order],
        "data_gate": {"operating": operating_result["global"], "workforce": workforce_gate, "issues": list(dict.fromkeys(issues))},
        "summary": {
            "personnel_cross_evidence": buckets,
            "business_decline_without_personnel_support": buckets[EVIDENCE_INSUFFICIENT],
            "note": "该分组是证据归类，不是风险评分，也不改变候选名单与顺序。",
        },
        "candidates": candidates,
        "next_owner": "加盟服务业务 Review" if not issues else "数据出口/输入 Gate 修复",
    }


def render_markdown(review, manifest):
    lines = [
        f"# 加盟经营异常核查人员证据增强（{review.get('target_month') or '未知月份'}）",
        "",
        f"- 运行状态：{review['status']}",
        f"- 规则版本：{manifest['rule_version']}",
        f"- 运行 ID：{manifest['run_id']}",
        f"- 生成时间：{manifest['generated_at']}",
        f"- Dashboard 写入：禁止（只读候选，人工领取后才能形成正式事项）",
        "",
        "## 数据 Gate",
        "",
        f"- 经营：{review['data_gate']['operating'].get('message')}",
        f"- 人员：{review['data_gate']['workforce'].get('message')}",
    ]
    if review["data_gate"]["issues"]:
        lines.extend(["", "### 阻断原因", ""] + [f"- {issue}" for issue in review["data_gate"]["issues"]])
        return "\n".join(lines) + "\n"

    lines.extend(["", "## 汇总", ""])
    for label, store_ids in review["summary"]["personnel_cross_evidence"].items():
        lines.append(f"- {label}：{', '.join(store_ids) if store_ids else '无'}")
    lines.extend(["", "> 以上是证据归类，不是风险评分；人员相关性不等于因果。", ""])
    for candidate in review["candidates"]:
        facts = candidate["direct_facts"]
        proxy = candidate["proxy_metrics"]["workdays_per_average_therapist"]
        lines.extend(
            [
                f"## {candidate['candidate_order']}. {candidate['store_name']}（{candidate['store_id']}）",
                "",
                f"- 证据归类：{candidate['evidence_class']}（人员数据可信等级：{facts['confidence_level']}）",
                f"- 经营事实：{candidate['operating_facts']['evidence']}",
                f"- 人员事实：月初/月末/月均在岗 {facts['month_start_headcount']}/{facts['month_end_headcount']}/{facts['month_average_headcount']}；"
                f"较上月末变化 {facts['end_headcount_delta']}；近2月离职/调出 {facts['recent_2m_exits']}/{facts['recent_2m_transfer_out']}；"
                f"短期支援调入/调出 {facts['recent_2m_support_in']}/{facts['recent_2m_support_out']}。",
                f"- 代理指标：每名月均在岗理疗师对应工作人天，前3月 {proxy['baseline']}、近2月 {proxy['recent']}、变化 {proxy['change']}。",
                f"- 同向关系：" + "；".join(f"{key}{value}" for key, value in candidate["proxy_metrics"]["headcount_and_operating_metric_direction"].items()),
                f"- 核查假设：{candidate['hypothesis']}",
                f"- 证据边界：{candidate['evidence_limit']}",
                "- 仍缺现场事实：" + "；".join(candidate["remaining_field_facts"]),
                "- 建议加盟服务核查：" + "；".join(candidate["questions_for_franchise_service"]),
                "",
            ]
        )
    lines.extend(["## 下一责任人", "", "加盟服务业务 Review；不是继续开发，也不会自动写入 Dashboard 正式事项。", ""])
    return "\n".join(lines)

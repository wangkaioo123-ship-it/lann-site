from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from services.franchise_operating_check import (
    MIN_HISTORY_MONTHS,
    average,
    evaluate_window,
    is_scope_row,
    month_index,
    number,
    relative_change,
)


BUSINESS_REVIEW_SCHEMA_VERSION = "franchise-operating-business-review/v0.1"

DISPLAY_METRICS = (
    ("revenue", "实际营收", "完整月营收"),
    ("service_visits", "订单客次", "订单客次"),
    ("total_customers", "总客数", "总客数"),
    ("new_customers", "新客数", "新客数"),
    ("returning_customers", "老客数", "老客数"),
    ("discounted_average_ticket", "客单价_折扣后", "折扣后客单价"),
    ("therapist_workdays", "理疗师工作人天", "理疗师工作人天"),
    ("therapist_daily_output", "理疗师日均产值", "理疗师日均产值"),
    ("therapist_productivity", "理疗师生产率", "理疗师生产率"),
)


def _round(value, digits=4):
    return None if value is None else round(value, digits)


def _mean(rows, field):
    return average(number(row.get(field)) for row in rows)


def _metric_window(rows, field):
    selected = rows[-5:]
    baseline = _mean(selected[:3], field) if len(selected) == 5 else None
    recent = _mean(selected[-2:], field) if len(selected) == 5 else None
    return {
        "baseline_previous_3m": _round(baseline, 2),
        "recent_2m": _round(recent, 2),
        "change": _round(relative_change(recent, baseline)),
    }


def _threshold(actual, threshold, comparison):
    if actual is None:
        return {
            "actual": None,
            "threshold": threshold,
            "comparison": comparison,
            "met": False,
            "distance_to_threshold": None,
            "crossed_by": None,
        }
    if comparison == "lte":
        met = actual <= threshold
        distance = max(0.0, actual - threshold)
        crossed = max(0.0, threshold - actual)
    else:
        met = actual > threshold
        distance = max(0.0, threshold - actual)
        crossed = max(0.0, actual - threshold)
    return {
        "actual": _round(actual),
        "threshold": threshold,
        "comparison": comparison,
        "met": met,
        "distance_to_threshold": _round(distance),
        "crossed_by": _round(crossed),
    }


def _candidate_paths(evaluation):
    changes = evaluation.get("changes", {})
    revenue_8 = _threshold(changes.get("实际营收"), -0.08, "lte")
    revenue_3 = _threshold(changes.get("实际营收"), -0.03, "lte")
    total_customer = _threshold(changes.get("总客数"), -0.05, "lte")
    returning_customer = _threshold(changes.get("老客数"), -0.05, "lte")
    new_customer = _threshold(changes.get("新客数"), -0.15, "lte")
    workdays = _threshold(changes.get("理疗师工作人天"), -0.08, "lte")
    rent = _threshold(evaluation.get("rent_ratio"), 0.25, "gt")
    customer_or_capacity = any(
        item["met"] for item in (total_customer, returning_customer, new_customer, workdays)
    )
    combination_met = revenue_8["met"] and customer_or_capacity
    rent_path_met = rent["met"] and revenue_3["met"]
    if combination_met or rent_path_met:
        reason = "达到现行组合异常规则"
    else:
        missing = []
        if not revenue_8["met"]:
            missing.append("营收降幅未达到8%")
        if not customer_or_capacity:
            missing.append("客群或工作人天降幅未达到组合门槛")
        if not rent_path_met:
            if not rent["met"]:
                missing.append("近3月租售比未高于25%")
            elif not revenue_3["met"]:
                missing.append("高租售比路径下营收降幅未达到3%")
        reason = "；".join(dict.fromkeys(missing)) or "现有数据不足以判断门槛"
    return {
        "triggered": combination_met or rent_path_met,
        "reason": reason,
        "operating_combination_decline": {
            "met": combination_met,
            "revenue": revenue_8,
            "total_customers": total_customer,
            "returning_customers": returning_customer,
            "new_customers": new_customer,
            "therapist_workdays": workdays,
        },
        "rent_pressure_with_revenue_decline": {
            "met": rent_path_met,
            "rent_ratio": rent,
            "revenue": revenue_3,
        },
    }


def _optional_sum(rows, field):
    values = [number(row.get(field)) for row in rows]
    present = [value for value in values if value is not None]
    return _round(sum(present), 2) if present else None


def _personnel_history(operating_rows, workforce_rows, target_month):
    by_month = {row.get("month"): row for row in workforce_rows}
    expected_months = [row.get("月份") for row in operating_rows[-5:]]
    aligned = [by_month.get(month) for month in expected_months]
    latest = by_month.get(target_month)
    if not latest:
        return {
            "available": False,
            "target_month": target_month,
            "evidence_role": "证据缺口",
            "missing_months": expected_months,
            "note": "人员聚合未覆盖该门店目标月，不能用工作人天代替人员事实。",
        }

    present = [row for row in aligned if row]
    headcounts = [number(row.get("month_average_headcount")) if row else None for row in aligned]
    baseline_headcount = average(headcounts[:3]) if len(headcounts) == 5 else None
    recent_headcount = average(headcounts[-2:]) if len(headcounts) == 5 else None
    latest_workdays = number(operating_rows[-1].get("理疗师工作人天"))
    latest_headcount = number(latest.get("month_average_headcount"))
    confidence = latest.get("confidence_level") or "未知"
    coverage = latest.get("coverage_status") or "未知"
    strong_eligible = target_month >= "2026-07" and confidence in {"中", "高"}
    evidence_role = "可作交叉证据" if strong_eligible else "仅作辅助证据"
    missing_months = [month for month, row in zip(expected_months, aligned) if row is None]
    return {
        "available": True,
        "target_month": target_month,
        "evidence_role": evidence_role,
        "confidence_level": confidence,
        "coverage_status": coverage,
        "event_coverage_status": latest.get("event_coverage_status"),
        "cutoff_date": latest.get("cutoff_date"),
        "month_start_headcount": latest.get("month_start_headcount"),
        "month_end_headcount": latest.get("month_end_headcount"),
        "month_average_headcount": latest.get("month_average_headcount"),
        "average_headcount_previous_3m": _round(baseline_headcount, 2),
        "average_headcount_recent_2m": _round(recent_headcount, 2),
        "average_headcount_change": _round(relative_change(recent_headcount, baseline_headcount)),
        "recent_2m_hires": _optional_sum(present[-2:], "hire_count"),
        "recent_2m_exits": _optional_sum(present[-2:], "exit_count"),
        "recent_2m_transfer_in": _optional_sum(present[-2:], "transfer_in_count"),
        "recent_2m_transfer_out": _optional_sum(present[-2:], "transfer_out_count"),
        "recent_2m_support_in": _optional_sum(present[-2:], "support_in_count"),
        "recent_2m_support_out": _optional_sum(present[-2:], "support_out_count"),
        "manager_change_candidate": latest.get("manager_change_candidate"),
        "workdays_per_average_therapist": (
            _round(latest_workdays / latest_headcount, 2)
            if latest_workdays is not None and latest_headcount and latest_headcount > 0
            else None
        ),
        "missing_months": missing_months,
        "note": (
            "人员事实只用于交叉解释，不单独生成候选，也不能据此认定经营变化原因。"
            if strong_eligible
            else "该月人员可信度只支持辅助观察，不得输出较强人员结论。"
        ),
    }


def _possible_explanations(changes, personnel):
    explanations = []
    revenue = changes.get("revenue", {}).get("change")
    visits = changes.get("service_visits", {}).get("change")
    customers = changes.get("total_customers", {}).get("change")
    ticket = changes.get("discounted_average_ticket", {}).get("change")
    workdays = changes.get("therapist_workdays", {}).get("change")
    productivity = changes.get("therapist_daily_output", {}).get("change")
    if revenue is not None and revenue < 0 and any(value is not None and value < 0 for value in (visits, customers)):
        explanations.append("客次或客户规模变化可作为核查方向，但不能仅凭统计同向认定原因。")
    if revenue is not None and revenue < 0 and ticket is not None and ticket < 0:
        explanations.append("折扣后客单价变化可作为核查方向，仍需结合折扣、项目结构和会员消费核实。")
    if revenue is not None and revenue < 0 and workdays is not None and workdays < 0 and productivity is not None and productivity >= -0.05:
        explanations.append("服务承载变化可作为核查方向，工作人天是代理指标，不等于实际在岗人数。")
    if personnel.get("available") and personnel.get("average_headcount_change") is not None:
        if personnel["average_headcount_change"] < 0 and revenue is not None and revenue < 0:
            explanations.append("人员月均数量与营收出现同向变化，只能作为交叉证据，需核查发生时间与排班。")
    return explanations or ["现有统计差异不足以提出可靠解释，需结合门店现场事实核查。"]


def _store_observation(store_id, rows, operating_store_result, workforce_rows, target_month):
    rows = sorted(rows, key=lambda row: row.get("月份") or "")
    if not rows or rows[-1].get("月份") != target_month or len(rows) < MIN_HISTORY_MONTHS:
        return None
    evaluation = evaluate_window(rows, len(rows) - 1)
    if evaluation is None:
        return None
    selected = rows[-5:]
    latest = selected[-1]
    changes = {
        key: {"label": label, **_metric_window(selected, field)}
        for key, field, label in DISPLAY_METRICS
    }
    latest_facts = {
        key: _round(number(latest.get(field)), 2)
        for key, field, _ in DISPLAY_METRICS
    }
    latest_facts.update(
        {
            "month": target_month,
            "rent_ratio": _round(number(latest.get("租售比"))),
            "data_source": latest.get("营收数据来源"),
            "data_completeness": latest.get("营收数据完整性"),
        }
    )
    personnel = _personnel_history(selected, workforce_rows, target_month)
    candidate = (operating_store_result or {}).get("candidate")
    paths = _candidate_paths(evaluation)
    evidence_gaps = ["门店现场经营变化、已采取动作及效果"]
    if latest_facts["service_visits"] is None:
        evidence_gaps.append("订单客次缺失；总客数不能自动替代客次")
    if latest_facts["discounted_average_ticket"] is None:
        evidence_gaps.append("折扣后客单价缺失")
    if not personnel.get("available"):
        evidence_gaps.append("目标月人员聚合事实缺失")
    elif personnel.get("missing_months"):
        evidence_gaps.append("人员历史未完整覆盖经营对比窗口")
    return {
        "store_id": store_id,
        "store_name": latest.get("门店名称") or latest.get("Hanson门店名称") or "",
        "operating_status": (operating_store_result or {}).get("status"),
        "candidate_triggered": bool(candidate),
        "candidate_id": candidate.get("candidate_id") if candidate else None,
        "trigger_codes": candidate.get("trigger_codes", []) if candidate else [],
        "candidate_rule_check": paths,
        "latest_month_facts": latest_facts,
        "statistical_differences": changes,
        "personnel_history": personnel,
        "possible_explanations": _possible_explanations(changes, personnel),
        "evidence_gaps": evidence_gaps,
        "peer_evidence": {
            "used_for_candidate": False,
            "note": "本版不以同类门店比较触发候选；如后续展示同类门店，只能作为辅助证据。",
        },
    }


def build_business_review(
    monthly_rows,
    operating_result,
    workforce_dataset,
    workforce_gate,
    candidate_freeze_manifest=None,
):
    target_month = operating_result.get("global", {}).get("latest_month")
    target_index = month_index(target_month)
    operating_by_store = defaultdict(list)
    for row in monthly_rows:
        row_index = month_index(row.get("月份"))
        if (
            row.get("点位ID")
            and row.get("月度Gate纳入") == "是"
            and is_scope_row(row)
            and row_index is not None
            and target_index is not None
            and row_index <= target_index
        ):
            operating_by_store[row["点位ID"]].append(row)
    workforce_by_store = defaultdict(list)
    for row in workforce_dataset.get("rows", []):
        if row.get("store_id"):
            workforce_by_store[row["store_id"]].append(row)

    stores = []
    excluded = []
    for store_id in sorted(operating_by_store):
        observation = _store_observation(
            store_id,
            operating_by_store[store_id],
            operating_result.get("stores", {}).get(store_id),
            workforce_by_store.get(store_id, []),
            target_month,
        )
        if observation:
            stores.append(observation)
        else:
            excluded.append(
                {
                    "store_id": store_id,
                    "store_name": operating_by_store[store_id][-1].get("门店名称", ""),
                    "reason": (operating_result.get("stores", {}).get(store_id) or {}).get("status")
                    or "未形成连续5个月可比较窗口",
                }
            )

    stores.sort(
        key=lambda item: (
            item["statistical_differences"]["revenue"]["change"] is None,
            item["statistical_differences"]["revenue"]["change"] or 0,
            item["store_id"],
        )
    )
    for rank, store in enumerate(stores, start=1):
        store["revenue_change_rank"] = rank

    workforce_confidence = sorted(
        {
            store["personnel_history"].get("confidence_level", "未知")
            for store in stores
            if store["personnel_history"].get("available")
        }
    )
    candidate_count = sum(store["candidate_triggered"] for store in stores)
    run_mode = "fixed_candidate_replay" if candidate_freeze_manifest else "full_scope_scan"
    comparison_note = (
        "本次使用固定候选文件，只用于复现已确认的2026-07九家校准样本及顺序，不代表重新按全量规则筛选。"
        if candidate_freeze_manifest
        else (
            "本次为无候选冻结的全量规则扫描。此前2026-07固定九家属于历史校准回放；"
            "当前候选数为0仅表示本次输入按现行V0.1门槛未触发，不能解释为门店没有经营问题。"
        )
    )
    ready = bool(operating_result.get("global", {}).get("ready") and workforce_gate.get("ready"))
    return {
        "schema_version": BUSINESS_REVIEW_SCHEMA_VERSION,
        "status": "ready_for_business_review" if ready else "blocked_by_data_gate",
        "target_month": target_month,
        "dashboard_write_allowed": False,
        "run_mode": run_mode,
        "data_cutoff": {
            "operating_complete_month": target_month,
            "workforce_dates": workforce_gate.get("data_cutoff_dates", []),
        },
        "data_gate": {
            "operating": operating_result.get("global", {}),
            "workforce": workforce_gate,
            "workforce_confidence_in_participating_stores": workforce_confidence,
        },
        "coverage": {
            "scope_store_count": workforce_gate.get("scope_store_count"),
            "workforce_covered_scope_store_count": workforce_gate.get("covered_scope_store_count"),
            "participating_store_count": len(stores),
            "excluded_store_count": len(excluded),
        },
        "ranking": {
            "basis": "最近2个完整月平均营收相对此前3个月平均营收的变化率，由下降大到增长排序",
            "note": "这是单项统计差异排序，不是综合风险评分。",
        },
        "candidate_count": candidate_count,
        "fixed_nine_comparison": {
            "historical_reference_month": "2026-07",
            "historical_reference_count": 9,
            "historical_reference_rule_version": "franchise-operating-check/v0.1",
            "current_month": target_month,
            "current_rule_version": operating_result.get("global", {}).get("rule_version"),
            "same_month_as_reference": target_month == "2026-07",
            "same_rule_version_as_reference": (
                operating_result.get("global", {}).get("rule_version") == "franchise-operating-check/v0.1"
            ),
            "current_candidate_freeze_applied": bool(candidate_freeze_manifest),
            "input_version_check": "经营与人员输入版本需以本次manifest中的SHA-256核对，不能从候选数反推输入相同。",
            "current_mode": run_mode,
            "note": comparison_note,
        },
        "evidence_legend": {
            "facts": "目标完整月经营月表与脱敏人员月表中的直接值。",
            "statistical_differences": "最近2月均值相对此前3月均值的统计变化，不是因果。",
            "proxy_metrics": "工作人天、人均工作人天等仅为代理指标。",
            "possible_explanations": "只用于安排核查的问题假设。",
            "evidence_gaps": "现有聚合数据无法回答、需业务现场补充的事实。",
        },
        "stores": stores,
        "excluded_stores": excluded,
    }


def _pct(value):
    return "—" if value is None else f"{value * 100:.1f}%"


def _num(value, digits=0):
    if value is None:
        return "—"
    return f"{value:,.{digits}f}"


def render_business_markdown(review, manifest):
    operating = review["data_gate"]["operating"]
    workforce = review["data_gate"]["workforce"]
    lines = [
        f"# 加盟门店业绩差异月度评审（{review.get('target_month') or '未知月份'}）",
        "",
        f"- 状态：{review['status']}",
        f"- 运行 ID：{manifest['run_id']}",
        f"- 生成时间：{manifest['generated_at']}",
        f"- 经营 Gate：{operating.get('message')}",
        f"- 人员 Gate：{workforce.get('message')}",
        f"- 参与排序门店：{review['coverage']['participating_store_count']} 家",
        f"- 规则候选：{review['candidate_count']} 家",
        "- Dashboard 写入：禁止",
        "",
        "> " + review["fixed_nine_comparison"]["note"],
        "",
        "## 全部门店差异排序",
        "",
        "| 排名 | 门店 | 候选 | 完整月营收 | 营收变化 | 订单客次 | 新客/老客 | 折后客单 | 工作人天 | 日均产值 | 月均人数 | 未触发/触发说明 |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for store in review["stores"]:
        facts = store["latest_month_facts"]
        changes = store["statistical_differences"]
        personnel = store["personnel_history"]
        lines.append(
            "| {rank} | {name}（{store_id}） | {candidate} | {revenue} | {revenue_change} | {visits} | "
            "{new}/{old} | {ticket} | {workdays} | {output} | {headcount} | {reason} |".format(
                rank=store["revenue_change_rank"],
                name=store["store_name"],
                store_id=store["store_id"],
                candidate="是" if store["candidate_triggered"] else "否",
                revenue=_num(facts["revenue"]),
                revenue_change=_pct(changes["revenue"]["change"]),
                visits=_num(facts["service_visits"]),
                new=_num(facts["new_customers"]),
                old=_num(facts["returning_customers"]),
                ticket=_num(facts["discounted_average_ticket"], 1),
                workdays=_num(facts["therapist_workdays"], 1),
                output=_num(facts["therapist_daily_output"], 1),
                headcount=_num(personnel.get("month_average_headcount"), 1),
                reason=store["candidate_rule_check"]["reason"],
            )
        )
    lines.extend(
        [
            "",
            "## 证据边界",
            "",
            "- 事实：完整月经营值与脱敏人员聚合值。",
            "- 统计差异：最近2月均值相对此前3月均值，不代表因果。",
            "- 代理指标：工作人天及人均工作人天不等于实际排班明细。",
            "- 可能解释：仅作为加盟服务核查方向。",
            "- 同类门店：本版不参与候选触发；后续若展示，只作辅助证据。",
            "",
        ]
    )
    return "\n".join(lines)


def _browser_html(runs):
    payload = json.dumps(runs, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>LANN 加盟门店月度评审</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;margin:0;background:#f5f4ef;color:#1f2a24}}
main{{max-width:1500px;margin:auto;padding:28px}} h1{{margin:0 0 8px}} .muted{{color:#657068}} .tabs{{display:flex;gap:8px;margin:20px 0;flex-wrap:wrap}}
button{{border:1px solid #aab5ad;background:white;border-radius:999px;padding:8px 16px;cursor:pointer}} button.active{{background:#173f31;color:white;border-color:#173f31}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:14px 0}} .card{{background:white;border:1px solid #dde2de;border-radius:10px;padding:14px}}
.notice{{background:#fff7dd;border-left:4px solid #d3981c;padding:12px;margin:14px 0}} .table-wrap{{overflow:auto;background:white;border:1px solid #dde2de;border-radius:10px}}
table{{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}} th,td{{padding:9px 10px;border-bottom:1px solid #ecefec;text-align:right}} th:first-child,td:first-child,th:nth-child(2),td:nth-child(2),th:last-child,td:last-child{{text-align:left}}
.yes{{color:#a13b2b;font-weight:700}} .no{{color:#3e6c55}} details{{white-space:normal;min-width:280px}} code{{background:#eef0ed;padding:2px 5px;border-radius:4px}}
</style></head><body><main><h1>加盟门店业绩差异 / 波动月度评审</h1><div class=\"muted\">只读业务评审，不写 Dashboard；排序是统计差异，不是风险评分。</div><div id=\"tabs\" class=\"tabs\"></div><div id=\"app\"></div></main>
<script id=\"payload\" type=\"application/json\">{payload}</script><script>
const runs=JSON.parse(document.getElementById('payload').textContent); const tabs=document.getElementById('tabs'); const app=document.getElementById('app');
const fmt=(v,d=0)=>v===null||v===undefined?'—':Number(v).toLocaleString('zh-CN',{{maximumFractionDigits:d,minimumFractionDigits:d}}); const pct=v=>v===null||v===undefined?'—':(v*100).toFixed(1)+'%';
function el(tag,text,cls){{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node}}
function render(index){{[...tabs.children].forEach((b,i)=>b.classList.toggle('active',i===index));const r=runs[index].review;app.replaceChildren();
 const cards=el('div',undefined,'cards');[['经营完整月',r.data_cutoff.operating_complete_month],['人员截止',(r.data_cutoff.workforce_dates||[]).join('、')||'待确认'],['参与门店',r.coverage.participating_store_count+' 家'],['人员覆盖',(r.coverage.workforce_covered_scope_store_count??'—')+' / '+(r.coverage.scope_store_count??'—')],['规则候选',r.candidate_count+' 家'],['经营 Gate',r.data_gate.operating.ready?'通过':'未通过'],['人员 Gate',r.data_gate.workforce.ready?'通过':'未通过'],['人员可信度',(r.data_gate.workforce_confidence_in_participating_stores||[]).join('、')||'待确认']].forEach(x=>{{const c=el('div',undefined,'card');c.append(el('div',x[0],'muted'),el('strong',String(x[1])));cards.append(c)}});app.append(cards);
 app.append(el('div',r.fixed_nine_comparison.note,'notice')); const wrap=el('div',undefined,'table-wrap');const table=el('table');const head=el('tr');['排名','门店','候选','营收','营收变化','订单客次','新客/老客','折后客单','工作人天','日均产值','月均人数','规则距离与证据'].forEach(x=>head.append(el('th',x)));table.append(head);
 r.stores.forEach(s=>{{const f=s.latest_month_facts,d=s.statistical_differences,p=s.personnel_history,tr=el('tr');[s.revenue_change_rank,s.store_name+'（'+s.store_id+'）'].forEach(x=>tr.append(el('td',x)));tr.append(el('td',s.candidate_triggered?'是':'否',s.candidate_triggered?'yes':'no'));[fmt(f.revenue),pct(d.revenue.change),fmt(f.service_visits),fmt(f.new_customers)+' / '+fmt(f.returning_customers),fmt(f.discounted_average_ticket,1),fmt(f.therapist_workdays,1),fmt(f.therapist_daily_output,1),fmt(p.month_average_headcount,1)].forEach(x=>tr.append(el('td',x)));const td=el('td');const details=el('details');const combo=s.candidate_rule_check.operating_combination_decline,rent=s.candidate_rule_check.rent_pressure_with_revenue_decline;details.append(el('summary',s.candidate_rule_check.reason),el('div','统计差异：订单客次 '+pct(d.service_visits.change)+'；总客数 '+pct(d.total_customers.change)+'；新客 '+pct(d.new_customers.change)+'；老客 '+pct(d.returning_customers.change)+'；折后客单 '+pct(d.discounted_average_ticket.change)+'；工作人天 '+pct(d.therapist_workdays.change)+'；日均产值 '+pct(d.therapist_daily_output.change)+'；生产率 '+pct(d.therapist_productivity.change)),el('div','规则距离：组合路径营收 '+pct(combo.revenue.actual)+' / 门槛 -8.0%；租金路径租售比 '+pct(rent.rent_ratio.actual)+' / 门槛 >25.0%，营收 '+pct(rent.revenue.actual)+' / 门槛 -3.0%'),el('div','人员事实：月初/月末/月均 '+fmt(p.month_start_headcount,1)+' / '+fmt(p.month_end_headcount,1)+' / '+fmt(p.month_average_headcount,1)+'；近2月离职/调出 '+fmt(p.recent_2m_exits,1)+' / '+fmt(p.recent_2m_transfer_out,1)+'；证据角色 '+(p.evidence_role||'待确认')),el('div','可能解释：'+s.possible_explanations.join('；')),el('div','证据缺口：'+s.evidence_gaps.join('；')),el('div','人员边界：'+(p.note||'无')));td.append(details);tr.append(td);table.append(tr)}});wrap.append(table);app.append(wrap);
 const gate=el('p','经营：'+r.data_gate.operating.message+'；人员：'+r.data_gate.workforce.message,'muted');app.append(gate);
}}
runs.forEach((run,i)=>{{const b=el('button',run.month);b.onclick=()=>render(i);tabs.append(b)}}); if(runs.length)render(runs.length-1);else app.append(el('p','尚无当前展示版本的成功月度评审。'));
</script></body></html>"""


def write_business_review_browser(output_root):
    output_root = Path(output_root)
    by_month = {}
    for manifest_path in output_root.glob("????-??/*/manifest.json") if output_root.is_dir() else []:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            business_name = (manifest.get("outputs") or {}).get("business_review_json")
            business_path = manifest_path.parent / business_name if business_name else None
            if (
                manifest.get("status") != "ready_for_business_review"
                or manifest.get("dashboard_write_allowed") is not False
                or manifest.get("business_review_schema_version") != BUSINESS_REVIEW_SCHEMA_VERSION
                or not business_path
                or not business_path.is_file()
            ):
                continue
            review = json.loads(business_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        month = manifest.get("run_month")
        current = by_month.get(month)
        if current is None or str(manifest.get("generated_at") or "") > str(current["generated_at"] or ""):
            by_month[month] = {
                "month": month,
                "generated_at": manifest.get("generated_at"),
                "run_id": manifest.get("run_id"),
                "review": review,
            }
    runs = [by_month[month] for month in sorted(by_month)]
    output_root.mkdir(parents=True, exist_ok=True)
    index_payload = {
        "schema_version": "franchise-operating-business-review-index/v0.1",
        "dashboard_write_allowed": False,
        "months": [run["month"] for run in runs],
        "runs": runs,
    }
    (output_root / "business_review_index.json").write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_root / "business_review.html").write_text(_browser_html(runs), encoding="utf-8")
    return index_payload

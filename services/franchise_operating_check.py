from __future__ import annotations

from collections import defaultdict
from datetime import date


RULE_VERSION = "franchise-operating-check/v0.1"
SCOPE_ATTRIBUTES = ("加盟", "合资")
OPERATING_STATUSES = {"运营中", "正常营业"}
CORE_FIELDS = (
    "实际营收",
    "新客数",
    "老客数",
    "总客数",
    "理疗师工作人天",
    "理疗师日均产值",
)
MIN_HISTORY_MONTHS = 6
MIN_COVERAGE = 0.8
MIN_FIELD_COMPLETENESS = 0.8


def number(value):
    try:
        return float(value) if value not in ("", None) else None
    except (TypeError, ValueError):
        return None


def average(values):
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def relative_change(recent, baseline):
    if recent is None or baseline is None or baseline <= 0:
        return None
    return recent / baseline - 1


def month_index(value):
    try:
        year, month = (int(part) for part in str(value).split("-")[:2])
    except (TypeError, ValueError):
        return None
    if month < 1 or month > 12:
        return None
    return year * 12 + month


def is_scope_row(row):
    attribute = str(row.get("门店属性") or "")
    status = str(row.get("门店状态") or "")
    return any(value in attribute for value in SCOPE_ATTRIBUTES) and status in OPERATING_STATUSES


def has_core_fields(row):
    return bool(row.get("点位ID")) and all(number(row.get(field)) is not None for field in CORE_FIELDS)


def consecutive_months(rows):
    indexes = [month_index(row.get("月份")) for row in rows]
    return all(indexes[index] is not None and indexes[index] - indexes[index - 1] == 1 for index in range(1, len(indexes)))


def metric_change(recent_rows, baseline_rows, field):
    recent = average(number(row.get(field)) for row in recent_rows)
    baseline = average(number(row.get(field)) for row in baseline_rows)
    return relative_change(recent, baseline)


def format_money(value):
    return "待确认" if value is None else f"{value / 10000:.1f} 万"


def format_change(value):
    if value is None:
        return "待确认"
    direction = "上升" if value >= 0 else "下降"
    return f"{direction} {abs(value) * 100:.1f}%"


def format_ratio(value):
    return "待确认" if value is None else f"{value * 100:.1f}%"


def evaluate_window(rows, end_index):
    if end_index < MIN_HISTORY_MONTHS - 1:
        return None
    selected = rows[end_index - 4 : end_index + 1]
    if len(selected) != 5 or not consecutive_months(selected) or not all(has_core_fields(row) for row in selected):
        return None

    recent_rows = selected[-2:]
    baseline_rows = selected[:3]
    changes = {
        field: metric_change(recent_rows, baseline_rows, field)
        for field in CORE_FIELDS + ("留存率", "返店频次")
    }
    rent_ratio = average(number(row.get("租售比")) for row in rows[max(0, end_index - 2) : end_index + 1])
    revenue_drop = changes["实际营收"] is not None and changes["实际营收"] <= -0.08
    customer_drop_fields = [
        field
        for field, threshold in (("总客数", -0.05), ("老客数", -0.05), ("新客数", -0.15))
        if changes[field] is not None and changes[field] <= threshold
    ]
    capacity_drop = changes["理疗师工作人天"] is not None and changes["理疗师工作人天"] <= -0.08
    productivity_stable = changes["理疗师日均产值"] is not None and changes["理疗师日均产值"] >= -0.05
    rent_pressure = rent_ratio is not None and rent_ratio > 0.25
    trigger_codes = []
    if revenue_drop and (customer_drop_fields or capacity_drop):
        trigger_codes.append("operating-combination-decline")
    if rent_pressure and changes["实际营收"] is not None and changes["实际营收"] <= -0.03:
        trigger_codes.append("rent-pressure-with-revenue-decline")
    if not trigger_codes:
        return {"is_candidate": False, "changes": changes, "rent_ratio": rent_ratio}

    recent_revenue = average(number(row.get("实际营收")) for row in recent_rows)
    baseline_revenue = average(number(row.get("实际营收")) for row in baseline_rows)
    evidence = [f"最近2个完整月平均营收 {format_money(recent_revenue)}，较此前3个月{format_change(changes['实际营收'])}"]
    explanations = []
    gaps = ["区域经理掌握的现场经营变化", "门店已经采取的处理动作", "加盟商是否已经知情"]
    questions = ["近期经营环境、店长和团队是否发生明显变化？", "区域经理已经采取了哪些动作，当前效果如何？"]

    if customer_drop_fields:
        details = "、".join(f"{field}{format_change(changes[field])}" for field in customer_drop_fields)
        evidence.append(f"客户指标同步走弱：{details}")
        explanations.append("客流或客户结构变化可能是核查方向之一")
        gaps.extend(["近期获客活动变化", "老客到店变化及主要原因"])
        questions.append("新老客变化主要来自获客减少、老客流失，还是季节性波动？")

    if capacity_drop:
        evidence.append(f"理疗师工作人天{format_change(changes['理疗师工作人天'])}")
        if productivity_stable:
            evidence.append(f"理疗师日均产值未同步明显下降（{format_change(changes['理疗师日均产值'])}）")
            explanations.append("人员承载变化可能是核查方向之一")
        gaps.extend(["实际在岗人数与离职情况", "排班与店长变化"])
        questions.append("近期实际人数、离职、排班和店长是否发生变化？")

    if rent_pressure:
        evidence.append(f"最近3个完整月平均租售比 {format_ratio(rent_ratio)}")
        explanations.append("固定租赁成本可能放大经营压力")
        gaps.extend(["门店完整成本结构", "当前利润或亏损事实"])
        questions.append("除租金外，当前还有哪些主要成本压力，是否已形成明确改善方案？")

    return {
        "is_candidate": True,
        "trigger_codes": trigger_codes,
        "changes": changes,
        "rent_ratio": rent_ratio,
        "why_now": "；".join(evidence[:2]),
        "evidence": "；".join(evidence),
        "hypotheses": "；".join(dict.fromkeys(explanations)) or "现有数据不足以提出可靠解释",
        "gaps": "；".join(dict.fromkeys(gaps)),
        "questions": "；".join(dict.fromkeys(questions)),
        "recent_revenue": recent_revenue,
        "baseline_revenue": baseline_revenue,
    }


def build_operating_check_candidates(monthly_rows, today=None, target_month=None):
    today = today or date.today()
    scope_rows = [row for row in monthly_rows if is_scope_row(row)]
    if target_month:
        target_index = month_index(target_month)
        scope_rows = [row for row in scope_rows if month_index(row.get("月份")) is not None and month_index(row.get("月份")) <= target_index]
    observed_months = sorted({row.get("月份") for row in scope_rows if month_index(row.get("月份")) is not None})
    eligible_rows = [row for row in scope_rows if row.get("月度Gate纳入") == "是"]
    eligible_months = sorted({row.get("月份") for row in eligible_rows if month_index(row.get("月份")) is not None})
    latest_month = target_month or (eligible_months[-1] if eligible_months else "")
    global_result = {
        "ready": False,
        "latest_month": latest_month,
        "coverage": 0,
        "field_completeness": 0,
        "message": "没有可用于经营核查的完整自然月数据",
        "rule_version": RULE_VERSION,
    }
    if not observed_months or not eligible_months or latest_month not in eligible_months:
        if target_month and target_month not in eligible_months:
            global_result["message"] = f"目标月份 {target_month} 没有通过经营完整月 Gate"
        return {"global": global_result, "stores": {}}

    latest_index = month_index(latest_month)
    observed_index = month_index(observed_months[-1])
    expected_latest_index = today.year * 12 + today.month - 1
    recent_floor = latest_index - 5
    scope_store_ids = {
        row.get("点位ID")
        for row in scope_rows
        if row.get("点位ID") and month_index(row.get("月份")) is not None and recent_floor <= month_index(row.get("月份")) <= latest_index
    }
    latest_rows = [row for row in eligible_rows if row.get("月份") == latest_month]
    latest_scope_rows = [row for row in scope_rows if row.get("月份") == latest_month]
    latest_store_ids = {row.get("点位ID") for row in latest_rows if row.get("点位ID")}
    complete_latest_rows = [row for row in latest_rows if has_core_fields(row)]
    coverage = len(latest_store_ids) / len(scope_store_ids) if scope_store_ids else 0
    field_completeness = len(complete_latest_rows) / len(latest_rows) if latest_rows else 0
    unmapped = [row for row in latest_scope_rows if not row.get("点位ID")]
    issues = []
    if target_month:
        if latest_index is None or latest_index > expected_latest_index:
            issues.append(f"目标月份尚未闭月（当前 {target_month}）")
    elif latest_index != expected_latest_index:
        issues.append(f"完整月数据截止异常（当前 {latest_month}）")
    if not target_month and (observed_index is None or latest_index is None or observed_index - latest_index > 1):
        issues.append("完整月数据截止时间异常")
    if coverage < MIN_COVERAGE:
        issues.append(f"门店覆盖率不足（{coverage * 100:.1f}%）")
    if field_completeness < MIN_FIELD_COMPLETENESS:
        issues.append(f"核心字段完整度不足（{field_completeness * 100:.1f}%）")
    if unmapped:
        issues.append(f"存在 {len(unmapped)} 条未映射门店数据")

    global_result = {
        "ready": not issues,
        "latest_month": latest_month,
        "coverage": coverage,
        "field_completeness": field_completeness,
        "message": "；".join(issues) if issues else (
            f"数据截止 {latest_month}；门店覆盖率 {coverage * 100:.1f}%；核心字段完整度 {field_completeness * 100:.1f}%"
        ),
        "rule_version": RULE_VERSION,
    }

    grouped = defaultdict(list)
    for row in eligible_rows:
        if row.get("点位ID"):
            grouped[row["点位ID"]].append(row)

    store_results = {}
    for site_id in sorted(grouped):
        rows = grouped[site_id]
        rows.sort(key=lambda row: row.get("月份") or "")
        if not global_result["ready"]:
            store_results[site_id] = {"status": f"停止生成：{global_result['message']}", "candidate": None}
            continue
        if rows[-1].get("月份") != latest_month:
            store_results[site_id] = {"status": "未覆盖目标完整月", "candidate": None}
            continue
        if len(rows) < MIN_HISTORY_MONTHS:
            store_results[site_id] = {"status": f"有效历史不足 {MIN_HISTORY_MONTHS} 个月", "candidate": None}
            continue
        evaluation = evaluate_window(rows, len(rows) - 1)
        if evaluation is None:
            store_results[site_id] = {"status": "历史月份不连续或核心字段不完整", "candidate": None}
            continue
        if not evaluation["is_candidate"]:
            store_results[site_id] = {"status": "数据检查通过，暂未触发组合异常", "candidate": None}
            continue

        duration = 0
        for end_index in range(len(rows) - 1, MIN_HISTORY_MONTHS - 2, -1):
            previous = evaluate_window(rows, end_index)
            if not previous or not previous["is_candidate"]:
                break
            duration += 1
        trigger_key = "+".join(evaluation["trigger_codes"])
        candidate = {
            **evaluation,
            "candidate_id": f"operating-check:{site_id}:{latest_month}:{trigger_key}",
            "latest_month": latest_month,
            "duration_months": duration,
        }
        store_results[site_id] = {"status": "数据检查通过，进入经营异常核查候选", "candidate": candidate}

    return {"global": global_result, "stores": store_results}

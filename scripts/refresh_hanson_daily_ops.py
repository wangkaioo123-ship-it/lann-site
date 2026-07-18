"""Read Hanson daily closes and build analysis-safe monthly revenue plus 30/90-day trends."""

import argparse
import calendar
import csv
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from config import settings
from services import bi_client


POLICY = "config/ops_source_policy.json"
MAPPING = "config/store_site_mapping.json"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def fmt(value) -> str:
    return f"{number(value):.2f}"


def parse_day(value) -> date:
    return datetime.fromisoformat(str(value)[:10]).date()


def query_daily(start_date: str) -> list[dict]:
    sql = (
        "SELECT DATE(s.`DAY_CHECK_DATE`) AS data_date, s.`STORE_ID` AS store_id, "
        "MAX(i.`NAME`) AS store_name, SUM(g.`prod_amt`) AS prod_amt, COUNT(*) AS check_rows "
        "FROM `store_day_check` s "
        "JOIN `store_day_check_general_data` g ON g.`day_check_id` = s.`id` "
        "LEFT JOIN `org_store` i ON i.`ID` = s.`STORE_ID` "
        f"WHERE s.`DAY_CHECK_DATE` >= '{start_date}' "
        "GROUP BY DATE(s.`DAY_CHECK_DATE`), s.`STORE_ID` "
        "ORDER BY DATE(s.`DAY_CHECK_DATE`), s.`STORE_ID`"
    )
    payload = {
        "database": 2,
        "type": "native",
        "native": {"query": sql},
        "constraints": {"max-results": 50000, "max-results-bare-rows": 50000},
    }
    response = bi_client.post("/api/dataset", payload)
    response.raise_for_status()
    data = response.json().get("data", {})
    headers = [column.get("name") or column.get("display_name") or "" for column in data.get("cols", [])]
    return [dict(zip(headers, row)) for row in data.get("rows", [])]


def query_customer_monthly(start_month: str) -> list[dict]:
    sql = (
        "SELECT o.`monthly_time` AS data_month, o.`region_id` AS store_id, MAX(s.`name`) AS store_name, "
        "SUM(CASE WHEN o.`is_old` = 0 THEN o.`cust_num` ELSE 0 END) AS new_customer_count, "
        "SUM(CASE WHEN o.`is_old` = 1 THEN o.`cust_num` ELSE 0 END) AS old_customer_count, "
        "SUM(o.`cust_count`) AS order_customer_times, SUM(o.`cust_real_amt`) AS customer_real_amt, "
        "SUM(o.`last_consume_num`) AS retention_base_count, "
        "SUM(o.`consume_back_num`) AS retained_customer_count, "
        "SUM(o.`cust_order_num`) AS customer_order_count, "
        "COUNT(DISTINCT o.`is_old`) AS customer_segments, MAX(o.`create_date`) AS source_updated_at "
        "FROM `operate_monthly_indicator_data` o "
        "LEFT JOIN (SELECT `store_id`, MAX(`name`) AS `name` FROM `store_info` GROUP BY `store_id`) s "
        "ON s.`store_id` = o.`region_id` "
        f"WHERE o.`region_type` = 1 AND o.`monthly_time` >= '{start_month}' "
        "GROUP BY o.`monthly_time`, o.`region_id` ORDER BY o.`monthly_time`, o.`region_id`"
    )
    payload = {
        "database": 3,
        "type": "native",
        "native": {"query": sql},
        "constraints": {"max-results": 10000, "max-results-bare-rows": 10000},
    }
    response = bi_client.post("/api/dataset", payload)
    response.raise_for_status()
    data = response.json().get("data", {})
    headers = [column.get("name") or column.get("display_name") or "" for column in data.get("cols", [])]
    return [dict(zip(headers, row)) for row in data.get("rows", [])]


def load_mapping(rows: list[dict]) -> tuple[dict[str, str], set[str]]:
    mapped = {}
    excluded = set()
    for row in rows:
        name = (row.get("hanson_store_name") or row.get("Hanson门店名称") or "").strip()
        site_id = (row.get("site_id") or row.get("确认点位ID") or "").strip()
        if row.get("status") == "exclude" or site_id == "排除":
            excluded.add(name)
        elif name and site_id:
            mapped[name] = site_id
    return mapped, excluded


def build_monthly(daily_rows: list[dict], mapping_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    mapped, excluded = load_mapping(mapping_rows)
    latest_date = max((parse_day(row["data_date"]) for row in daily_rows), default=None)
    grouped = defaultdict(list)
    for row in daily_rows:
        name = str(row.get("store_name") or "").strip()
        if not name or name in excluded:
            continue
        day = parse_day(row["data_date"])
        grouped[(name, day.strftime("%Y-%m"))].append(row)

    output = []
    issues = []
    for (name, month), rows in sorted(grouped.items(), key=lambda item: (item[0][1], item[0][0])):
        year, month_number = (int(part) for part in month.split("-"))
        expected_days = calendar.monthrange(year, month_number)[1]
        days = {parse_day(row["data_date"]) for row in rows}
        site_id = mapped.get(name, "")
        revenue = sum(number(row.get("prod_amt")) for row in rows)
        is_closed_month = latest_date is not None and month < latest_date.strftime("%Y-%m")
        is_complete = len(days) == expected_days
        reasons = []
        if not site_id:
            reasons.append("门店未映射")
        if not is_closed_month:
            reasons.append("当月未结束")
        elif not is_complete:
            reasons.append(f"日结不完整({len(days)}/{expected_days})")
        if revenue <= 0:
            reasons.append("营收为0")
        included = not reasons
        output.append(
            {
                "点位ID": site_id,
                "Hanson门店ID": "；".join(sorted({str(row.get("store_id") or "") for row in rows})),
                "Hanson门店名称": name,
                "月份": month,
                "实际营收": fmt(revenue),
                "日结天数": len(days),
                "应有天数": expected_days,
                "数据完整性": "完整自然月" if is_complete and is_closed_month else "不完整",
                "分析纳入": "是" if included else "否",
                "质量备注": "；".join(reasons),
                "数据来源": "Hanson store_day_check prod_amt",
                "来源截止日": latest_date.isoformat() if latest_date else "",
            }
        )
        if reasons:
            issues.append({"Hanson门店名称": name, "月份": month, "问题": "；".join(reasons)})
    return output, issues


def resolved_point_id(name: str, target_date: date, mapped: dict[str, str], episodes: list[dict]) -> str:
    matches = []
    for episode in episodes:
        if episode.get("hanson_store_name") != name or episode.get("resolution_status") != "confirmed":
            continue
        start = datetime.fromisoformat(episode["effective_start"]).date() if episode.get("effective_start") else date.min
        end = datetime.fromisoformat(episode["effective_end"]).date() if episode.get("effective_end") else date.max
        if start <= target_date <= end:
            matches.append(episode.get("analysis_point_id", ""))
    return matches[0] if len(matches) == 1 else mapped.get(name, "")


def build_trends(daily_rows: list[dict], mapping_rows: list[dict], episodes: list[dict] | None = None) -> list[dict]:
    mapped, excluded = load_mapping(mapping_rows)
    coverage = defaultdict(set)
    for row in daily_rows:
        name = str(row.get("store_name") or "").strip()
        if name and name not in excluded and mapped.get(name):
            coverage[parse_day(row["data_date"])].add(name)
    peak_store_count = max((len(names) for names in coverage.values()), default=0)
    stable_threshold = math.ceil(peak_store_count * 0.8)
    stable_dates = [day for day, names in coverage.items() if len(names) >= stable_threshold]
    latest_date = max(stable_dates, default=None)
    if latest_date is None:
        return []
    by_store = defaultdict(list)
    for row in daily_rows:
        name = str(row.get("store_name") or "").strip()
        if name and name not in excluded and mapped.get(name) and parse_day(row["data_date"]) <= latest_date:
            by_store[name].append(row)
    output = []
    for name, rows in sorted(by_store.items()):
        item = {"点位ID": resolved_point_id(name, latest_date, mapped, episodes or []), "Hanson门店名称": name, "数据截止日": latest_date.isoformat()}
        for window in (30, 90):
            start = latest_date - timedelta(days=window - 1)
            selected = [row for row in rows if parse_day(row["data_date"]) >= start]
            revenue = sum(number(row.get("prod_amt")) for row in selected)
            days = len({parse_day(row["data_date"]) for row in selected})
            item[f"近{window}日营收"] = fmt(revenue)
            item[f"近{window}日日结天数"] = days
            item[f"近{window}日日均营收"] = fmt(revenue / days) if days else ""
        output.append(item)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Hanson daily prod_amt aggregates (read-only BI query).")
    parser.add_argument("--policy", default=POLICY)
    parser.add_argument("--mapping", default=MAPPING)
    parser.add_argument("--daily-out", default="data/staging/hanson_daily_prod_amt.csv")
    parser.add_argument("--monthly-out", default="data/staging/hanson_monthly_prod_amt.csv")
    parser.add_argument("--trend-out", default="data/staging/hanson_revenue_trends.csv")
    parser.add_argument("--issues-out", default="data/staging/hanson_daily_quality_issues.csv")
    parser.add_argument("--customer-out", default="data/staging/hanson_monthly_customer_metrics.csv")
    args = parser.parse_args()

    policy = json.loads((settings.ROOT_DIR / args.policy).read_text(encoding="utf-8"))
    daily = query_daily(policy["daily_source_start"])
    customer_monthly = query_customer_monthly(policy["daily_source_start"][:7])
    mapping_path = settings.ROOT_DIR / args.mapping
    mapping_rows = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path.suffix.lower() == ".json" else read_csv(mapping_path)
    episodes = json.loads((settings.ROOT_DIR / "config/site_identity_episodes.json").read_text(encoding="utf-8"))
    monthly, issues = build_monthly(daily, mapping_rows)
    trends = build_trends(daily, mapping_rows, episodes)

    daily_fields = ["data_date", "store_id", "store_name", "prod_amt", "check_rows"]
    monthly_fields = ["点位ID", "Hanson门店ID", "Hanson门店名称", "月份", "实际营收", "日结天数", "应有天数", "数据完整性", "分析纳入", "质量备注", "数据来源", "来源截止日"]
    trend_fields = ["点位ID", "Hanson门店名称", "数据截止日", "近30日营收", "近30日日结天数", "近30日日均营收", "近90日营收", "近90日日结天数", "近90日日均营收"]
    customer_fields = ["data_month", "store_id", "store_name", "new_customer_count", "old_customer_count", "order_customer_times", "customer_real_amt", "retention_base_count", "retained_customer_count", "customer_order_count", "customer_segments", "source_updated_at"]
    write_csv(settings.ROOT_DIR / args.daily_out, daily, daily_fields)
    write_csv(settings.ROOT_DIR / args.monthly_out, monthly, monthly_fields)
    write_csv(settings.ROOT_DIR / args.trend_out, trends, trend_fields)
    write_csv(settings.ROOT_DIR / args.issues_out, issues, ["Hanson门店名称", "月份", "问题"])
    write_csv(settings.ROOT_DIR / args.customer_out, customer_monthly, customer_fields)
    latest = max((parse_day(row["data_date"]) for row in daily), default=None)
    print(f"daily rows={len(daily)} latest={latest} monthly rows={len(monthly)} included={sum(row['分析纳入'] == '是' for row in monthly)}")
    print(f"trends={len(trends)} quality_issues={len(issues)}")
    print(f"customer_monthly={len(customer_monthly)}")


if __name__ == "__main__":
    main()

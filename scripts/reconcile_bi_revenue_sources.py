"""Compare Hanson daily close revenue with the current monthly indicator source.

This script is read-only against BI and writes only aggregate store-month results locally.
"""

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

from config import settings
from services import bi_client


MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")
NAME_NOISE = re.compile(r"[\s·•\-_（）()]+")


def query(database: int, sql: str, limit: int = 10000) -> tuple[list[str], list[list]]:
    payload = {
        "database": database,
        "type": "native",
        "native": {"query": sql},
        "constraints": {"max-results": limit, "max-results-bare-rows": limit},
    }
    response = bi_client.post("/api/dataset", payload)
    response.raise_for_status()
    data = response.json().get("data", {})
    headers = [column.get("name") or column.get("display_name") or "" for column in data.get("cols", [])]
    return headers, data.get("rows", [])


def dict_rows(headers: list[str], rows: list[list]) -> list[dict]:
    return [{header: row[index] if index < len(row) else "" for index, header in enumerate(headers)} for row in rows]


def dedupe_monthly(rows: list[dict]) -> dict[tuple[str, str], dict]:
    latest = {}
    for row in rows:
        key = (str(row.get("store_id") or ""), str(row.get("data_month") or ""))
        previous = latest.get(key)
        if previous is None or str(row.get("created_at") or "") >= str(previous.get("created_at") or ""):
            latest[key] = row
    return latest


def number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_name(value: str) -> str:
    text = NAME_NOISE.sub("", str(value or "").strip()).lower()
    text = text.replace("lann", "")
    return text[:-1] if text.endswith("店") else text


def aggregate_by_name(rows: list[dict], value_field: str) -> dict[tuple[str, str], dict]:
    aggregated = {}
    for row in rows:
        name_key = normalize_name(row.get("store_name", ""))
        month = str(row.get("data_month") or "")
        if not name_key or not month:
            continue
        key = (name_key, month)
        item = aggregated.setdefault(
            key,
            {
                "store_name": row.get("store_name", ""),
                "data_month": month,
                "store_ids": set(),
                "value": 0.0,
                "day_count": 0,
            },
        )
        store_id = str(row.get("store_id") or "")
        if store_id:
            item["store_ids"].add(store_id)
        item["value"] += number(row.get(value_field))
        item["day_count"] = max(item["day_count"], int(number(row.get("day_count"))))
    return aggregated


def compare(monthly: dict[tuple[str, str], dict], daily_rows: list[dict], daily_field: str = "daily_prod_amt") -> list[dict]:
    monthly_by_name = aggregate_by_name(list(monthly.values()), "real_income_with_marketing")
    daily = aggregate_by_name(daily_rows, daily_field)
    output = []
    for key in sorted(set(monthly_by_name) | set(daily), key=lambda item: (item[1], item[0])):
        month_row = monthly_by_name.get(key, {})
        day_row = daily.get(key, {})
        monthly_value = number(month_row.get("value"))
        daily_value = number(day_row.get("value"))
        difference = daily_value - monthly_value
        difference_ratio = difference / monthly_value if monthly_value else None
        if not month_row:
            status = "仅日结源"
        elif not day_row:
            status = "仅月度源"
        elif monthly_value == 0:
            status = "月度值为0"
        elif abs(difference_ratio or 0) <= 0.01:
            status = "差异<=1%"
        elif abs(difference_ratio or 0) <= 0.05:
            status = "差异1%-5%"
        else:
            status = "差异>5%"
        output.append(
            {
                "月份": key[1],
                "月度门店ID": "；".join(sorted(month_row.get("store_ids", set()))),
                "日结门店ID": "；".join(sorted(day_row.get("store_ids", set()))),
                "月度ID数": len(month_row.get("store_ids", set())),
                "日结ID数": len(day_row.get("store_ids", set())),
                "门店名称": day_row.get("store_name") or month_row.get("store_name", ""),
                "月度指标实际营收": f"{monthly_value:.2f}",
                "日结金额字段": daily_field.removeprefix("daily_"),
                "日结月合计": f"{daily_value:.2f}",
                "差额": f"{difference:.2f}",
                "差异比例": "" if difference_ratio is None else f"{difference_ratio:.6f}",
                "日结天数": day_row.get("day_count", ""),
                "对账状态": status,
            }
        )
    return output


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["月份", "月度门店ID", "日结门店ID", "月度ID数", "日结ID数", "门店名称", "月度指标实际营收", "日结金额字段", "日结月合计", "差额", "差异比例", "日结天数", "对账状态"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile aggregate revenue between Hanson monthly and daily sources.")
    parser.add_argument("--start-month", default="2026-01")
    parser.add_argument("--end-month", default="2026-03")
    parser.add_argument("--daily-field", choices=("prod_amt", "flow_amt", "goods_amt"), default="prod_amt")
    parser.add_argument("--out", default="data/staging/bi_revenue_source_reconciliation.csv")
    args = parser.parse_args()
    if not MONTH_PATTERN.fullmatch(args.start_month) or not MONTH_PATTERN.fullmatch(args.end_month):
        raise ValueError("月份必须为 YYYY-MM")

    monthly_headers, monthly_raw = query(
        3,
        "SELECT `store_id`, `store_name`, `data_month`, `real_income_with_marketing`, `created_at` "
        "FROM `report_store_month_indicator_export` "
        f"WHERE `data_month` BETWEEN '{args.start_month}' AND '{args.end_month}'",
    )
    daily_headers, daily_raw = query(
        2,
        "SELECT DATE_FORMAT(s.`DAY_CHECK_DATE`, '%Y-%m') AS data_month, "
        "s.`STORE_ID` AS store_id, MAX(i.`NAME`) AS store_name, "
        f"SUM(g.`{args.daily_field}`) AS daily_{args.daily_field}, "
        "COUNT(DISTINCT DATE(s.`DAY_CHECK_DATE`)) AS day_count "
        "FROM `store_day_check` s "
        "JOIN `store_day_check_general_data` g ON g.`day_check_id` = s.`id` "
        "LEFT JOIN `org_store` i ON i.`ID` = s.`STORE_ID` "
        f"WHERE s.`DAY_CHECK_DATE` >= '{args.start_month}-01' "
        f"AND s.`DAY_CHECK_DATE` < DATE_ADD(LAST_DAY('{args.end_month}-01'), INTERVAL 1 DAY) "
        "GROUP BY DATE_FORMAT(s.`DAY_CHECK_DATE`, '%Y-%m'), s.`STORE_ID`",
    )

    monthly = dedupe_monthly(dict_rows(monthly_headers, monthly_raw))
    rows = compare(monthly, dict_rows(daily_headers, daily_raw), f"daily_{args.daily_field}")
    out_path = settings.ROOT_DIR / args.out
    write_csv(out_path, rows)
    counts = Counter(row["对账状态"] for row in rows)
    print(f"wrote {out_path} rows={len(rows)}")
    print("reconciliation", dict(counts))


if __name__ == "__main__":
    main()

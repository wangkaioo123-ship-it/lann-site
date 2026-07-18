"""Bridge Wang Lei's monthly history with Hanson daily-close monthly revenue."""

import argparse
import csv
import json
from pathlib import Path

from config import settings


QUALITY_FIELDS = ["来源口径", "日结天数", "应有天数", "数据完整性", "分析纳入", "质量备注", "来源截止日", "客户指标来源", "客户指标完整性"]


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def combine(monthly_rows: list[dict], daily_rows: list[dict], monthly_end: str, customer_rows: list[dict] | None = None) -> list[dict]:
    customer_by_store_month = {
        ((row.get("store_name") or "").strip(), row.get("data_month", "")): row
        for row in (customer_rows or [])
        if row.get("store_name") and row.get("data_month")
    }
    output = []
    for row in monthly_rows:
        if row.get("月份", "") <= monthly_end:
            copied = dict(row)
            copied.update(
                {
                    "来源口径": "王磊月度稿 real_income_with_marketing",
                    "日结天数": "",
                    "应有天数": "",
                    "数据完整性": "月度源已结算",
                    "分析纳入": "是" if float(row.get("实际营收") or 0) > 0 else "否",
                    "质量备注": "" if float(row.get("实际营收") or 0) > 0 else "营收为0",
                    "来源截止日": monthly_end,
                    "客户指标来源": "王磊月度稿",
                    "客户指标完整性": "月度源已结算",
                }
            )
            output.append(copied)

    monthly_fields = list(monthly_rows[0].keys()) if monthly_rows else []
    for row in daily_rows:
        if row.get("月份", "") <= monthly_end or row.get("分析纳入") != "是":
            continue
        copied = {field: "" for field in monthly_fields}
        customer = customer_by_store_month.get(((row.get("Hanson门店名称") or "").strip(), row.get("月份", "")), {})
        new_customers = float(customer.get("new_customer_count") or 0) if customer else 0
        old_customers = float(customer.get("old_customer_count") or 0) if customer else 0
        order_times = float(customer.get("order_customer_times") or 0) if customer else 0
        revenue = float(row.get("实际营收") or 0)
        total_customers = new_customers + old_customers
        retention_base = float(customer.get("retention_base_count") or 0) if customer else 0
        retained_customers = float(customer.get("retained_customer_count") or 0) if customer else 0
        customer_orders = float(customer.get("customer_order_count") or 0) if customer else 0
        customer_complete = bool(customer) and int(float(customer.get("customer_segments") or 0)) == 2
        copied.update(
            {
                "点位ID": row.get("点位ID", ""),
                "Hanson门店ID": row.get("Hanson门店ID", ""),
                "Hanson门店名称": row.get("Hanson门店名称", ""),
                "月份": row.get("月份", ""),
                "实际营收": row.get("实际营收", ""),
                "订单客次": f"{order_times:.0f}" if customer_complete else "",
                "新客数": f"{new_customers:.0f}" if customer_complete else "",
                "老客数": f"{old_customers:.0f}" if customer_complete else "",
                "总客数": f"{new_customers + old_customers:.0f}" if customer_complete else "",
                "客单价_折扣后": f"{revenue / order_times:.2f}" if customer_complete and order_times else "",
                "留存率": f"{100 * retained_customers / retention_base:.2f}" if customer_complete and retention_base else "",
                "返店频次": f"{customer_orders / total_customers:.2f}" if customer_complete and total_customers else "",
                "数据来源": row.get("数据来源", ""),
                "来源口径": "Hanson店长日结 prod_amt",
                "日结天数": row.get("日结天数", ""),
                "应有天数": row.get("应有天数", ""),
                "数据完整性": row.get("数据完整性", ""),
                "分析纳入": row.get("分析纳入", ""),
                "质量备注": row.get("质量备注", ""),
                "来源截止日": row.get("来源截止日", ""),
                "客户指标来源": "Hanson operate_monthly_indicator_data" if customer_complete else "",
                "客户指标完整性": "新老客分段完整" if customer_complete else "缺客户月指标",
            }
        )
        output.append(copied)

    output.sort(key=lambda row: (row.get("月份", ""), row.get("Hanson门店名称", "")))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the approved monthly/daily operating source bridge.")
    parser.add_argument("--policy", default="config/ops_source_policy.json")
    parser.add_argument("--monthly", default="data/staging/site_ops_monthly_bi.csv")
    parser.add_argument("--daily", default="data/staging/hanson_monthly_prod_amt.csv")
    parser.add_argument("--customer", default="data/staging/hanson_monthly_customer_metrics.csv")
    parser.add_argument("--out", default="data/staging/site_ops_monthly_combined.csv")
    args = parser.parse_args()
    policy = json.loads((settings.ROOT_DIR / args.policy).read_text(encoding="utf-8"))
    monthly_rows = read_csv(settings.ROOT_DIR / args.monthly)
    daily_rows = read_csv(settings.ROOT_DIR / args.daily)
    customer_rows = read_csv(settings.ROOT_DIR / args.customer)
    rows = combine(monthly_rows, daily_rows, policy["monthly_source_end"], customer_rows)
    fields = list(monthly_rows[0].keys()) + QUALITY_FIELDS
    write_csv(settings.ROOT_DIR / args.out, rows, fields)
    sources = {}
    for row in rows:
        sources[row["来源口径"]] = sources.get(row["来源口径"], 0) + 1
    print(f"wrote {settings.ROOT_DIR / args.out} rows={len(rows)} sources={sources}")


if __name__ == "__main__":
    main()

import argparse
import csv

from config import settings
from services import bi_client


BI_DATABASE_ID = 3
BI_TABLE_ID = 825
BI_TABLE_NAME = "report_store_month_indicator_export"
MAPPING = settings.ROOT_DIR / "data" / "staging" / "store_month_mapping_review.csv"

BI_FIELDS = [
    "id",
    "batch_id",
    "created_at",
    "store_id",
    "store_name",
    "data_month",
    "cash_flow",
    "real_income_with_marketing",
    "open_card_income",
    "order_customer_times",
    "per_customer_after_discount",
    "per_customer_before_discount",
    "discount_rate",
    "new_per_customer_before_discount",
    "new_per_customer_after_discount",
    "old_per_customer_before_discount",
    "old_per_customer_after_discount",
    "new_customer_count",
    "old_customer_count",
    "retention_rate",
    "second_store_rate",
    "return_store_frequency",
    "open_card_people",
    "open_card_income_stored",
    "average_stored_value",
    "stored_value_discount_rate",
    "stored_member_conversion_rate",
    "stored_member_recharge_rate",
    "unrecharge_people",
    "point_count",
    "point_rate",
    "bad_emp_eval_count",
    "bad_order_eval_count",
    "reward_count",
    "reward_amount",
    "wechat_subscribe_count",
    "therapist_workdays",
    "therapist_daily_service_customers",
    "therapist_daily_output",
    "therapist_production_rate",
    "therapist_daily_open_card_people",
    "therapist_daily_open_card_amount",
]


def clean_num(value):
    if value in ("", None):
        return ""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    if n.is_integer():
        return str(int(n))
    return f"{n:.6f}".rstrip("0").rstrip(".")


def query_rows(limit: int) -> tuple[list[str], list[list]]:
    payload = {
        "database": BI_DATABASE_ID,
        "type": "query",
        "query": {
            "source-table": BI_TABLE_ID,
            "limit": limit,
        },
    }
    resp = bi_client.post("/api/dataset", payload)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    headers = [col.get("name") or col.get("display_name") or "" for col in data.get("cols", [])]
    return headers, data.get("rows", [])


def query_native_page(limit: int, offset: int) -> tuple[list[str], list[list]]:
    field_sql = ", ".join(f"`{field}`" for field in BI_FIELDS)
    sql = (
        f"SELECT {field_sql} FROM `{BI_TABLE_NAME}` "
        f"ORDER BY `data_month`, `store_id` LIMIT {int(limit)} OFFSET {int(offset)}"
    )
    payload = {
        "database": BI_DATABASE_ID,
        "type": "native",
        "native": {"query": sql},
        "constraints": {
            "max-results": limit,
            "max-results-bare-rows": limit,
        },
    }
    resp = bi_client.post("/api/dataset", payload)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    headers = [col.get("name") or col.get("display_name") or "" for col in data.get("cols", [])]
    return headers, data.get("rows", [])


def query_native_all(page_size: int, max_rows: int) -> tuple[list[str], list[list]]:
    all_rows = []
    headers = BI_FIELDS
    offset = 0
    while offset < max_rows:
        page_headers, page_rows = query_native_page(page_size, offset)
        if page_headers:
            headers = page_headers
        if not page_rows:
            break
        all_rows.extend(page_rows)
        print(f"fetched offset={offset} rows={len(page_rows)} total={len(all_rows)}")
        if len(page_rows) < page_size:
            break
        offset += page_size
    return headers, all_rows


def load_mapping() -> tuple[dict[str, str], set[str]]:
    mapping_rows = list(csv.DictReader(MAPPING.open(encoding="utf-8-sig", newline="")))
    store_to_site = {}
    excluded = set()
    for row in mapping_rows:
        store = row["Hanson门店名称"]
        site_id = (row.get("确认点位ID") or "").strip()
        if site_id == "排除":
            excluded.add(store)
        elif site_id:
            store_to_site[store] = site_id
    return store_to_site, excluded


def row_dict(headers: list[str], row: list) -> dict:
    return {header: row[i] if i < len(row) else "" for i, header in enumerate(headers)}


def dedupe_latest(headers: list[str], rows: list[list]) -> list[list]:
    latest = {}
    for raw in rows:
        row = row_dict(headers, raw)
        key = (row.get("store_name") or "", row.get("data_month") or "")
        if not key[0] or not key[1]:
            key = (row.get("id") or len(latest), "")
        prev = latest.get(key)
        if prev is None:
            latest[key] = raw
            continue
        prev_row = row_dict(headers, prev)
        if str(row.get("created_at") or "") >= str(prev_row.get("created_at") or ""):
            latest[key] = raw
    return list(latest.values())


def main():
    parser = argparse.ArgumentParser(description="Export monthly store operations from BI Metabase.")
    parser.add_argument("--limit", type=int, default=50000)
    parser.add_argument("--page-size", type=int, default=2000)
    parser.add_argument("--mbql", action="store_true", help="Use Metabase table query instead of native SQL.")
    parser.add_argument(
        "--raw-out",
        default="data/staging/ops_monthly_raw_bi.csv",
    )
    parser.add_argument(
        "--site-out",
        default="data/staging/site_ops_monthly_bi.csv",
    )
    args = parser.parse_args()

    if args.mbql:
        headers, rows = query_rows(args.limit)
    else:
        headers, rows = query_native_all(args.page_size, args.limit)
    all_rows = rows
    rows = dedupe_latest(headers, all_rows)
    store_to_site, excluded = load_mapping()

    raw_out = settings.ROOT_DIR / args.raw_out
    raw_out.parent.mkdir(parents=True, exist_ok=True)
    with raw_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    site_headers = [
        "点位ID",
        "Hanson门店ID",
        "Hanson门店名称",
        "月份",
        "实际营收",
        "现金流",
        "开卡收入",
        "订单客次",
        "新客数",
        "老客数",
        "总客数",
        "客单价_折扣后",
        "客单价_折扣前",
        "留存率",
        "二次到店率",
        "返店频次",
        "开卡人次",
        "点钟数",
        "理疗师工作人天",
        "理疗师日均服务客次",
        "理疗师日均产值",
        "理疗师生产率",
        "数据来源",
    ]
    site_rows = []
    skipped = 0
    for raw in rows:
        row = row_dict(headers, raw)
        store_name = str(row.get("store_name") or "")
        if store_name in excluded or store_name not in store_to_site:
            skipped += 1
            continue
        new_customers = clean_num(row.get("new_customer_count"))
        old_customers = clean_num(row.get("old_customer_count"))
        total_customers = ""
        try:
            total_customers = clean_num(float(new_customers or 0) + float(old_customers or 0))
        except ValueError:
            pass
        site_rows.append(
            [
                store_to_site[store_name],
                clean_num(row.get("store_id")),
                store_name,
                row.get("data_month") or "",
                clean_num(row.get("real_income_with_marketing")),
                clean_num(row.get("cash_flow")),
                clean_num(row.get("open_card_income")),
                clean_num(row.get("order_customer_times")),
                new_customers,
                old_customers,
                total_customers,
                clean_num(row.get("per_customer_after_discount")),
                clean_num(row.get("per_customer_before_discount")),
                clean_num(row.get("retention_rate")),
                clean_num(row.get("second_store_rate")),
                clean_num(row.get("return_store_frequency")),
                clean_num(row.get("open_card_people")),
                clean_num(row.get("point_count")),
                clean_num(row.get("therapist_workdays")),
                clean_num(row.get("therapist_daily_service_customers")),
                clean_num(row.get("therapist_daily_output")),
                clean_num(row.get("therapist_production_rate")),
                "BI Metabase report_store_month_indicator_export",
            ]
        )

    site_out = settings.ROOT_DIR / args.site_out
    with site_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(site_headers)
        writer.writerows(site_rows)

    months = sorted({row[3] for row in site_rows if row[3]})
    print(f"source_rows={len(all_rows)}")
    print(f"wrote {raw_out} rows={len(rows)}")
    print(f"wrote {site_out} rows={len(site_rows)} skipped_raw_rows={skipped}")
    print(f"deduped_rows={len(rows)} removed_duplicates={len(all_rows) - len(rows)}")
    if months:
        print(f"months={months[0]}..{months[-1]}")
    print(f"mapped_stores={len(store_to_site)} excluded_stores={len(excluded)}")


if __name__ == "__main__":
    main()

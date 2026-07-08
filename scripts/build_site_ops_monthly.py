import csv
from pathlib import Path


RAW = Path("data/staging/ops_monthly_raw.csv")
MAPPING = Path("data/staging/store_month_mapping_review.csv")
OUT = Path("data/staging/site_ops_monthly.csv")


NUMERIC_FIELDS = [
    "现金流",
    "实际收入（含营销）",
    "开卡收入",
    "订单客次",
    "客单价（折扣后）",
    "客单价（折扣前）",
    "新客数量",
    "老客数量",
    "留存率",
    "二次到店率",
    "返店频次",
    "开卡人次",
    "点钟数",
    "理疗师工作人天",
    "理疗师日均服务客次",
    "理疗师日均产值",
    "理疗师生产率",
]


def clean_num(value):
    value = (value or "").strip()
    if not value:
        return ""
    try:
        n = float(value)
    except ValueError:
        return value
    if n.is_integer():
        return str(int(n))
    return f"{n:.6f}".rstrip("0").rstrip(".")


def main():
    mapping_rows = list(csv.DictReader(MAPPING.open(encoding="utf-8-sig", newline="")))
    store_to_site = {}
    excluded = set()
    for row in mapping_rows:
        store = row["Hanson门店名称"]
        site_id = (row.get("确认点位ID") or "").strip()
        if site_id == "排除":
            excluded.add(store)
        else:
            store_to_site[store] = site_id

    raw_rows = list(csv.DictReader(RAW.open(encoding="utf-8-sig", newline="")))
    headers = [
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

    out = []
    skipped = 0
    for row in raw_rows:
        store = row["门店名称"]
        if store in excluded or store not in store_to_site:
            skipped += 1
            continue
        site_id = store_to_site[store]
        new_customers = clean_num(row.get("新客数量", ""))
        old_customers = clean_num(row.get("老客数量", ""))
        total_customers = ""
        try:
            total_customers = clean_num(str(float(new_customers or 0) + float(old_customers or 0)))
        except ValueError:
            pass
        out.append(
            [
                site_id,
                clean_num(row.get("门店ID", "")),
                store,
                row.get("数据年月", ""),
                clean_num(row.get("实际收入（含营销）", "")),
                clean_num(row.get("现金流", "")),
                clean_num(row.get("开卡收入", "")),
                clean_num(row.get("订单客次", "")),
                new_customers,
                old_customers,
                total_customers,
                clean_num(row.get("客单价（折扣后）", "")),
                clean_num(row.get("客单价（折扣前）", "")),
                clean_num(row.get("留存率", "")),
                clean_num(row.get("二次到店率", "")),
                clean_num(row.get("返店频次", "")),
                clean_num(row.get("开卡人次", "")),
                clean_num(row.get("点钟数", "")),
                clean_num(row.get("理疗师工作人天", "")),
                clean_num(row.get("理疗师日均服务客次", "")),
                clean_num(row.get("理疗师日均产值", "")),
                clean_num(row.get("理疗师生产率", "")),
                "Hanson store-month Excel",
            ]
        )

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(out)

    print(f"wrote {OUT}")
    print(f"rows={len(out)} skipped_raw_rows={skipped}")
    print(f"mapped_stores={len(store_to_site)} excluded_stores={len(excluded)}")


if __name__ == "__main__":
    main()

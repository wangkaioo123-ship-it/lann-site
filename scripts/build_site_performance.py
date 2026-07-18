import csv
import argparse
from collections import defaultdict
from pathlib import Path


BASE = Path("data/staging/base_table.csv")
OPS = Path("data/staging/site_ops_monthly.csv")
RENT = Path("data/staging/rent_extract.csv")
MONTHLY_OUT = Path("data/staging/site_performance_monthly.csv")
SUMMARY_OUT = Path("data/staging/site_performance_summary.csv")
DEFAULT_EXCLUDE_SITE_IDS = {"L0035", "L0085"}


def read_csv(path):
    return list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))


def num(value):
    try:
        return float(value) if value not in ("", None) else 0.0
    except ValueError:
        return 0.0


def fmt(value, digits=2):
    if value in ("", None):
        return ""
    try:
        value = float(value)
    except ValueError:
        return value
    if value == 0:
        return "0"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def choose_base_row(rows):
    if not rows:
        return {}
    # Duplicate IDs exist for old/new addresses. Prefer active/current records for forward-looking analysis.
    status_rank = {"运营中": 0, "在建": 1, "待建": 2, "已终止": 9}
    return sorted(rows, key=lambda r: status_rank.get(r.get("门店状态", ""), 5))[0]


def build(
    rent_path=RENT,
    monthly_out=MONTHLY_OUT,
    summary_out=SUMMARY_OUT,
    ops_path=OPS,
    exclude_site_ids=None,
    base_path=BASE,
):
    exclude_site_ids = set(exclude_site_ids or [])
    base_rows = read_csv(Path(base_path))
    ops_rows = read_csv(Path(ops_path))
    rent_rows = read_csv(Path(rent_path))

    base_by_id = defaultdict(list)
    for row in base_rows:
        if row.get("点位ID"):
            base_by_id[row["点位ID"]].append(row)
    base_by_id = {site_id: choose_base_row(rows) for site_id, rows in base_by_id.items()}
    rent_by_id = {row["点位ID"]: row for row in rent_rows if row.get("点位ID")}

    monthly_headers = [
        "点位ID",
        "门店名称",
        "Hanson门店名称",
        "城市",
        "门店属性",
        "门店状态",
        "月份",
        "实际营收",
        "月租金",
        "租金状态",
        "租售比",
        "新客数",
        "老客数",
        "总客数",
        "订单客次",
        "客单价_折扣后",
        "开卡收入",
        "理疗师工作人天",
        "理疗师日均产值",
        "理疗师生产率",
        "租金来源文件",
        "租金备注",
        "营收数据来源",
        "营收数据完整性",
        "营收质量备注",
        "留存率",
        "返店频次",
    ]

    monthly = []
    for op in ops_rows:
        site_id = op["点位ID"]
        if site_id in exclude_site_ids:
            continue
        base = base_by_id.get(site_id, {})
        rent = rent_by_id.get(site_id, {})
        monthly_rent = num(rent.get("当年租金", ""))
        revenue = num(op.get("实际营收", ""))
        rent_ratio = monthly_rent / revenue if monthly_rent and revenue else ""
        rent_status = rent.get("状态", "缺租金")
        if not rent:
            rent_status = "缺租金"
        monthly.append(
            [
                site_id,
                base.get("门店名称", ""),
                op.get("Hanson门店名称", ""),
                base.get("城市", ""),
                base.get("门店属性", ""),
                base.get("门店状态", ""),
                op.get("月份", ""),
                fmt(revenue),
                fmt(monthly_rent) if monthly_rent else "",
                rent_status,
                fmt(rent_ratio, 4) if rent_ratio != "" else "",
                fmt(op.get("新客数", "")),
                fmt(op.get("老客数", "")),
                fmt(op.get("总客数", "")),
                fmt(op.get("订单客次", "")),
                fmt(op.get("客单价_折扣后", "")),
                fmt(op.get("开卡收入", "")),
                fmt(op.get("理疗师工作人天", "")),
                fmt(op.get("理疗师日均产值", "")),
                fmt(op.get("理疗师生产率", "")),
                rent.get("来源文件", ""),
                rent.get("备注", ""),
                op.get("来源口径") or op.get("数据来源", ""),
                op.get("数据完整性", ""),
                op.get("质量备注", ""),
                fmt(op.get("留存率", "")),
                fmt(op.get("返店频次", "")),
            ]
        )

    monthly_out = Path(monthly_out)
    summary_out = Path(summary_out)

    with monthly_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(monthly_headers)
        writer.writerows(monthly)

    all_months = sorted({row["月份"] for row in ops_rows if row.get("月份")})
    recent_months = set(all_months[-12:])
    by_site = defaultdict(list)
    for row in monthly:
        if row[6] in recent_months:
            by_site[row[0]].append(row)

    summary_headers = [
        "点位ID",
        "门店名称",
        "Hanson门店名称",
        "城市",
        "门店属性",
        "门店状态",
        "统计月份起",
        "统计月份止",
        "有数据月份数",
        "有营收月份数",
        "近12月营收",
        "近12月平均月营收",
        "月租金",
        "租金状态",
        "租售比_按平均月营收",
        "近12月新客数",
        "平均月新客数",
        "客户指标月份数",
        "客户指标截至月份",
        "近12月总客数",
        "平均客单价_折扣后",
        "平均理疗师日均产值",
        "分析可用性",
        "营收来源说明",
        "平均留存率",
        "平均返店频次",
    ]

    summary = []
    for site_id, rows in sorted(by_site.items()):
        first = rows[0]
        revenues = [num(r[7]) for r in rows]
        nonzero_revenues = [x for x in revenues if x > 0]
        revenue_sum = sum(revenues)
        active_month_count = len(nonzero_revenues)
        avg_revenue = revenue_sum / active_month_count if active_month_count else 0
        monthly_rent = num(first[8])
        ratio = monthly_rent / avg_revenue if monthly_rent and avg_revenue else ""
        new_rows = [r for r in rows if r[11] not in ("", None)]
        customer_rows = [r for r in rows if r[13] not in ("", None)]
        new_sum = sum(num(r[11]) for r in new_rows)
        customer_sum = sum(num(r[13]) for r in customer_rows)
        metric_months = sorted(r[6] for r in rows if r[11] not in ("", None) or r[13] not in ("", None))
        avg_ticket_values = [num(r[15]) for r in rows if num(r[15]) > 0]
        avg_therapist_prod_values = [num(r[18]) for r in rows if num(r[18]) > 0]
        retention_values = [num(r[25]) for r in rows if len(r) > 25 and r[25] not in ("", None)]
        return_frequency_values = [num(r[26]) for r in rows if len(r) > 26 and r[26] not in ("", None)]

        if first[9] == "当年已定" and nonzero_revenues:
            usability = "可用于租售比分析"
        elif first[9] != "当年已定":
            usability = "缺有效租金"
        else:
            usability = "缺有效营收"

        summary.append(
            [
                site_id,
                first[1],
                first[2],
                first[3],
                first[4],
                first[5],
                all_months[-12],
                all_months[-1],
                len(rows),
                len(nonzero_revenues),
                fmt(revenue_sum),
                fmt(avg_revenue),
                fmt(monthly_rent) if monthly_rent else "",
                first[9],
                fmt(ratio, 4) if ratio != "" else "",
                fmt(new_sum),
                fmt(new_sum / len(new_rows) if new_rows else ""),
                len(metric_months),
                metric_months[-1] if metric_months else "",
                fmt(customer_sum),
                fmt(sum(avg_ticket_values) / len(avg_ticket_values) if avg_ticket_values else ""),
                fmt(
                    sum(avg_therapist_prod_values) / len(avg_therapist_prod_values)
                    if avg_therapist_prod_values
                    else ""
                ),
                usability,
                "；".join(sorted({r[22] for r in rows if len(r) > 22 and r[22]})),
                fmt(sum(retention_values) / len(retention_values) if retention_values else ""),
                fmt(sum(return_frequency_values) / len(return_frequency_values) if return_frequency_values else ""),
            ]
        )

    with summary_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(summary_headers)
        writer.writerows(summary)

    print(f"wrote {monthly_out} rows={len(monthly)}")
    print(f"wrote {summary_out} rows={len(summary)} months={all_months[-12]}..{all_months[-1]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rent-file", default=str(RENT))
    parser.add_argument("--ops-file", default=str(OPS))
    parser.add_argument("--monthly-out", default=str(MONTHLY_OUT))
    parser.add_argument("--summary-out", default=str(SUMMARY_OUT))
    parser.add_argument("--base-file", default=str(BASE))
    parser.add_argument(
        "--include-excluded-sites",
        action="store_true",
        help="Include sites intentionally excluded from the analysis sample.",
    )
    args = parser.parse_args()
    exclude_site_ids = set() if args.include_excluded_sites else DEFAULT_EXCLUDE_SITE_IDS
    build(args.rent_file, args.monthly_out, args.summary_out, args.ops_file, exclude_site_ids, args.base_file)

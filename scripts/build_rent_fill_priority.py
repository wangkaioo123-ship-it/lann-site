import csv
from pathlib import Path


SUMMARY = Path("data/staging/site_performance_summary.csv")
OUT = Path("data/staging/rent_fill_priority.csv")


def num(value):
    try:
        return float(value) if value not in ("", None) else 0.0
    except ValueError:
        return 0.0


def main():
    rows = list(csv.DictReader(SUMMARY.open(encoding="utf-8-sig", newline="")))
    missing = [
        row
        for row in rows
        if row["分析可用性"] == "缺有效租金" and num(row["近12月营收"]) > 0
    ]
    missing.sort(key=lambda row: num(row["近12月平均月营收"]), reverse=True)

    headers = [
        "优先级",
        "点位ID",
        "门店名称",
        "Hanson门店名称",
        "城市",
        "门店属性",
        "门店状态",
        "近12月平均月营收",
        "近12月营收",
        "有营收月份数",
        "当前租金状态",
        "建议动作",
    ]
    out = []
    for i, row in enumerate(missing, 1):
        rent_status = row["租金状态"]
        if rent_status == "缺租金":
            action = "补月租金、含税口径、租金来源文件"
        elif "续约文档" in rent_status:
            action = "补2026现行续约协议或付款通知"
        elif "商务条款" in rent_status:
            action = "补商务条款附件/付款通知/财务实付"
        elif "待你给文档" in rent_status:
            action = "补最终租赁合同或现行付款材料"
        else:
            action = "复核租金状态"
        out.append(
            [
                i,
                row["点位ID"],
                row["门店名称"],
                row["Hanson门店名称"],
                row["城市"],
                row["门店属性"],
                row["门店状态"],
                row["近12月平均月营收"],
                row["近12月营收"],
                row["有营收月份数"],
                rent_status,
                action,
            ]
        )

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(out)

    print(f"wrote {OUT} rows={len(out)}")


if __name__ == "__main__":
    main()

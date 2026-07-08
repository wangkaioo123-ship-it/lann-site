import csv
import argparse
from collections import Counter
from pathlib import Path


def num(value):
    try:
        return float(value) if value not in ("", None) else 0.0
    except ValueError:
        return 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", default="data/staging/site_performance_summary.csv")
    args = parser.parse_args()
    rows = list(csv.DictReader(Path(args.summary).open(encoding="utf-8-sig", newline="")))
    print(f"summary_rows={len(rows)}")
    print(Counter(row["分析可用性"] for row in rows))
    print(Counter(row["租金状态"] for row in rows))

    usable = [row for row in rows if row["分析可用性"] == "可用于租售比分析"]
    print(f"usable={len(usable)}")
    print("\nusable sorted by rent ratio desc:")
    for row in sorted(usable, key=lambda r: num(r["租售比_按平均月营收"]), reverse=True):
        print(
            row["点位ID"],
            row["门店名称"],
            "avg_rev=" + row["近12月平均月营收"],
            "rent=" + row["月租金"],
            "ratio=" + row["租售比_按平均月营收"],
            "months=" + row["有营收月份数"],
        )

    print("\nmissing rent with revenue:")
    for row in rows:
        if row["分析可用性"] == "缺有效租金" and num(row["近12月营收"]) > 0:
            print(row["点位ID"], row["门店名称"], row["Hanson门店名称"], row["近12月平均月营收"])


if __name__ == "__main__":
    main()

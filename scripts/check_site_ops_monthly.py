import csv
from collections import Counter
from pathlib import Path


def num(value):
    try:
        return float(value) if value not in ("", None) else 0.0
    except ValueError:
        return 0.0


def main():
    rows = list(csv.DictReader(Path("data/staging/site_ops_monthly.csv").open(encoding="utf-8-sig", newline="")))
    site_ids = {row["点位ID"] for row in rows}
    months = [row["月份"] for row in rows if row["月份"]]
    nonzero = [row for row in rows if num(row["实际营收"]) > 0]
    keys = Counter((row["点位ID"], row["月份"]) for row in rows)
    dups = [(key, count) for key, count in keys.items() if count > 1]

    print(f"rows={len(rows)}")
    print(f"site_ids={len(site_ids)}")
    print(f"months={min(months)}..{max(months)} distinct={len(set(months))}")
    print(f"nonzero_revenue_rows={len(nonzero)}")
    print(f"duplicate_site_month_keys={len(dups)}")
    if dups:
        print("dups sample:")
        for item in dups[:20]:
            print(item)
    print("top revenue rows:")
    for row in sorted(nonzero, key=lambda r: num(r["实际营收"]), reverse=True)[:10]:
        print(row["点位ID"], row["Hanson门店名称"], row["月份"], row["实际营收"])


if __name__ == "__main__":
    main()

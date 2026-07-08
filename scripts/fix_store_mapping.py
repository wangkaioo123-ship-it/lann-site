import csv
from pathlib import Path


def main():
    path = Path("data/staging/store_month_mapping_review.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    fields = list(rows[0].keys())
    changed = 0
    for row in rows:
        if row["Hanson门店名称"] == "新天地店":
            row["确认点位ID"] = "L0003"
            if not (row.get("确认备注") or "").strip():
                row["确认备注"] = "按用户确认：新天地店对应 L0003"
            changed += 1
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"changed={changed}")


if __name__ == "__main__":
    main()

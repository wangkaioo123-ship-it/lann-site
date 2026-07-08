import csv
from pathlib import Path


def main():
    mapping = list(
        csv.DictReader(Path("data/staging/store_month_mapping_review.csv").open(encoding="utf-8-sig", newline=""))
    )
    base = list(csv.DictReader(Path("data/staging/base_table.csv").open(encoding="utf-8-sig", newline="")))
    valid = {r["点位ID"] for r in base if r.get("点位ID")}
    # These appear in Hanson/base adjacent data but are not standard L IDs.
    valid.update({"NM0001", "NM0002"})

    blank = []
    invalid = []
    excluded = []
    confirmed = []
    for row in mapping:
        confirmed_id = (row.get("确认点位ID") or "").strip()
        if not confirmed_id:
            blank.append(row)
        elif confirmed_id == "排除":
            excluded.append(row)
        elif confirmed_id not in valid:
            invalid.append(row)
        else:
            confirmed.append(row)

    print(
        f"rows={len(mapping)} confirmed={len(confirmed)} "
        f"excluded={len(excluded)} blank={len(blank)} invalid={len(invalid)}"
    )
    if blank:
        print("\nBLANK")
        for row in blank:
            print(
                row.get("Hanson门店名称", ""),
                row.get("候选点位ID", ""),
                row.get("候选底表门店名称", ""),
                row.get("确认备注", ""),
            )
    if invalid:
        print("\nINVALID")
        for row in invalid:
            print(row.get("Hanson门店名称", ""), row.get("确认点位ID", ""), row.get("确认备注", ""))
    if excluded:
        print("\nEXCLUDED")
        for row in excluded:
            print(row.get("Hanson门店名称", ""), row.get("确认备注", ""))


if __name__ == "__main__":
    main()

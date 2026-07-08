import csv
import re
import zipfile
from difflib import SequenceMatcher
from pathlib import Path

from scripts.inspect_xlsx_stdlib import read_sheet, workbook_sheets


EXCLUDE_STORES = {
    "",
    "新店模型",
    "上海支持中心",
    "培训部（上海分公司）",
    "培训部（华东分公司）",
    "lann store",
}


def norm(s):
    s = (s or "").lower()
    for x in [
        "上海",
        "杭州",
        "成都",
        "武汉",
        "苏州",
        "温州",
        "宁波",
        "深圳",
        "贵阳",
        "昆明",
        "lann",
        "蘭",
        "籣",
        "店",
        "-新",
        "（华侨城）",
        " ",
        "+",
        "plus",
    ]:
        s = s.replace(x.lower(), "")
    s = s.replace("yoyo", "").replace("soho", "").replace("mall", "").replace("plaza", "")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", s)


def to_num(x):
    try:
        return float(x) if x not in ("", None) else 0.0
    except ValueError:
        return 0.0


def main():
    base = list(csv.DictReader(Path("data/staging/base_table.csv").open(encoding="utf-8-sig", newline="")))
    base_names = [
        (r.get("点位ID", ""), r.get("门店名称", ""), norm(r.get("门店名称", "")))
        for r in base
        if r.get("点位ID") and norm(r.get("门店名称", ""))
    ]

    path = next(Path("data/raw").glob("store-month*.xlsx"))
    with zipfile.ZipFile(path) as z:
        sheet_name, target = workbook_sheets(z)[0]
        rows = read_sheet(z, target)
    headers = rows[0]
    data = rows[1:]

    stores = sorted(set(r[1] for r in data if len(r) > 1 and r[1] not in EXCLUDE_STORES))
    months = [r[2] for r in data if len(r) > 2 and re.match(r"\d{4}-\d{2}", r[2] or "")]
    nonzero = [r for r in data if len(r) > 4 and to_num(r[4]) > 0]

    matched = []
    unmatched = []
    for store in stores:
        store_norm = norm(store)
        direct = [
            b
            for b in base_names
            if b[2] and (b[2] == store_norm or b[2] in store_norm or store_norm in b[2])
        ]
        if direct:
            matched.append((store, direct[0][0], direct[0][1], "direct"))
            continue
        scored = sorted(
            ((SequenceMatcher(None, store_norm, b[2]).ratio(), b) for b in base_names if b[2]),
            key=lambda x: x[0],
            reverse=True,
        )
        best = scored[0]
        if best[0] >= 0.62:
            matched.append((store, best[1][0], best[1][1], f"fuzzy {best[0]:.2f}"))
        else:
            unmatched.append((store, best[0], best[1][0], best[1][1], store_norm, best[1][2]))

    print(f"file={path}")
    print(f"sheet={sheet_name}")
    print(f"rows={len(data)} cols={len(headers)}")
    print(f"month_range={min(months)}..{max(months)} distinct_months={len(set(months))}")
    print(f"hanson_stores={len(stores)} nonzero_rows={len(nonzero)}")
    print(f"base_names={len(base_names)} matched={len(matched)} unmatched={len(unmatched)}")
    print("\nheaders:")
    for i, h in enumerate(headers):
        print(f"{i}: {h}")
    print("\nmatched:")
    for item in matched:
        print(item)
    print("\nunmatched:")
    for item in unmatched:
        print(item)


if __name__ == "__main__":
    main()

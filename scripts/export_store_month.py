import csv
import re
import zipfile
from difflib import SequenceMatcher
from pathlib import Path

from scripts.inspect_xlsx_stdlib import read_sheet, workbook_sheets


RAW_OUT = Path("data/staging/ops_monthly_raw.csv")
MAP_OUT = Path("data/staging/store_month_mapping_review.csv")

EXCLUDE_STORES = {
    "",
    "新店模型",
    "上海支持中心",
    "培训部（上海分公司）",
    "培训部（华东分公司）",
    "lann store",
}


def norm_keep_city(s):
    s = (s or "").lower()
    for x in ["lann", "蘭", "籣", "店", "-新", "（华侨城）", " ", "+", "plus"]:
        s = s.replace(x.lower(), "")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", s)


def norm_drop_city(s):
    s = norm_keep_city(s)
    for x in ["上海", "杭州", "成都", "武汉", "苏州", "温州", "宁波", "深圳", "贵阳", "昆明"]:
        s = s.replace(x, "")
    s = s.replace("yoyo", "").replace("soho", "").replace("mall", "").replace("plaza", "")
    return s


def to_num(x):
    try:
        return float(x) if x not in ("", None) else 0.0
    except ValueError:
        return 0.0


def load_store_month():
    path = next(Path("data/raw").glob("store-month*.xlsx"))
    with zipfile.ZipFile(path) as z:
        _, target = workbook_sheets(z)[0]
        return read_sheet(z, target)


def write_raw(rows):
    headers = rows[0]
    data = rows[1:]
    keep = [
        "门店ID",
        "门店名称",
        "数据年月",
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
    idx = [headers.index(h) for h in keep]
    RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
    with RAW_OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(keep)
        for row in data:
            if len(row) < len(headers):
                row = row + [""] * (len(headers) - len(row))
            w.writerow([row[i] for i in idx])


def build_mapping(rows):
    base = list(csv.DictReader(Path("data/staging/base_table.csv").open(encoding="utf-8-sig", newline="")))
    base_names = [
        {
            "点位ID": r.get("点位ID", ""),
            "门店名称": r.get("门店名称", ""),
            "城市": r.get("城市", ""),
            "门店状态": r.get("门店状态", ""),
            "keep": norm_keep_city(r.get("门店名称", "")),
            "drop": norm_drop_city(r.get("门店名称", "")),
        }
        for r in base
        if r.get("点位ID") and r.get("门店名称")
    ]

    data = rows[1:]
    by_store = {}
    for row in data:
        if len(row) < 5:
            continue
        name = row[1]
        if name in EXCLUDE_STORES:
            continue
        rec = by_store.setdefault(name, {"months": set(), "nonzero": 0, "revenue": 0.0, "store_id": row[0]})
        rec["months"].add(row[2])
        rev = to_num(row[4])
        rec["revenue"] += rev
        if rev > 0:
            rec["nonzero"] += 1

    out = []
    for store, stat in sorted(by_store.items()):
        keep = norm_keep_city(store)
        drop = norm_drop_city(store)
        candidates = []

        exact_keep = [b for b in base_names if b["keep"] == keep]
        if len(exact_keep) == 1:
            b = exact_keep[0]
            status = "自动匹配-高置信"
            score = 1.0
            reason = "完整名称规范化后唯一相等"
        else:
            exact_drop = [b for b in base_names if b["drop"] == drop and drop]
            if len(exact_drop) == 1:
                b = exact_drop[0]
                status = "自动匹配-中置信"
                score = 0.9
                reason = "去城市/品牌后唯一相等"
            else:
                scored = sorted(
                    (
                        (SequenceMatcher(None, drop, b["drop"]).ratio(), b)
                        for b in base_names
                        if b["drop"]
                    ),
                    key=lambda x: x[0],
                    reverse=True,
                )
                score, b = scored[0]
                # Short/generic names need review even when the best score looks high.
                if score >= 0.76 and len(drop) >= 4:
                    status = "候选匹配-需确认"
                    reason = "模糊匹配分数较高但非唯一规则"
                else:
                    status = "未匹配-需确认"
                    reason = "无法可靠匹配到底表门店"
        out.append(
            [
                store,
                stat["store_id"],
                min(stat["months"]),
                max(stat["months"]),
                len(stat["months"]),
                stat["nonzero"],
                round(stat["revenue"], 2),
                b["点位ID"],
                b["门店名称"],
                b["城市"],
                b["门店状态"],
                status,
                round(score, 3),
                reason,
            ]
        )

    with MAP_OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "Hanson门店名称",
                "Hanson门店ID",
                "最早月份",
                "最晚月份",
                "月份数",
                "有收入月份数",
                "累计实际收入",
                "候选点位ID",
                "候选底表门店名称",
                "候选城市",
                "候选门店状态",
                "匹配状态",
                "匹配分数",
                "匹配说明",
            ]
        )
        w.writerows(out)
    return out


def main():
    rows = load_store_month()
    write_raw(rows)
    mapping = build_mapping(rows)
    from collections import Counter

    print(f"wrote {RAW_OUT}")
    print(f"wrote {MAP_OUT}")
    print(f"mapping rows={len(mapping)}")
    print(Counter(r[11] for r in mapping))


if __name__ == "__main__":
    main()

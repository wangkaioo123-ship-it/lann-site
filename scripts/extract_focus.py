"""
聚焦版抽取：对 2023 年后开业、有测算的 46 张表，
只扫"营收页 + 租金页"两个标签，加严标签与数值过滤，抽 月营收 / 月租金。

输出 data/staging/focus_forecast.csv（含置信标记），抽不准的留给后续兜底。
运行：python -m scripts.extract_focus
"""

import csv

from config import settings
from services import feishu_client, feishu_oauth
from scripts.sample_forecasts import resolve_to_sheet_token
from scripts.extract_forecasts import parse_number, col_letter
from scripts.focus_post2023 import year_of

# 营收页 / 租金页 的标签关键词（按优先级）
REVENUE_TAB_KW = ["运营测算", "新店测算", "新店模型", "单店模型", "业绩预算"]
RENT_TAB_KW = ["租赁商务", "商务条件"]
OVERVIEW_TAB_KW = ["项目概况", "项目总览", "店铺概况", "店铺信息", "汇总"]

# 月营收：标签要像营收、排除比率类、数值要够大
REV_POS = ["月营收", "月营业额", "月业绩", "营业额", "月收入", "营收"]
REV_NEG = ["比重", "占比", "基数", "社保", "年", "日", "坪效"]
REV_RANGE = (30000, 5_000_000)

# 月租金：标签像租金、排除单价/宿舍/提成等、数值像月总额
RENT_POS = ["房租", "月租金", "租金"]
RENT_NEG = ["单价", "每日", "每平", "㎡", "平米", "宿舍", "提成", "中介", "支付", "年租", "押金", "占比"]
RENT_RANGE = (5000, 1_000_000)


def pick_tabs(sheets):
    """从所有标签里挑出营收页、租金页（找不到就用概况页兜底）。"""
    def find(kws):
        for kw in kws:
            for s in sheets:
                if kw in s.get("title", ""):
                    return s
        return None
    rev = find(REVENUE_TAB_KW) or find(OVERVIEW_TAB_KW)
    rent = find(RENT_TAB_KW) or find(OVERVIEW_TAB_KW)
    tabs = []
    for t in (rev, rent):
        if t and t not in tabs:
            tabs.append(t)
    return tabs


def scan(grid, pos_kw, neg_kw, lo, hi):
    """在网格里找候选：标签含 pos 不含 neg，相邻值落在 [lo,hi]。返回去重后的值列表。"""
    vals = []
    for i, row in enumerate(grid):
        for j, cell in enumerate(row):
            if not cell:
                continue
            text = str(cell)
            if not any(k in text for k in pos_kw):
                continue
            if any(k in text for k in neg_kw):
                continue
            right = row[j + 1] if j + 1 < len(row) else None
            down = grid[i + 1][j] if i + 1 < len(grid) and j < len(grid[i + 1]) else None
            for cand in (right, down):
                n = parse_number(cand)
                if n is not None and lo <= n <= hi:
                    vals.append(round(n, 2))
                    break
    # 去重保序
    seen, out = set(), []
    for v in vals:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def main():
    token = feishu_oauth.get_valid_user_token()
    path = settings.ROOT_DIR / "data" / "staging" / "base_table.csv"
    with path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    sub = [r for r in rows
           if (year_of(r.get("合同开业日期", "")) or 0) >= 2023 and r.get("有无测算") == "有"]

    out_rows = []
    for idx, r in enumerate(sub, 1):
        name = r["门店名称"]
        rev_vals, rent_vals, note = [], [], ""
        try:
            st = resolve_to_sheet_token(r["测算表链接"], token)
            if not st:
                note = "非电子表格"
            else:
                meta = feishu_client.get_spreadsheet_meta(st, token)
                for tab in pick_tabs(meta.get("sheets", [])):
                    grid = feishu_client.read_sheet_range(st, f"{tab['sheet_id']}!A1:N80", token)
                    rev_vals += scan(grid, REV_POS, REV_NEG, *REV_RANGE)
                    rent_vals += scan(grid, RENT_POS, RENT_NEG, *RENT_RANGE)
                rev_vals = list(dict.fromkeys(rev_vals))
                rent_vals = list(dict.fromkeys(rent_vals))
        except Exception as e:
            note = str(e)[:40]

        def conf(vals):
            if len(vals) == 1:
                return "高"
            if len(vals) >= 2:
                return "多候选"
            return "无"

        out_rows.append({
            "点位ID": r["点位ID"], "门店名称": name,
            "月营收_候选": rev_vals, "月营收置信": conf(rev_vals),
            "月租金_候选": rent_vals, "月租金置信": conf(rent_vals),
            "备注": note,
        })
        print(f"  [{idx}/{len(sub)}] {name}: 营收{rev_vals}({conf(rev_vals)}) 租金{rent_vals}({conf(rent_vals)}) {note}")

    out = settings.ROOT_DIR / "data" / "staging" / "focus_forecast.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    # 汇总
    rev_ok = sum(1 for x in out_rows if x["月营收置信"] == "高")
    rent_ok = sum(1 for x in out_rows if x["月租金置信"] == "高")
    print(f"\n=== 汇总（{len(out_rows)} 家）===")
    print(f"  月营收单一候选(高置信): {rev_ok}   多候选: {sum(1 for x in out_rows if x['月营收置信']=='多候选')}   无: {sum(1 for x in out_rows if x['月营收置信']=='无')}")
    print(f"  月租金单一候选(高置信): {rent_ok}   多候选: {sum(1 for x in out_rows if x['月租金置信']=='多候选')}   无: {sum(1 for x in out_rows if x['月租金置信']=='无')}")
    print(f"  明细：{out}")


if __name__ == "__main__":
    main()

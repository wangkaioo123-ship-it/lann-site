"""
第二段抽取引擎：标签搜索式从测算表抓核心数。
逻辑：不依赖"第几个格子"，而是全表搜关键词标签，取其右侧/下方的值。
对 29 种版式免疫。抓不准的会标成候选，交给 AI 兜底。

目标指标：月营收(测算)、月租金 为核心；回本/毛利率/坪效/投资 顺手抓。

运行：python -m scripts.extract_forecasts [N]   N=只跑前几张(验证用)，省略=全部
"""

import csv
import json
import re
import sys

from config import settings
from services import feishu_client, feishu_oauth
from scripts.sample_forecasts import resolve_to_sheet_token

# 指标 → 标签关键词（一个格子文本含这些词，就视为该指标的候选标签）
METRIC_KEYWORDS = {
    "月营收": ["月营收", "月营业额", "月均营", "月业绩", "月销售", "月收入", "营业额", "营收"],
    "月租金": ["月租金", "房租", "租金"],
    "回本周期": ["回本", "回收期", "投资回收"],
    "毛利率": ["毛利率", "净利率"],
    "坪效": ["坪效"],
    "投资额": ["总投资", "投资额", "总投入", "投资预算", "投入概算"],
}

# 只读这些名字里含关键词的标签页（跳过 城市参数/筹备物料/明细/工程清单 等无关页）
TAB_KEYWORDS = ["概况", "总览", "测算", "模型", "商务", "业绩", "租赁", "运营", "投入", "项目", "汇总"]


def parse_number(text):
    """从一段文本里抽出第一个数字（处理千分位、元、%等）。抽不到返回 None。"""
    if text is None:
        return None
    s = str(text).replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def col_letter(idx):
    """0-based 列号 → A1 列字母。"""
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def scan_tab(grid, tab_title):
    """在一个标签页的二维网格里，搜所有指标的候选 (标签, 值, 位置)。"""
    found = {m: [] for m in METRIC_KEYWORDS}
    for i, row in enumerate(grid):
        for j, cell in enumerate(row):
            if cell in (None, ""):
                continue
            text = str(cell)
            for metric, kws in METRIC_KEYWORDS.items():
                if any(kw in text for kw in kws):
                    # 取右侧、下方的相邻值，挑第一个能解析成数字的
                    right = row[j + 1] if j + 1 < len(row) else None
                    down = grid[i + 1][j] if i + 1 < len(grid) and j < len(grid[i + 1]) else None
                    val = None
                    for cand in (right, down):
                        n = parse_number(cand)
                        if n is not None:
                            val = n
                            break
                    found[metric].append({
                        "label": text[:30],
                        "value": val,
                        "raw_right": str(right)[:20] if right else "",
                        "where": f"{tab_title}!{col_letter(j)}{i+1}",
                    })
    return found


def extract_one(link, token):
    """抽一张测算表，返回各指标的候选列表。"""
    sheet_token = resolve_to_sheet_token(link, token)
    if not sheet_token:
        return None
    meta = feishu_client.get_spreadsheet_meta(sheet_token, token)
    result = {m: [] for m in METRIC_KEYWORDS}
    for s in meta.get("sheets", []):
        title = s.get("title", "")
        if not any(kw in title for kw in TAB_KEYWORDS):
            continue
        sid = s.get("sheet_id")
        try:
            grid = feishu_client.read_sheet_range(sheet_token, f"{sid}!A1:N80", token)
        except RuntimeError:
            continue
        tab_found = scan_tab(grid, title)
        for m in result:
            result[m].extend(tab_found[m])
    return result


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    token = feishu_oauth.get_valid_user_token()

    path = settings.ROOT_DIR / "data" / "staging" / "base_table.csv"
    with path.open(encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r.get("测算表链接")]
    if limit:
        rows = rows[:limit]

    print(f"抽取 {len(rows)} 张测算表 ...\n")
    all_results = {}
    for idx, r in enumerate(rows, 1):
        name = r["门店名称"]
        try:
            res = extract_one(r["测算表链接"], token)
        except RuntimeError as e:
            print(f"  [{idx}/{len(rows)}] {name} 失败：{str(e)[:50]}")
            continue
        if res is None:
            continue
        all_results[name] = {"点位ID": r.get("点位ID", ""), "candidates": res}
        # 简报：每个核心指标取"有数值的第一个候选"作为初猜
        rev = next((c["value"] for c in res["月营收"] if c["value"]), None)
        rent = next((c["value"] for c in res["月租金"] if c["value"]), None)
        print(f"  [{idx}/{len(rows)}] {name}: 月营收候选={len(res['月营收'])}(初猜{rev}) 月租金候选={len(res['月租金'])}(初猜{rent})")

    out = settings.ROOT_DIR / "data" / "staging" / "forecast_candidates.json"
    out.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n候选明细已存：{out}")


if __name__ == "__main__":
    main()

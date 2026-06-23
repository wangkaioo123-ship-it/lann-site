"""
第二段·模板抽样：抽几张不同时期/不同店的测算表，看是否同一套模板，
并定位"租金""测算营收""回本"等关键数据在哪个标签页。

只读，零风险。运行：python -m scripts.sample_forecasts
"""

import csv
import re

from config import settings
from services import feishu_client, feishu_oauth


def parse_link(link: str):
    """把测算表链接解析成 ('sheet'|'wiki', token)。"""
    m = re.search(r"/sheets/([A-Za-z0-9]+)", link)
    if m:
        return "sheet", m.group(1)
    m = re.search(r"/wiki/([A-Za-z0-9]+)", link)
    if m:
        return "wiki", m.group(1)
    return "unknown", ""


def resolve_to_sheet_token(link: str, token: str):
    """把链接统一解析为可读的电子表格 token。"""
    kind, tok = parse_link(link)
    if kind == "sheet":
        return tok
    if kind == "wiki":
        node = feishu_client.get_wiki_node(tok, token)
        if node.get("obj_type") == "sheet":
            return node.get("obj_token")
        return None  # wiki 节点不是电子表格
    return None


def load_samples(n=6):
    """从底表里挑 n 个有测算链接的点位（尽量跨不同位置）。"""
    path = settings.ROOT_DIR / "data" / "staging" / "base_table.csv"
    with path.open(encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r.get("测算表链接")]
    if len(rows) <= n:
        return rows
    step = len(rows) // n
    return [rows[i * step] for i in range(n)]


def main():
    token = feishu_oauth.get_valid_user_token()
    samples = load_samples(6)
    print(f"抽样 {len(samples)} 张测算表，对比模板：\n")

    tab_signatures = []
    for r in samples:
        name = r["门店名称"]
        link = r["测算表链接"]
        try:
            sheet_token = resolve_to_sheet_token(link, token)
            if not sheet_token:
                print(f"[{name}] 链接非电子表格，跳过：{link}")
                continue
            meta = feishu_client.get_spreadsheet_meta(sheet_token, token)
            tabs = [s.get("title") for s in meta.get("sheets", [])]
            tab_signatures.append(tuple(tabs))
            print(f"[{name}] {len(tabs)} 标签：{tabs}")
        except RuntimeError as e:
            print(f"[{name}] 读取失败：{e}")

    # 模板一致性判断
    print("\n=== 模板一致性 ===")
    uniq = set(tab_signatures)
    print(f"抽样中出现了 {len(uniq)} 种不同的标签结构")
    if len(uniq) == 1:
        print("→ 模板高度一致，可写一个解析器批量抽。")
    else:
        print("→ 模板不完全一致，需要分组或更鲁棒的定位方式。各结构如下：")
        for sig in uniq:
            print(f"   {list(sig)}")


if __name__ == "__main__":
    main()

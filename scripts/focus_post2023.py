"""
按开业时间(2023 年后)圈定试点，并验证这批的测算表模板是否统一。
若统一 → 可写精准解析器自动抽，不必 AI 逐张读。

只读。运行：python -m scripts.focus_post2023
"""

import csv
from collections import Counter

from config import settings
from services import feishu_client, feishu_oauth
from scripts.sample_forecasts import resolve_to_sheet_token


def year_of(date_str):
    """'2024-05-01' → 2024；空或异常返回 None。"""
    if not date_str or len(date_str) < 4:
        return None
    try:
        return int(date_str[:4])
    except ValueError:
        return None


def main():
    token = feishu_oauth.get_valid_user_token()
    path = settings.ROOT_DIR / "data" / "staging" / "base_table.csv"
    with path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    # 2023 年(含)以后开业、且有测算
    sub = []
    for r in rows:
        y = year_of(r.get("合同开业日期", ""))
        if y and y >= 2023 and r.get("有无测算") == "有":
            sub.append(r)

    print(f"2023 年后开业 且 有测算：{len(sub)} 家\n")
    print(f"{'点位ID':<8}{'门店名称':<22}{'开业日':<12}{'状态':<8}{'属性'}")
    for r in sub:
        print(f"  {r['点位ID']:<8}{r['门店名称']:<22}{r['合同开业日期']:<12}{r['门店状态']:<8}{r['门店属性']}")

    # 验证模板一致性
    print("\n=== 验证这批的测算表模板 ===")
    sigs = Counter()
    fail = []
    for r in sub:
        try:
            st = resolve_to_sheet_token(r["测算表链接"], token)
            if not st:
                fail.append((r["门店名称"], "非电子表格"))
                continue
            meta = feishu_client.get_spreadsheet_meta(st, token)
            tabs = tuple(s.get("title") for s in meta.get("sheets", []))
            sigs[tabs] += 1
        except Exception as e:
            fail.append((r["门店名称"], str(e)[:40]))

    print(f"\n能读 {sum(sigs.values())} 张，共 {len(sigs)} 种模板结构：")
    for sig, cnt in sigs.most_common():
        print(f"  [{cnt} 张] {list(sig)[:6]}{' ...' if len(sig) > 6 else ''}")
    if fail:
        print(f"\n读取失败 {len(fail)} 张：")
        for name, why in fail:
            print(f"  {name}: {why}")


if __name__ == "__main__":
    main()

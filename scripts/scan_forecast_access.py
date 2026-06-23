"""
扫描全部 73 张测算表：统计
  1) 王凯身份现在能读几张、哪几张读不了（需别人授权）
  2) 一共有几种模板结构、各占多少（决定抽取策略）

只读。运行：python -m scripts.scan_forecast_access
"""

import csv
from collections import Counter

from config import settings
from services import feishu_client, feishu_oauth
from scripts.sample_forecasts import resolve_to_sheet_token


def main():
    token = feishu_oauth.get_valid_user_token()
    path = settings.ROOT_DIR / "data" / "staging" / "base_table.csv"
    with path.open(encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r.get("测算表链接")]

    print(f"共 {len(rows)} 个点位有测算链接，逐张检查可读性与模板...\n")

    ok, no_perm, other_fail = [], [], []
    signatures = Counter()
    for r in rows:
        name = r["门店名称"]
        link = r["测算表链接"]
        try:
            sheet_token = resolve_to_sheet_token(link, token)
            if not sheet_token:
                other_fail.append((name, "非电子表格链接"))
                continue
            meta = feishu_client.get_spreadsheet_meta(sheet_token, token)
            tabs = tuple(s.get("title") for s in meta.get("sheets", []))
            signatures[tabs] += 1
            ok.append(name)
        except RuntimeError as e:
            msg = str(e)
            if "1310213" in msg or "No view permission" in msg:
                no_perm.append(name)
            else:
                other_fail.append((name, msg[:60]))

    print("=== 可读性 ===")
    print(f"  ✅ 能读：{len(ok)} 张")
    print(f"  🔒 无权限（需 owner 授权）：{len(no_perm)} 张")
    if no_perm:
        print("     " + "，".join(no_perm))
    print(f"  ⚠️ 其它失败：{len(other_fail)} 张")
    for name, why in other_fail:
        print(f"     {name}: {why}")

    print(f"\n=== 模板结构分布（仅能读的 {len(ok)} 张）===")
    print(f"  共 {len(signatures)} 种不同结构")
    for sig, cnt in signatures.most_common():
        head = list(sig)[:5]
        print(f"  [{cnt} 张] {head}{' ...' if len(sig) > 5 else ''}")


if __name__ == "__main__":
    main()

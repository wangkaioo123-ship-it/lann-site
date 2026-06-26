"""
加盟商意见记录表聚合洞察：按类型/进度/来源分布，并按类型归组列出所有反馈问题。
运行：python -m scripts.feedback_summary
"""

from collections import Counter
from datetime import datetime, timezone, timedelta

from config import settings
from services import feishu_client

FEEDBACK_TABLE_ID = "tbl85UP9FcqIq0ex"
CN = timezone(timedelta(hours=8))


def text_of(v):
    if v is None:
        return ""
    if isinstance(v, list):
        return "".join(s.get("text", "") if isinstance(s, dict) else str(s) for s in v)
    return str(v)


def ymd(v):
    try:
        return datetime.fromtimestamp(int(v) / 1000, CN).strftime("%Y-%m")
    except Exception:
        return "?"


def main():
    app_token = settings.require("LEASE_TABLE_APP_TOKEN")
    token = feishu_client.get_tenant_access_token()
    recs = feishu_client.list_all_records(app_token, FEEDBACK_TABLE_ID, token,
                                          max_total=1000, text_as_array=True)

    def g(rec, name):
        return text_of(rec.get("fields", {}).get(name)).strip()

    months = [ymd(rec["fields"].get("反馈时间")) for rec in recs if rec["fields"].get("反馈时间")]
    print(f"共 {len(recs)} 条，时间范围 {min(months)} ~ {max(months)}\n")

    print("=== 反馈类型分布 ===")
    for k, c in Counter(g(r, "反馈类型") for r in recs).most_common():
        print(f"  {k or '(空)'}: {c}")
    print("\n=== 处理进度分布 ===")
    for k, c in Counter(g(r, "处理进度") for r in recs).most_common():
        print(f"  {k or '(空)'}: {c}")
    print("\n=== 反馈来源分布 ===")
    for k, c in Counter(g(r, "反馈来源") for r in recs).most_common():
        print(f"  {k or '(空)'}: {c}")

    print("\n=== 按类型归组的反馈问题（[进度] 问题）===")
    by_type = {}
    for r in recs:
        by_type.setdefault(g(r, "反馈类型") or "(空)", []).append(r)
    for typ, rs in sorted(by_type.items(), key=lambda x: -len(x[1])):
        print(f"\n--- {typ}（{len(rs)} 条）---")
        for r in rs:
            q = g(r, "反馈问题").replace("\n", " ")[:80]
            prog = g(r, "处理进度")
            print(f"  [{prog}] {q}")


if __name__ == "__main__":
    main()

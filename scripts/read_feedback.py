"""
读取加盟商意见记录表（tbl85UP9FcqIq0ex），打印字段结构与全部记录，
供洞察当前加盟商反馈、提炼 KR。

运行：python -m scripts.read_feedback
"""

from config import settings
from services import feishu_client

FEEDBACK_TABLE_ID = "tbl85UP9FcqIq0ex"


def text_of(v):
    if v is None:
        return ""
    if isinstance(v, list):
        return "".join(s.get("text", "") if isinstance(s, dict) else str(s) for s in v)
    return str(v)


def main():
    app_token = settings.require("LEASE_TABLE_APP_TOKEN")
    token = feishu_client.get_tenant_access_token()

    fields = feishu_client.list_table_fields(app_token, FEEDBACK_TABLE_ID, token)
    print(f"=== 字段（{len(fields)} 个）===")
    for f in fields:
        print(f"  - {f.get('field_name')}  (type={f.get('type')})")

    records = feishu_client.list_all_records(app_token, FEEDBACK_TABLE_ID, token,
                                             max_total=1000, text_as_array=True)
    print(f"\n=== 共 {len(records)} 条记录 ===")
    for i, rec in enumerate(records, 1):
        fields_data = rec.get("fields", {})
        parts = []
        for k, v in fields_data.items():
            txt = text_of(v).strip()
            if txt:
                parts.append(f"{k}={txt[:100]}")
        print(f"[{i}] " + " | ".join(parts))


if __name__ == "__main__":
    main()

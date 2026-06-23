"""
定向探查：挖出 4 个"软字段"的真实形态（链接 or 内联文字），
并统计全表记录数、各关键字段的填充率（覆盖多少项目）。

运行：python -m scripts.inspect_fields
"""

from config import settings
from services import feishu_client

# 重点要看清形态的软字段
FOCUS_FIELDS = [
    "单店测算",
    "租赁合同附件",
    "加盟合同附件",
    "下一年租金",
    "额外争取的租赁商务条件备注",
]


def describe_value(value):
    """把一个字段值描述成：是否含链接、文本预览。"""
    # text_field_as_array=true 时，文本字段是分段列表
    if isinstance(value, list):
        has_link = False
        texts = []
        links = []
        for seg in value:
            if isinstance(seg, dict):
                if seg.get("link"):
                    has_link = True
                    links.append(seg.get("link"))
                if seg.get("text"):
                    texts.append(seg.get("text"))
        joined = "".join(texts)
        tag = "【含链接】" if has_link else "【纯文本】"
        out = f"{tag} 文本='{joined[:100]}'"
        if links:
            out += f"  链接={links[:2]}"
        return out
    return f"【非分段】{str(value)[:120]}"


def main():
    app_token = settings.require("LEASE_TABLE_APP_TOKEN")
    table_id = settings.require("LEASE_TABLE_ID")

    token = feishu_client.get_tenant_access_token()
    print("正在分页读取全部记录（文本字段按分段返回，以识别链接）...\n")
    records = feishu_client.list_all_records(
        app_token, table_id, token, max_total=1000, text_as_array=True
    )
    total = len(records)
    print(f"=== 全表共 {total} 条记录（项目/门店）===\n")

    # 1) 关键字段填充率统计
    print("=== 关键字段填充率（多少项目有该数据）===")
    count_fields = FOCUS_FIELDS + ["门店属性", "门店状态"]
    fill = {name: 0 for name in count_fields}
    for rec in records:
        fields = rec.get("fields", {})
        for name in count_fields:
            v = fields.get(name)
            if v not in (None, "", [], 0):
                fill[name] += 1
    for name in count_fields:
        print(f"  {name}: {fill[name]} / {total}")

    # 2) 软字段真实形态：每个字段挑前 3 个有值的样本，看是链接还是文字
    for fname in FOCUS_FIELDS:
        print(f"\n=== 字段「{fname}」样本（前 3 个有值的）===")
        shown = 0
        for rec in records:
            v = rec.get("fields", {}).get(fname)
            if v in (None, "", []):
                continue
            store = rec.get("fields", {}).get("门店名称", "?")
            if isinstance(store, list):
                store = "".join(s.get("text", "") for s in store if isinstance(s, dict))
            print(f"  [{store}] {describe_value(v)}")
            shown += 1
            if shown >= 3:
                break
        if shown == 0:
            print("  （全表无任何记录填了此字段）")


if __name__ == "__main__":
    main()

"""
只读探查脚本：把"租赁信息表"的真实结构打印出来。
目的：在写任何抽取逻辑之前，先搞清楚立项/合同数据到底是什么形态
（结构化字段 / 关联记录 / 附件 / 文档链接），从而决定最省力的清洗路径。

运行：python -m scripts.inspect_table
依赖 .env 中的 FEISHU_APP_ID / FEISHU_APP_SECRET / LEASE_TABLE_APP_TOKEN / LEASE_TABLE_ID
"""

from config import settings
from services import feishu_client

# 飞书多维表格字段类型码 → 人话（重点关注会影响抽取方式的几类）
FIELD_TYPE_NAMES = {
    1: "多行文本",
    2: "数字",
    3: "单选",
    4: "多选",
    5: "日期",
    7: "复选框",
    11: "人员",
    13: "电话",
    15: "超链接(可能是文档链接)",
    17: "附件(文件，如合同PDF/扫描件)",
    18: "单向关联(链接到另一张表的记录)",
    19: "查找引用",
    20: "公式",
    21: "双向关联(链接到另一张表的记录)",
    22: "地理位置",
    1001: "创建时间",
    1002: "最后更新时间",
    1003: "创建人",
    1004: "修改人",
    1005: "自动编号",
}


def main():
    app_token = settings.require("LEASE_TABLE_APP_TOKEN")
    table_id = settings.require("LEASE_TABLE_ID")

    print("正在获取飞书 token ...")
    token = feishu_client.get_tenant_access_token()
    print("token 获取成功。\n")

    # 1) 打印字段结构
    fields = feishu_client.list_table_fields(app_token, table_id, token)
    print(f"=== 租赁信息表共有 {len(fields)} 个字段 ===")
    for f in fields:
        type_code = f.get("type")
        type_name = FIELD_TYPE_NAMES.get(type_code, f"未知类型({type_code})")
        print(f"  - {f.get('field_name')}  [{type_name}]")

    # 2) 抽样几条记录，观察真实内容形态
    print("\n=== 抽样前 3 条记录（仅看结构，不展示全部内容）===")
    records = feishu_client.list_table_records(app_token, table_id, token, max_records=3)
    for i, rec in enumerate(records, 1):
        print(f"\n--- 记录 {i} (record_id={rec.get('record_id')}) ---")
        for field_name, value in rec.get("fields", {}).items():
            # 只展示值的类型与简短预览，避免刷屏和泄露大量业务数据
            preview = str(value)
            if len(preview) > 120:
                preview = preview[:120] + " ...(已截断)"
            print(f"    {field_name}: {preview}")


if __name__ == "__main__":
    main()

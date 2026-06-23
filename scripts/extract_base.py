"""
第一段抽取：把"租赁信息表"95 条记录的结构化字段，拉成一张干净底表。
只用结构化字段（不碰测算表），无需云文档权限。
输出：data/staging/base_table.csv（已 gitignore，含商务数据不进库）

运行：python -m scripts.extract_base
"""

import csv
from datetime import datetime, timezone, timedelta

from config import settings
from services import feishu_client

# 输出列  ←  飞书字段名 的映射（集中管理，便于以后换源/改名）
# 含义：见 docs/lann_site_data_design_v0.1.md 点位主数据表
COLUMN_MAP = [
    ("点位ID", "门店序号"),
    ("门店名称", "门店名称"),
    ("城市", "城市"),
    ("品牌", "品牌"),
    ("门店属性", "门店属性"),
    ("门店状态", "门店状态"),
    ("地址", "店铺/加盟地址"),
    ("签约编号", "签约编号"),
    ("交铺日期", "交铺日期"),
    ("租赁起始日", "租赁起始日"),
    ("租赁终止日", "租赁终止日"),
    ("合同开业日期", "合同开业日期"),
    ("门店面积", "门店面积"),
    ("面积计算方式", "面积计算方式"),
    ("合同装修免租期天", "合同装修免租期（天）"),
    ("实际装修免租期", "实际装修免租期"),
    ("当前年租金月", "当前年租金（月）"),
    ("物业管理费", "物业管理费"),
    ("宣传推广费", "宣传推广费"),
    ("加盟费计算方式", "加盟费计算方式"),
    ("实际加盟费金额", "实际加盟费金额"),
    ("管理费比例", "管理费比例"),
]

# 需要从时间戳(毫秒)转成日期字符串的字段
DATE_FIELDS = {"交铺日期", "租赁起始日", "租赁终止日", "合同开业日期"}

CN_TZ = timezone(timedelta(hours=8))


def text_of(value) -> str:
    """把任意字段值转成纯文本（text_field_as_array 下文本字段是分段列表）。"""
    if value is None:
        return ""
    if isinstance(value, list):
        parts = []
        for seg in value:
            if isinstance(seg, dict):
                parts.append(seg.get("text", ""))
            else:
                parts.append(str(seg))
        return "".join(parts)
    return str(value)


def to_date(value) -> str:
    """毫秒时间戳 → YYYY-MM-DD。"""
    if value in (None, "", []):
        return ""
    try:
        ts = int(value) / 1000
        return datetime.fromtimestamp(ts, CN_TZ).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return text_of(value)


def extract_forecast_link(fields: dict):
    """从"单店测算"字段里取出测算表链接（若有）。返回 (有无测算, 链接)。"""
    v = fields.get("单店测算")
    if not v:
        return "无", ""
    if isinstance(v, list):
        for seg in v:
            if isinstance(seg, dict) and seg.get("link"):
                return "有", seg.get("link")
        # 有文字但没链接
        return "有", ""
    return "有", ""


def main():
    app_token = settings.require("LEASE_TABLE_APP_TOKEN")
    table_id = settings.require("LEASE_TABLE_ID")

    token = feishu_client.get_tenant_access_token()
    print("拉取全部记录 ...")
    records = feishu_client.list_all_records(
        app_token, table_id, token, max_total=1000, text_as_array=True
    )
    print(f"共 {len(records)} 条。\n")

    out_dir = settings.ROOT_DIR / "data" / "staging"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "base_table.csv"

    headers = [col for col, _ in COLUMN_MAP] + ["有无测算", "测算表链接", "record_id"]

    n_forecast = 0
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for rec in records:
            fields = rec.get("fields", {})
            row = []
            for _, src in COLUMN_MAP:
                v = fields.get(src)
                if src in DATE_FIELDS:
                    row.append(to_date(v))
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    row.append(v)  # 数字保持原值
                else:
                    row.append(text_of(v))
            has_fc, link = extract_forecast_link(fields)
            if has_fc == "有":
                n_forecast += 1
            row += [has_fc, link, rec.get("record_id", "")]
            writer.writerow(row)

    print(f"✅ 底表已生成：{out_path}")
    print(f"   共 {len(records)} 个点位，其中 {n_forecast} 个有测算表、{len(records) - n_forecast} 个无（=当年未立项的反例）")


if __name__ == "__main__":
    main()

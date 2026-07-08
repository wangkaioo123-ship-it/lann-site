"""
从飞书租赁信息表直接导出结构化租金。

输出：data/staging/rent_extract_feishu.csv
只读飞书，不写入、不改字段。
"""

import csv
from datetime import datetime, timedelta, timezone

from config import settings
from services import feishu_client


CN_TZ = timezone(timedelta(hours=8))


def text_of(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(value)


def date_of(value) -> str:
    if value in (None, "", []):
        return ""
    try:
        return datetime.fromtimestamp(int(value) / 1000, CN_TZ).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return text_of(value)


def num_text(value) -> str:
    if value in (None, "", []):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value).is_integer():
            return str(int(value))
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text_of(value).strip()


def main():
    app_token = settings.require("LEASE_TABLE_APP_TOKEN")
    table_id = settings.require("LEASE_TABLE_ID")
    token = feishu_client.get_tenant_access_token()
    records = feishu_client.list_all_records(
        app_token, table_id, token, max_total=2000, text_as_array=True
    )

    out = settings.ROOT_DIR / "data" / "staging" / "rent_extract_feishu.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "点位ID",
        "门店名",
        "当年租金",
        "下一年租金",
        "年租金变更日",
        "含税",
        "来源文件",
        "备注",
        "状态",
        "record_id",
    ]

    rows = []
    for rec in records:
        fields = rec.get("fields", {})
        site_id = text_of(fields.get("门店序号")).strip()
        name = text_of(fields.get("门店名称")).strip()
        current_rent = num_text(fields.get("当前年租金+物业费（月）"))
        next_rent = num_text(fields.get("下一年租金"))
        change_date = date_of(fields.get("年租金变更日"))
        source = text_of(fields.get("租赁合同附件")).strip()
        note = text_of(fields.get("额外争取的租赁商务条件备注")).strip()
        status = "当年已定" if current_rent else "缺当年租金"
        rows.append(
            [
                site_id,
                name,
                current_rent,
                next_rent,
                change_date,
                "",
                source,
                note,
                status,
                rec.get("record_id", ""),
            ]
        )

    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    filled_current = sum(1 for row in rows if row[2])
    filled_next = sum(1 for row in rows if row[3])
    print(f"wrote {out}")
    print(f"records={len(rows)} current_rent={filled_current} next_rent={filled_next}")


if __name__ == "__main__":
    main()

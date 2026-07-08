import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from config import settings
from services import feishu_client


FIELD_TYPE_NAMES = {
    1: "多行文本",
    2: "数字",
    3: "单选",
    4: "多选",
    5: "日期",
    7: "复选框",
    11: "人员",
    13: "电话",
    15: "超链接",
    17: "附件",
    18: "单向关联",
    19: "查找引用",
    20: "公式",
    21: "双向关联",
    22: "地理位置",
    1001: "创建时间",
    1002: "最后更新时间",
    1003: "创建人",
    1004: "修改人",
    1005: "自动编号",
}


def text_of(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                if item.get("text"):
                    parts.append(str(item.get("text")))
                elif item.get("name"):
                    parts.append(str(item.get("name")))
                elif item.get("file_token"):
                    parts.append("[附件]")
                else:
                    parts.append(json.dumps(item, ensure_ascii=False)[:80])
            else:
                parts.append(str(item))
        return "".join(parts)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def is_filled(value) -> bool:
    if value in (None, "", [], {}):
        return False
    return True


def short(value, limit=120) -> str:
    text = text_of(value).replace("\n", " ").strip()
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def parse_source(args) -> tuple[str, str, str]:
    if args.source == "lease":
        return (
            settings.require("LEASE_TABLE_APP_TOKEN"),
            settings.require("LEASE_TABLE_ID"),
            "",
        )
    if args.source == "expansion":
        return (
            settings.require("EXPANSION_TABLE_APP_TOKEN"),
            settings.require("EXPANSION_TABLE_ID"),
            settings.EXPANSION_TABLE_VIEW_ID,
        )
    return (args.app_token, args.table_id, args.view_id or "")


def main():
    parser = argparse.ArgumentParser(description="Inspect a Feishu bitable without writing data.")
    parser.add_argument("--source", choices=["lease", "expansion", "custom"], default="expansion")
    parser.add_argument("--app-token", default="")
    parser.add_argument("--table-id", default="")
    parser.add_argument("--view-id", default="")
    parser.add_argument("--max-records", type=int, default=500)
    parser.add_argument("--sample", type=int, default=5)
    parser.add_argument("--out-prefix", default="data/staging/expansion_table")
    args = parser.parse_args()

    app_token, table_id, view_id = parse_source(args)
    if not app_token or not table_id:
        raise RuntimeError("Missing app token or table id")

    token = feishu_client.get_tenant_access_token()
    fields = feishu_client.list_table_fields(app_token, table_id, token)
    records = feishu_client.list_all_records(
        app_token, table_id, token, max_total=args.max_records, text_as_array=True
    )

    prefix = settings.ROOT_DIR / args.out_prefix
    prefix.parent.mkdir(parents=True, exist_ok=True)
    fields_out = Path(str(prefix) + "_fields.csv")
    fill_out = Path(str(prefix) + "_fill.csv")
    sample_out = Path(str(prefix) + "_sample.csv")

    field_names = [field.get("field_name", "") for field in fields]
    field_type_by_name = {
        field.get("field_name", ""): FIELD_TYPE_NAMES.get(field.get("type"), str(field.get("type")))
        for field in fields
    }

    with fields_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["field_name", "type_code", "type_name"])
        for field in fields:
            writer.writerow(
                [
                    field.get("field_name", ""),
                    field.get("type", ""),
                    FIELD_TYPE_NAMES.get(field.get("type"), str(field.get("type"))),
                ]
            )

    fill_counter = Counter()
    for rec in records:
        rec_fields = rec.get("fields", {})
        for name in field_names:
            if is_filled(rec_fields.get(name)):
                fill_counter[name] += 1

    with fill_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["field_name", "type_name", "filled", "total", "fill_rate"])
        for name in field_names:
            filled = fill_counter[name]
            total = len(records)
            writer.writerow(
                [
                    name,
                    field_type_by_name.get(name, ""),
                    filled,
                    total,
                    f"{filled / total:.4f}" if total else "",
                ]
            )

    sample_rows = []
    for rec in records[: args.sample]:
        row = {"record_id": rec.get("record_id", "")}
        rec_fields = rec.get("fields", {})
        for name in field_names:
            row[name] = short(rec_fields.get(name))
        sample_rows.append(row)

    with sample_out.open("w", encoding="utf-8-sig", newline="") as f:
        headers = ["record_id"] + field_names
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(sample_rows)

    print(f"source={args.source} app_token={app_token[:4]}*** table_id={table_id}")
    if view_id:
        print(f"view_id={view_id}")
    print(f"fields={len(fields)} records_read={len(records)}")
    print(f"wrote {fields_out}")
    print(f"wrote {fill_out}")
    print(f"wrote {sample_out}")
    print("\nfield fill top:")
    for name, filled in fill_counter.most_common(20):
        print(f"{name} [{field_type_by_name.get(name, '')}] {filled}/{len(records)}")


if __name__ == "__main__":
    main()

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import settings
from services import feishu_client


CN_TZ = timezone(timedelta(hours=8))


FIELDS = [
    "项目名称",
    "城市",
    "当前阶段",
    "开店性质",
    "商场体系",
    "商圈等级",
    "商场评级",
    "物业形态",
    "预期房量规模",
    "预计业务组合",
    "预计门店类型",
    "预期月营业额",
    "初步判断",
    "立项信息表",
    "选址调研报告",
    "租金（元/㎡/天）",
    "免租期（月）",
    "装修补贴（元）",
    "合同年限（年）",
    "商务条件评级",
    "预计开业时间",
    "开业时间",
    "商场开业时间",
    "商场地点",
    "项目编号",
    "更新时间",
]


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
        return "、".join(part for part in parts if part)
    if isinstance(value, dict):
        if value.get("full_address"):
            return str(value.get("full_address"))
        if value.get("address"):
            return str(value.get("address"))
        return json.dumps(value, ensure_ascii=False)
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
    try:
        n = float(value)
    except (TypeError, ValueError):
        return text_of(value)
    if n.is_integer():
        return str(int(n))
    return f"{n:.6f}".rstrip("0").rstrip(".")


def has_value(row: dict, name: str) -> bool:
    return row.get(name) not in ("", None)


def completeness(row: dict) -> tuple[str, str]:
    required = ["项目名称", "城市", "当前阶段", "开店性质"]
    site_context = ["商圈等级", "商场评级", "物业形态", "商场地点"]
    business = ["预期月营业额", "租金（元/㎡/天）", "预期房量规模", "预计门店类型"]
    docs = ["立项信息表", "选址调研报告"]

    missing = []
    for name in required:
        if not has_value(row, name):
            missing.append(name)

    context_count = sum(1 for name in site_context if has_value(row, name))
    business_count = sum(1 for name in business if has_value(row, name))
    docs_count = sum(1 for name in docs if has_value(row, name))

    if missing:
        status = "缺基础字段"
    elif context_count >= 2 and business_count >= 2:
        status = "可初步对标"
    elif context_count >= 1 or business_count >= 1 or docs_count >= 1:
        status = "资料部分可用"
    else:
        status = "仅基础信息"

    detail = []
    if missing:
        detail.append("缺：" + "、".join(missing))
    detail.append(f"场地字段{context_count}/4")
    detail.append(f"商务/测算字段{business_count}/4")
    detail.append(f"资料链接{docs_count}/2")
    return status, "；".join(detail)


def normalize_record(rec: dict) -> dict:
    fields = rec.get("fields", {})
    row = {"record_id": rec.get("record_id", "")}
    for name in FIELDS:
        value = fields.get(name)
        if name in {"开业时间", "商场开业时间", "更新时间"}:
            row[name] = date_of(value)
        elif name in {"预期月营业额", "租金（元/㎡/天）", "免租期（月）", "装修补贴（元）", "合同年限（年）"}:
            row[name] = num_text(value)
        else:
            row[name] = text_of(value).replace("\n", " ").strip()
    status, detail = completeness(row)
    row["资料完整度"] = status
    row["缺口说明"] = detail
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-records", type=int, default=1000)
    parser.add_argument("--out", default="data/staging/expansion_candidates.csv")
    args = parser.parse_args()

    token = feishu_client.get_tenant_access_token()
    records = feishu_client.list_all_records(
        settings.require("EXPANSION_TABLE_APP_TOKEN"),
        settings.require("EXPANSION_TABLE_ID"),
        token,
        max_total=args.max_records,
        text_as_array=True,
    )
    rows = [normalize_record(rec) for rec in records]
    rows.sort(key=lambda r: (r["资料完整度"], r["城市"], r["项目名称"]))

    out = settings.ROOT_DIR / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    headers = ["record_id"] + FIELDS + ["资料完整度", "缺口说明"]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    counts = {}
    for row in rows:
        counts[row["资料完整度"]] = counts.get(row["资料完整度"], 0) + 1
    print(f"wrote {out} rows={len(rows)}")
    print(counts)


if __name__ == "__main__":
    main()

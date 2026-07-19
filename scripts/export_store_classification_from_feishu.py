"""Read the 2026 S/A/B/C store classification sheet into local staging.

The script only reads Feishu and writes a local cache used by lann-site analysis.
It never changes the source spreadsheet.
"""

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path

from config import settings
from services import feishu_client


DEFAULT_SHEET_TOKEN = "XRv2smrFghMmN8tcZcAca8WHn0f"
DEFAULT_OUTPUT = "data/staging/store_2026_classification.csv"
OUTPUT_HEADERS = (
    "门店名称",
    "城市",
    "投资类型",
    "开业日期",
    "商圈等级",
    "商场等级",
    "立项业绩定额",
    "房量规模",
    "业务组合",
    "门店类型",
    "生命周期",
    "月均新客",
    "月均营业额_万元",
    "近12个月收入合计_万元",
    "近12个月新客客次",
    "房间数",
    "门店2026分类",
    "来源链接",
)


def excel_serial_to_iso(value):
    if not isinstance(value, (int, float)):
        return value or ""
    return (datetime(1899, 12, 30) + timedelta(days=value)).date().isoformat()


def normalize_rows(values: list[list], source_url: str) -> list[dict]:
    if not values:
        return []
    rows = []
    for raw in values[1:]:
        padded = list(raw) + [None] * max(0, 17 - len(raw))
        if not padded[0]:
            continue
        rows.append(
            {
                "门店名称": padded[0],
                "城市": padded[1] or "",
                "投资类型": padded[2] or "",
                "开业日期": excel_serial_to_iso(padded[3]),
                "商圈等级": padded[4] or "",
                "商场等级": padded[5] or "",
                "立项业绩定额": padded[6] or "",
                "房量规模": padded[7] or "",
                "业务组合": padded[8] or "",
                "门店类型": padded[9] or "",
                "生命周期": padded[10] or "",
                "月均新客": padded[11] if padded[11] is not None else "",
                "月均营业额_万元": padded[12] if padded[12] is not None else "",
                "近12个月收入合计_万元": padded[13] if padded[13] is not None else "",
                "近12个月新客客次": padded[14] if padded[14] is not None else "",
                "房间数": padded[15] if padded[15] is not None else "",
                "门店2026分类": padded[16] or "",
                "来源链接": source_url,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet-token", default=DEFAULT_SHEET_TOKEN)
    parser.add_argument("--sheet-title", default="Sheet1")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    token = feishu_client.get_tenant_access_token()
    meta = feishu_client.get_spreadsheet_meta(args.sheet_token, token)
    tabs = meta.get("sheets", [])
    tab = next((item for item in tabs if item.get("title") == args.sheet_title), None)
    if not tab:
        available = ", ".join(item.get("title", "") for item in tabs)
        raise RuntimeError(f"未找到标签页 {args.sheet_title}；当前标签页：{available}")

    values = feishu_client.read_sheet_range(
        args.sheet_token,
        f"{tab['sheet_id']}!A1:Q500",
        token,
        value_render_option="UnformattedValue",
    )
    source_url = f"https://lann.feishu.cn/sheets/{args.sheet_token}"
    rows = normalize_rows(values, source_url)
    output = settings.ROOT_DIR / Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    counts = {tier: sum(row["门店2026分类"] == tier for row in rows) for tier in "SABC"}
    print(f"store classification exported: rows={len(rows)} tiers={counts} output={output}")


if __name__ == "__main__":
    main()

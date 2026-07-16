import csv
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET


RAW_DIR = Path("data/raw/customer_materials")
SUMMARY_OUT = Path("data/staging/huamu_yingfeng_customer_store_summary.csv")
DOC_OUT = Path("docs/HUAMU_YINGFENG_CUSTOMER_MIGRATION_V0.1.md")

NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

TARGET_STORES = ["花木店", "盈丰天地店", "云汇天地店", "花木陆悦坊店"]
FOCUS_CONTAINS = ["花木", "盈丰", "云汇", "陆悦"]


def latest_workbook() -> Path:
    files = sorted(RAW_DIR.glob("**/*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No .xlsx files found under {RAW_DIR}")
    return files[0]


def col_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    idx = 0
    for ch in letters:
        idx = idx * 26 + ord(ch.upper()) - ord("A") + 1
    return idx


def num(value) -> float:
    try:
        return float(value) if value not in ("", None) else 0.0
    except ValueError:
        return 0.0


def fmt(value, digits=1) -> str:
    value = float(value or 0)
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def excel_date(serial: float) -> str:
    if serial <= 0:
        return ""
    return (datetime(1899, 12, 30) + timedelta(days=int(serial))).strftime("%Y-%m-%d")


def read_shared_strings(z: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    shared = []
    for si in root.findall("a:si", NS):
        texts = [t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")]
        shared.append("".join(texts))
    return shared


def cell_text(cell: ET.Element, shared: list[str]) -> str:
    value = cell.find("a:v", NS)
    if value is None:
        return ""
    text = value.text or ""
    if cell.attrib.get("t") == "s" and text.isdigit():
        return shared[int(text)]
    return text


def read_customer_rows(path: Path) -> list[dict]:
    with ZipFile(path) as z:
        shared = read_shared_strings(z)
        root = ET.fromstring(z.read("xl/worksheets/sheet2.xml"))
        rows = []
        for xml_row in root.findall(".//a:sheetData/a:row", NS):
            row_num = int(xml_row.attrib.get("r", "0"))
            if row_num < 4:
                continue
            cells = {}
            for cell in xml_row.findall("a:c", NS):
                ref = cell.attrib.get("r", "")
                if ref:
                    cells[col_index(ref)] = cell_text(cell, shared)
            customer_id = (cells.get(3) or "").strip()
            store = (cells.get(4) or "").strip()
            if not customer_id or not store:
                continue
            rows.append(
                {
                    "customer_id": customer_id,
                    "store": store,
                    "last_visit_serial": num(cells.get(5)),
                    "card_balance": num(cells.get(6)),
                    "hospital_balance": num(cells.get(7)),
                    "coupon_balance": num(cells.get(8)),
                    "gift_balance": num(cells.get(9)),
                    "debt_total": num(cells.get(10)),
                    "equity_2024": num(cells.get(11)),
                    "equity_2025": num(cells.get(12)),
                    "equity_2026_1_5": num(cells.get(13)),
                    "equity_r12": num(cells.get(14)),
                    "consume_2024": num(cells.get(15)),
                    "consume_2025": num(cells.get(16)),
                    "consume_2026_1_5": num(cells.get(17)),
                    "consume_r12": num(cells.get(18)),
                }
            )
        return rows


def aggregate(rows: list[dict]) -> list[dict]:
    by_store = defaultdict(list)
    for row in rows:
        by_store[row["store"]].append(row)
    max_visit = max((row["last_visit_serial"] for row in rows), default=0)
    out = []
    for store, items in by_store.items():
        active_90 = [row for row in items if max_visit - row["last_visit_serial"] <= 90]
        active_180 = [row for row in items if max_visit - row["last_visit_serial"] <= 180]
        active_365 = [row for row in items if max_visit - row["last_visit_serial"] <= 365]
        r12_consumers = [row for row in items if row["consume_r12"] > 0]
        out.append(
            {
                "门店": store,
                "客户数": len(items),
                "最近到店最早": excel_date(min(row["last_visit_serial"] for row in items)),
                "最近到店最晚": excel_date(max(row["last_visit_serial"] for row in items)),
                "近90天活跃客户": len(active_90),
                "近180天活跃客户": len(active_180),
                "近365天活跃客户": len(active_365),
                "R12有消耗客户": len(r12_consumers),
                "R12权益金": sum(row["equity_r12"] for row in items),
                "R12消耗": sum(row["consume_r12"] for row in items),
                "2024权益金": sum(row["equity_2024"] for row in items),
                "2025权益金": sum(row["equity_2025"] for row in items),
                "2026年1-5月权益金": sum(row["equity_2026_1_5"] for row in items),
                "2024消耗": sum(row["consume_2024"] for row in items),
                "2025消耗": sum(row["consume_2025"] for row in items),
                "2026年1-5月消耗": sum(row["consume_2026_1_5"] for row in items),
                "人均R12消耗": sum(row["consume_r12"] for row in items) / len(items),
                "R12消耗客户人均消耗": sum(row["consume_r12"] for row in items) / len(r12_consumers) if r12_consumers else 0,
                "卡余合计": sum(row["card_balance"] for row in items),
                "负债总金额": sum(row["debt_total"] for row in items),
            }
        )
    out.sort(key=lambda row: row["R12消耗"], reverse=True)
    for idx, row in enumerate(out, start=1):
        row["R12消耗排名"] = idx
    return out


def duplicate_store_count(rows: list[dict]) -> int:
    stores_by_customer = defaultdict(set)
    for row in rows:
        stores_by_customer[row["customer_id"]].add(row["store"])
    return sum(1 for stores in stores_by_customer.values() if len(stores) > 1)


def write_csv(rows: list[dict]) -> None:
    fields = [
        "门店",
        "客户数",
        "最近到店最早",
        "最近到店最晚",
        "近90天活跃客户",
        "近180天活跃客户",
        "近365天活跃客户",
        "R12有消耗客户",
        "R12权益金",
        "R12消耗",
        "2024权益金",
        "2025权益金",
        "2026年1-5月权益金",
        "2024消耗",
        "2025消耗",
        "2026年1-5月消耗",
        "人均R12消耗",
        "R12消耗客户人均消耗",
        "卡余合计",
        "负债总金额",
        "R12消耗排名",
    ]
    SUMMARY_OUT.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY_OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def find_row(rows: list[dict], name: str) -> dict:
    return next((row for row in rows if row["门店"] == name), {})


def render_doc(path: Path, rows: list[dict], raw_rows: list[dict]) -> str:
    focus_rows = [row for row in rows if any(token in row["门店"] for token in FOCUS_CONTAINS)]
    if not focus_rows:
        focus_rows = [find_row(rows, "花木店")]
    dup_count = duplicate_store_count(raw_rows)
    total_customers = len({row["customer_id"] for row in raw_rows})
    max_visit = excel_date(max((row["last_visit_serial"] for row in raw_rows), default=0))

    table_lines = []
    for row in focus_rows:
        table_lines.append(
            "| {门店} | {客户数} | {近180天活跃客户} | {R12有消耗客户} | {R12权益金} | {R12消耗} | {人均R12消耗} | {R12消耗排名} |".format(
                门店=row["门店"],
                客户数=row["客户数"],
                近180天活跃客户=row["近180天活跃客户"],
                R12有消耗客户=row["R12有消耗客户"],
                R12权益金=fmt(row["R12权益金"]),
                R12消耗=fmt(row["R12消耗"]),
                人均R12消耗=fmt(row["人均R12消耗"]),
                R12消耗排名=row["R12消耗排名"],
            )
        )

    huamu = find_row(rows, "花木店")
    yingfeng = find_row(rows, "盈丰天地店") or find_row(rows, "云汇天地店")
    luyue = find_row(rows, "花木陆悦坊店")

    return f"""# 花木-盈丰客户资料分析 V0.1

生成日期：2026-07-14

## 一、数据边界

- 原始文件：`{path}`
- 核心工作表：`A4-订单数据`
- 客户记录数：{len(raw_rows)}
- 去重客户数：{total_customers}
- 数据内最近到店最大日期：{max_visit}
- 同一客户出现在多个所属门店的数量：{dup_count}

当前文件是客户归属门店级汇总表，不是交易流水级跨店消费明细。它能判断各门店客户资产、活跃度、R12权益金和R12消耗，但不能直接证明“某个客户从花木去盈丰，再回到花木”的迁移路径。

## 二、花木/盈丰相关门店聚合

| 门店 | 客户数 | 近180天活跃客户 | R12有消耗客户 | R12权益金 | R12消耗 | 人均R12消耗 | R12消耗排名 |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(table_lines)}

## 三、当前可以得到的判断

1. 花木店在客户资产上明显强于盈丰。花木客户数为 {huamu.get("客户数", 0)}，R12消耗为 {fmt(huamu.get("R12消耗", 0))}；盈丰客户数为 {yingfeng.get("客户数", 0)}，R12消耗为 {fmt(yingfeng.get("R12消耗", 0))}。

2. 这份表支持“盈丰没有沉淀出足够客户资产”的判断，但不能单独支持“花木老客短期迁移后回流”的路径判断。后者仍需要订单流水或会员跨店消费明细。

3. 如果后续拿不到流水，这份表也可以作为客户资产终局对比：花木是成熟客户资产型门店，盈丰没有形成同等级客户池。

## 四、还缺的关键数据

要验证花木翻新期间盈丰接近 30 万的来源，需要订单流水级字段：

- 脱敏会员ID
- 消费日期或消费月份
- 消费门店
- 消费金额
- 订单数/消费次数
- 是否新客
- 是否开卡
- 开卡金额
- 点钟理疗师/是否点钟

没有这些字段时，只能做门店客户资产对比，不能做跨店迁移链路。

## 五、下一步

1. 先用当前表把花木、盈丰、花木陆悦坊的客户资产差异并入专题复盘。
2. 继续向 IT/BI 要订单流水级跨店消费数据。
3. 拿到流水后，重点定位花木翻新月份：盈丰新增业绩来自哪些会员、这些会员此前是否属于花木、花木恢复后是否回流。
"""


def main() -> None:
    path = latest_workbook()
    raw_rows = read_customer_rows(path)
    summary = aggregate(raw_rows)
    write_csv(summary)
    DOC_OUT.write_text(render_doc(path, summary, raw_rows), encoding="utf-8")
    print(f"raw_rows={len(raw_rows)} stores={len(summary)}")
    print(f"wrote {SUMMARY_OUT}")
    print(f"wrote {DOC_OUT}")


if __name__ == "__main__":
    main()

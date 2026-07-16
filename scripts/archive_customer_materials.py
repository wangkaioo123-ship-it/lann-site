import csv
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET


RAW_DIR = Path("data/raw/customer_materials")
PROFILE_OUT = Path("data/staging/customer_materials_profile.csv")
DOC_OUT = Path("docs/CUSTOMER_MATERIALS_ARCHIVE_V0.1.md")

NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


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


def read_shared_strings(z: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    shared = []
    for si in root.findall("a:si", NS):
        texts = [t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")]
        shared.append("".join(texts))
    return shared


def cell_value(cell: ET.Element, shared: list[str]) -> str:
    value = cell.find("a:v", NS)
    if value is None:
        return ""
    text = value.text or ""
    if cell.attrib.get("t") == "s" and text.isdigit():
        return shared[int(text)]
    return text


def row_values(row: ET.Element, shared: list[str]) -> list[str]:
    values = []
    last_col = 0
    for cell in row.findall("a:c", NS):
        ref = cell.attrib.get("r", "")
        idx = col_index(ref) if ref else last_col + 1
        while last_col + 1 < idx:
            values.append("")
            last_col += 1
        values.append(cell_value(cell, shared))
        last_col = idx
    return values


def workbook_profile(path: Path) -> list[dict]:
    with ZipFile(path) as z:
        shared = read_shared_strings(z)
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        rows = []
        for sheet in workbook.find("a:sheets", NS):
            name = sheet.attrib["name"]
            rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = relmap[rid]
            sheet_path = "xl/" + target.lstrip("/")
            root = ET.fromstring(z.read(sheet_path))
            dim = root.find("a:dimension", NS)
            xml_rows = root.findall(".//a:sheetData/a:row", NS)
            preview_rows = []
            for xml_row in xml_rows[:6]:
                values = [v.strip() for v in row_values(xml_row, shared)]
                preview_rows.append(" | ".join(v for v in values if v)[:500])
            rows.append(
                {
                    "归档文件": str(path),
                    "文件大小": path.stat().st_size,
                    "工作表": name,
                    "维度": dim.attrib.get("ref", "") if dim is not None else "",
                    "XML行数": len(xml_rows),
                    "前6行非空内容": "\n".join(preview_rows),
                }
            )
        return rows


def write_profile(rows: list[dict]) -> None:
    PROFILE_OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = ["归档文件", "文件大小", "工作表", "维度", "XML行数", "前6行非空内容"]
    with PROFILE_OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_doc(path: Path, rows: list[dict]) -> None:
    sheet_lines = []
    for row in rows:
        sheet_lines.append(
            f"| {row['工作表']} | {row['维度']} | {row['XML行数']} |"
        )
    content = f"""# 客户资料归档 V0.1

归档日期：2026-07-14

## 一、原始文件

- 文件：`{path}`
- 性质：客户/会员相关原始资料，含客户姓名、门店、余额、权益金、消耗等字段。
- 处理原则：原始文件仅本地保存，不进入 Git；后续分析优先使用脱敏会员 ID 或聚合结果。

## 二、工作簿结构

| 工作表 | 维度 | XML行数 |
|---|---:|---:|
{chr(10).join(sheet_lines)}

## 三、当前判断

- `A2-业务资料` 更像会员制度和业务口径说明。
- `A4-订单数据` 是核心客户/会员数据表，行数约 8.86 万，可用于花木与盈丰的会员迁移分析。
- 下一步不直接分析客户姓名，先建立脱敏映射或只输出会员迁移聚合结果。

## 四、下一步使用方向

1. 识别花木店、盈丰天地/云汇天地的客户跨店消费。
2. 定位花木翻新期间盈丰接近 30 万的月份。
3. 分析该月增长来源：花木老客迁移、盈丰自然新客、开卡/权益金/消耗结构。
4. 观察花木恢复后客户是否回流花木，或留在盈丰复购。
"""
    DOC_OUT.write_text(content, encoding="utf-8")


def main() -> None:
    path = latest_workbook()
    rows = workbook_profile(path)
    write_profile(rows)
    write_doc(path, rows)
    print(f"archived_profile={PROFILE_OUT} rows={len(rows)}")
    print(f"doc={DOC_OUT}")


if __name__ == "__main__":
    main()

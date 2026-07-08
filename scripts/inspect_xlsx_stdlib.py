import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "officeRel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def col_to_idx(cell_ref):
    letters = re.match(r"([A-Z]+)", cell_ref).group(1)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_shared_strings(z):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    out = []
    for si in root.findall("main:si", NS):
        texts = [t.text or "" for t in si.findall(".//main:t", NS)]
        out.append("".join(texts))
    return out


def cell_value(cell, shared):
    typ = cell.attrib.get("t")
    if typ == "inlineStr":
        texts = [t.text or "" for t in cell.findall(".//main:t", NS)]
        return "".join(texts)
    v = cell.find("main:v", NS)
    if v is None:
        return ""
    raw = v.text or ""
    if typ == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return raw
    return raw


def read_sheet(z, sheet_path, max_rows=None):
    shared = read_shared_strings(z)
    root = ET.fromstring(z.read(sheet_path))
    rows = []
    for row in root.findall(".//main:sheetData/main:row", NS):
        values = []
        for cell in row.findall("main:c", NS):
            ref = cell.attrib.get("r", "A1")
            idx = col_to_idx(ref)
            while len(values) <= idx:
                values.append("")
            values[idx] = cell_value(cell, shared)
        rows.append(values)
        if max_rows and len(rows) >= max_rows:
            break
    width = max((len(r) for r in rows), default=0)
    for r in rows:
        r.extend([""] * (width - len(r)))
    return rows


def workbook_sheets(z):
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rel_by_id = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
    sheets = []
    for s in wb.findall(".//main:sheet", NS):
        rid = s.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rel_by_id[rid]
        if not target.startswith("xl/"):
            target = "xl/" + target
        sheets.append((s.attrib["name"], target))
    return sheets


def main():
    path = Path(sys.argv[1])
    with zipfile.ZipFile(path) as z:
        sheets = workbook_sheets(z)
        print(f"file={path}")
        print(f"sheets={len(sheets)}")
        for name, target in sheets:
            rows = read_sheet(z, target, max_rows=12)
            full_rows = read_sheet(z, target)
            print(f"\nSHEET {name} path={target} rows={len(full_rows)} cols={max((len(r) for r in full_rows), default=0)}")
            for i, row in enumerate(rows, 1):
                print(i, row[:30])


if __name__ == "__main__":
    main()

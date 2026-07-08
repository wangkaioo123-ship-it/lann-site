import csv
import html
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path

from scripts.contract_plan import is_rent_file


OUT_DIR = Path("data/staging")
XLSX = OUT_DIR / "rent_contract_status_2026-06-29.xlsx"
CSV = OUT_DIR / "rent_contract_status_2026-06-29.csv"


def read_csv_dict(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def col_name(n):
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def cell_xml(v):
    if v is None:
        v = ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"<v>{v}</v>"
    return f"<is><t>{html.escape(str(v))}</t></is>"


def sheet_xml(data, widths=None, freeze=True, autofilter=True):
    max_col = max((len(r) for r in data), default=1)
    max_row = len(data)
    cols = ""
    if widths:
        for i, w in enumerate(widths, 1):
            cols += f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
    rows_xml = []
    for r_idx, row in enumerate(data, 1):
        cells = []
        for c_idx, val in enumerate(row, 1):
            ref = f"{col_name(c_idx)}{r_idx}"
            is_num = isinstance(val, (int, float)) and not isinstance(val, bool)
            t = "" if is_num else ' t="inlineStr"'
            style = 1 if r_idx == 1 else 0
            cells.append(f'<c r="{ref}"{t} s="{style}">{cell_xml(val)}</c>')
        rows_xml.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    pane = (
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        if freeze
        else '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
    )
    af = f'<autoFilter ref="A1:{col_name(max_col)}{max_row}"/>' if autofilter and max_row > 1 else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"{pane}<cols>{cols}</cols><sheetData>{''.join(rows_xml)}</sheetData>{af}</worksheet>"
    )


def build():
    base = read_csv_dict("data/staging/base_table.csv")
    rent_rows = read_csv_dict("data/staging/rent_extract.csv")
    rent_by_id = {r["点位ID"]: r for r in rent_rows}

    inv = json.loads(Path("data/contracts/inventory.json").read_text(encoding="utf-8"))
    by_l = defaultdict(list)
    for proj, info in inv.items():
        m = re.search(r"(L\d{4})", proj) or re.search(r"(L\d{4})", info.get("path", ""))
        if not m:
            continue
        sid = m.group(1)
        for f in info.get("files", []):
            by_l[sid].append(f["name"])

    ocr_by_id = defaultdict(list)
    for p in Path("data/contracts/ocr").glob("*.txt"):
        m = re.match(r"(L\d{4})", p.name)
        if m:
            ocr_by_id[m.group(1)].append(p.name)

    headers = [
        "点位ID",
        "门店名称",
        "城市",
        "门店属性",
        "门店状态",
        "租赁终止日",
        "底表当前年租金月",
        "合同档案文件数",
        "可跑租赁PDF数",
        "已OCR文本数",
        "当年/月租金",
        "下一年/月租金",
        "租金变更日",
        "含税",
        "租金来源文件",
        "处理结论",
        "需要王凯动作",
        "需要补充/确认内容",
        "备注",
    ]
    rows = []
    for b in base:
        sid = b.get("点位ID", "")
        files = by_l.get(sid, [])
        rent_files = [x for x in files if is_rent_file(x)]
        ocr_files = ocr_by_id.get(sid, [])
        rr = rent_by_id.get(sid)
        conclusion = ""
        action = ""
        need = ""
        note = ""
        rent_now = rent_next = change_date = tax = source = ""
        if rr:
            rent_now = rr.get("当年租金", "")
            rent_next = rr.get("下一年租金", "")
            change_date = rr.get("年租金变更日", "")
            tax = rr.get("含税", "")
            source = rr.get("来源文件", "")
            note = rr.get("备注", "")
            st = rr.get("状态", "")
            if st == "当年已定":
                conclusion = "已跑出当年租金"
                action = "无需动作"
            elif st == "历史已终止":
                conclusion = "历史已终止，已跑出历史租金"
                action = "无需动作"
            elif "续约文档" in st:
                conclusion = "缺2026现行续约/租金文件"
                action = "需补充档案"
                need = "补充当前有效续约协议、租赁补充协议、付款通知或财务实付租金"
            elif "商务条款" in st:
                conclusion = "合同OCR无法取得真实商务条款"
                action = "需补充档案"
                need = "补充商务条款附件、付款通知或财务实付租金"
            elif "待你给文档" in st:
                conclusion = "当前档案无最终租金文件"
                action = "需补充档案"
                need = "补充最终租赁合同/续约协议/商务条款/付款通知"
            else:
                conclusion = st or "已有租金行，需复核状态"
                action = "需人工确认"
                need = "复核租金表状态"
        else:
            if rent_files:
                conclusion = "有租赁PDF但未形成租金结论"
                action = "需人工确认"
                need = "检查OCR质量或人工读图；如为已终止/非现行合同，确认是否纳入"
                source = "；".join(rent_files[:3]) + ("…" if len(rent_files) > 3 else "")
            elif files:
                conclusion = "合同档案中无可跑租赁PDF"
                action = "需补充档案/确认无需"
                need = "补充租赁合同、续约协议、商务条款、付款通知；若加盟店租金不在总部档案，需确认口径"
            else:
                conclusion = "未在合同档案inventory中匹配到门店文件"
                action = "需确认档案位置"
                need = "确认该店是否有合同档案；如有，补入合同文件夹或更新inventory"

        rows.append(
            [
                sid,
                b.get("门店名称", ""),
                b.get("城市", ""),
                b.get("门店属性", ""),
                b.get("门店状态", ""),
                b.get("租赁终止日", ""),
                b.get("当前年租金月", ""),
                len(files),
                len(rent_files),
                len(ocr_files),
                rent_now,
                rent_next,
                change_date,
                tax,
                source,
                conclusion,
                action,
                need,
                note,
            ]
        )

    with CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)

    unique_site_ids = {r[0] for r in rows if r[0]}
    matched_ids = {r[0] for r in rows if r[7] > 0}
    rent_pdf_ids = {r[0] for r in rows if r[8] > 0}
    ocr_ids = {r[0] for r in rows if r[9] > 0}
    conclusion_ids = {
        r[0]
        for r in rows
        if r[10] or r[15].startswith(("缺", "合同OCR", "当前档案"))
    }
    current_done_ids = {r[0] for r in rows if r[15] == "已跑出当年租金"}
    historical_done_ids = {r[0] for r in rows if r[15] == "历史已终止，已跑出历史租金"}

    summary = [
        ["指标", "数量"],
        ["底表门店行数", len(base)],
        ["底表唯一点位ID数", len(unique_site_ids)],
        ["合同档案匹配门店行数 / 唯一点位ID数", f"{sum(1 for r in rows if r[7] > 0)} / {len(matched_ids)}"],
        ["有可跑租赁PDF门店行数 / 唯一点位ID数", f"{sum(1 for r in rows if r[8] > 0)} / {len(rent_pdf_ids)}"],
        ["已OCR门店行数 / 唯一点位ID数", f"{sum(1 for r in rows if r[9] > 0)} / {len(ocr_ids)}"],
        ["租金表已有结论门店行数 / 唯一点位ID数", f"{sum(1 for r in rows if r[10] or r[15].startswith(('缺', '合同OCR', '当前档案')))} / {len(conclusion_ids)}"],
        ["当年租金已定门店行数 / 唯一点位ID数", f"{sum(1 for r in rows if r[15] == '已跑出当年租金')} / {len(current_done_ids)}"],
        ["历史已终止已跑出门店行数 / 唯一点位ID数", f"{sum(1 for r in rows if r[15] == '历史已终止，已跑出历史租金')} / {len(historical_done_ids)}"],
        ["需要补充档案门店行数", sum(1 for r in rows if r[16] == "需补充档案")],
        ["需要补充档案/确认无需门店行数", sum(1 for r in rows if r[16] == "需补充档案/确认无需")],
        ["需要确认档案位置门店行数", sum(1 for r in rows if r[16] == "需确认档案位置")],
        ["需要人工确认门店行数", sum(1 for r in rows if r[16] == "需人工确认")],
    ]
    need_rows = [r for r in rows if r[16] != "无需动作"]

    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F4E79"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="1" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>
<sheet name="总览" sheetId="1" r:id="rId1"/>
<sheet name="门店明细" sheetId="2" r:id="rId2"/>
<sheet name="需补充确认" sheetId="3" r:id="rId3"/>
</sheets></workbook>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>
<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

    widths_detail = [12, 24, 10, 10, 12, 14, 16, 14, 14, 12, 14, 14, 14, 8, 28, 24, 18, 42, 80]
    with zipfile.ZipFile(XLSX, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/styles.xml", styles)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml(summary, [32, 14], freeze=True, autofilter=False))
        z.writestr("xl/worksheets/sheet2.xml", sheet_xml([headers] + rows, widths_detail, freeze=True, autofilter=True))
        z.writestr("xl/worksheets/sheet3.xml", sheet_xml([headers] + need_rows, widths_detail, freeze=True, autofilter=True))

    print(f"wrote {XLSX} {XLSX.stat().st_size}")
    print(f"wrote {CSV} {CSV.stat().st_size}")
    for row in summary[1:]:
        print(f"{row[0]}={row[1]}")


if __name__ == "__main__":
    build()

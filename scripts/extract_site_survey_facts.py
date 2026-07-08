import argparse
import csv
import re
from pathlib import Path

from config import settings
from services import feishu_client, feishu_oauth


META = Path("data/staging/site_survey_report_meta.csv")
OUT = Path("data/staging/site_survey_facts.csv")


def text_of(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(text_of(v) for v in value if text_of(v))
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or value.get("fileToken") or "")
    return str(value).strip()


def clean(value) -> str:
    return text_of(value).replace("\n", " ").strip()


def parse_number(value) -> str:
    text = clean(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return match.group(0) if match else ""


def inline_value(text: str, keyword: str) -> str:
    text = clean(text)
    if keyword not in text:
        return ""
    tail = text.split(keyword, 1)[1]
    tail = tail.lstrip(" /：:/")
    return tail.strip()


def find_row(grid, keyword: str):
    for row in grid:
        if any(keyword in clean(cell) for cell in row):
            return row
    return []


def next_cell(row, keyword: str, max_ahead: int = 2) -> str:
    for idx, cell in enumerate(row):
        cell_text = clean(cell)
        same_cell = inline_value(cell_text, keyword)
        if same_cell:
            return same_cell
        if keyword in cell_text:
            for offset in range(1, max_ahead + 1):
                if idx + offset < len(row):
                    value = clean(row[idx + offset])
                    if value:
                        return value
    return ""


def cell_after_label(grid, label: str, max_ahead: int = 3) -> str:
    for row in grid:
        value = next_cell(row, label, max_ahead=max_ahead)
        if value:
            return value
    return ""


def rating_for(grid, item: str) -> str:
    for row in grid:
        texts = [clean(cell) for cell in row]
        if any(item == text or item in text for text in texts):
            for value in reversed(texts):
                if value in {"S", "A", "B", "C"}:
                    return value
    return ""


def row_summary(grid, keyword: str) -> str:
    row = find_row(grid, keyword)
    if not row:
        return ""
    values = [clean(cell) for cell in row if clean(cell)]
    return " | ".join(values)[:1000]


def investment_value(grid, label: str) -> str:
    for row in grid:
        texts = [clean(cell) for cell in row]
        for idx, text in enumerate(texts):
            if label in text:
                for value in reversed(texts[idx + 1 :]):
                    n = parse_number(value)
                    if n:
                        return n
    return ""


def analysis_text(grid, category: str, subcategory: str = "") -> str:
    current_category = ""
    for row in grid:
        texts = [clean(cell) for cell in row]
        if texts and texts[0]:
            current_category = texts[0]
        if category not in current_category:
            continue
        if subcategory:
            if len(texts) > 1 and subcategory in texts[1]:
                return texts[2] if len(texts) > 2 else ""
        elif len(texts) > 2:
            return texts[2]
    return ""


def read_tab(sheet_token: str, title_keyword: str, token: str, max_range: str = "A1:H80") -> list:
    meta = feishu_client.get_spreadsheet_meta(sheet_token, token)
    for sheet in meta.get("sheets", []):
        title = sheet.get("title", "")
        if title_keyword in title:
            return feishu_client.read_sheet_range(
                sheet_token,
                f"{sheet.get('sheet_id')}!{max_range}",
                token,
                value_render_option="FormattedValue",
            )
    return []


def extract_one(row: dict, token: str) -> dict:
    sheet_token = row["sheet_token"]
    site_grid = read_tab(sheet_token, "场地信息", token)
    engineering_grid = read_tab(sheet_token, "店铺工程信息", token)
    analysis_grid = read_tab(sheet_token, "投资分析", token)

    overview = find_row(site_grid, "店铺概览")
    rent = next_cell(overview, "租金+物业")
    area = next_cell(overview, "面积")
    lease_term = cell_after_label([overview], "合同租期")
    mall_open = cell_after_label([overview], "商场开业时间")
    parking = cell_after_label([overview], "商场停车位")

    result = {
        "点位ID": row.get("点位ID", ""),
        "门店名称": row.get("门店名称", ""),
        "报告名称": row.get("报告名称", ""),
        "报告链接": row.get("报告链接", ""),
        "租金物业月成本": parse_number(rent),
        "面积": parse_number(area),
        "合同租期": lease_term,
        "商场开业时间": mall_open,
        "停车位": parking,
        "商场体系": cell_after_label(site_grid, "商场体系"),
        "商场体量": cell_after_label(site_grid, "商场体量"),
        "商场铺位数量": cell_after_label(site_grid, "商场铺位数量"),
        "交付条件": cell_after_label(site_grid, "交付条件"),
        "推荐落位楼层": cell_after_label(site_grid, "推荐落位楼层"),
        "商场城市排名评级": rating_for(site_grid, "商场城市排名"),
        "商圈等级评级": rating_for(site_grid, "商圈等级"),
        "商场定位评级": rating_for(site_grid, "商场定位"),
        "商场年销售额评级": rating_for(site_grid, "商场年销售额"),
        "商场客流评级": rating_for(site_grid, "商场客流"),
        "零售品牌评级": rating_for(site_grid, "商场零售品牌定位"),
        "餐饮品牌评级": rating_for(site_grid, "商场餐饮品牌定位"),
        "配套品牌评级": rating_for(site_grid, "商场配套品牌定位"),
        "西餐咖啡评级": rating_for(site_grid, "商场西餐咖啡品牌"),
        "主力店评级": rating_for(site_grid, "商场主力店品牌"),
        "连锁美容SPA普拉提摘要": row_summary(site_grid, "连锁美容"),
        "同类竞品摘要": row_summary(site_grid, "同类竞品"),
        "点评摘要": row_summary(site_grid, "点评"),
        "对标购物中心": cell_after_label(site_grid, "对标购物中心"),
        "常驻人口摘要": row_summary(site_grid, "常驻人口"),
        "周边小区摘要": row_summary(site_grid, "周边小区"),
        "房价摘要": row_summary(site_grid, "新房/二手房价"),
        "写字楼摘要": row_summary(site_grid, "写字楼(体量)"),
        "工程层高反馈": row_summary(engineering_grid, "层高"),
        "工程新风反馈": row_summary(engineering_grid, "新风"),
        "工程排风反馈": row_summary(engineering_grid, "排风"),
        "工程电力反馈": row_summary(engineering_grid, "电力供应"),
        "证照政策": analysis_text(analysis_grid, "证照政策", "营业执照"),
        "消防建议": analysis_text(analysis_grid, "证照政策", "消防"),
        "客质和人流": analysis_text(analysis_grid, "商场情况", "客质和人流"),
        "业态分布和营业时间": analysis_text(analysis_grid, "商场情况", "业态分布"),
        "商场竞争力": analysis_text(analysis_grid, "商场情况", "商场竞争力"),
        "广告分析": analysis_text(analysis_grid, "广告指引", "广告分析"),
        "远景机会": analysis_text(analysis_grid, "机会点和风险点分析", "远景"),
        "竞争性": analysis_text(analysis_grid, "机会点和风险点分析", "竞争性"),
        "风险性": analysis_text(analysis_grid, "机会点和风险点分析", "风险性"),
        "稳定营业额预期": analysis_text(analysis_grid, "回报率分析", "稳定营业额预期"),
        "总投入含押金": investment_value(analysis_grid, "总投入（含押金）"),
        "总投入不含押金": investment_value(analysis_grid, "总投入（不含押金）"),
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--meta", default=str(META))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    rows = [
        row
        for row in csv.DictReader(Path(args.meta).open(encoding="utf-8-sig", newline=""))
        if row.get("状态") == "可读取"
    ]
    token = feishu_oauth.get_valid_user_token()
    out_rows = []
    failures = []
    for idx, row in enumerate(rows, 1):
        try:
            out_rows.append(extract_one(row, token))
            print(f"[{idx}/{len(rows)}] {row.get('门店名称')} ok")
        except RuntimeError as exc:
            failures.append([row.get("点位ID", ""), row.get("门店名称", ""), str(exc)[:300]])
            print(f"[{idx}/{len(rows)}] {row.get('门店名称')} failed {str(exc)[:80]}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    headers = list(out_rows[0].keys()) if out_rows else []
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(out_rows)

    fail_out = settings.ROOT_DIR / "data" / "staging" / "site_survey_fact_failures.csv"
    with fail_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["点位ID", "门店名称", "失败原因"])
        writer.writerows(failures)

    print(f"wrote {out} rows={len(out_rows)}")
    print(f"wrote {fail_out} rows={len(failures)}")


if __name__ == "__main__":
    main()

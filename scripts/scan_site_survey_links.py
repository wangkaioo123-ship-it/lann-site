import argparse
import csv
import re
from urllib.parse import unquote

from config import settings
from services import feishu_client, feishu_oauth
from scripts.sample_forecasts import resolve_to_sheet_token


KEYWORDS = ["选址调研", "调研报告", "选址报告", "调研", "报告"]


def text_and_link(value) -> tuple[str, str]:
    if isinstance(value, list):
        texts = []
        links = []
        for item in value:
            t, lnk = text_and_link(item)
            if t:
                texts.append(t)
            if lnk:
                links.append(lnk)
        return "".join(texts), "；".join(links)
    if isinstance(value, dict):
        if value.get("text"):
            texts = str(value.get("text"))
        else:
            texts = ""
        link = value.get("link") or ""
        if link:
            link = unquote(str(link))
        return texts, link
    return str(value or ""), ""


def find_links_in_grid(grid, tab_title):
    hits = []
    for i, row in enumerate(grid):
        for j, cell in enumerate(row):
            text, link = text_and_link(cell)
            if not text and not link:
                continue
            haystack = text + " " + link
            if not any(keyword in haystack for keyword in KEYWORDS):
                continue
            # Also inspect nearby cells because labels and hyperlinks are often split.
            near_texts = []
            near_links = []
            for dj in range(0, 4):
                if j + dj < len(row):
                    t, lnk = text_and_link(row[j + dj])
                    if t:
                        near_texts.append(t)
                    if lnk:
                        near_links.append(lnk)
            if i + 1 < len(grid):
                for dj in range(0, 4):
                    if j + dj < len(grid[i + 1]):
                        t, lnk = text_and_link(grid[i + 1][j + dj])
                        if t:
                            near_texts.append(t)
                        if lnk:
                            near_links.append(lnk)
            hits.append(
                {
                    "sheet_tab": tab_title,
                    "cell": f"R{i + 1}C{j + 1}",
                    "label": text[:120],
                    "near_text": " | ".join(near_texts)[:300],
                    "links": "；".join(dict.fromkeys([link] + near_links))[:1000],
                }
            )
    return hits


def scan_sheet(link: str, token: str, max_rows: int, max_cols: str):
    sheet_token = resolve_to_sheet_token(link, token)
    if not sheet_token:
        return "不是电子表格", []
    meta = feishu_client.get_spreadsheet_meta(sheet_token, token)
    hits = []
    for sheet in meta.get("sheets", []):
        sid = sheet.get("sheet_id")
        title = sheet.get("title", "")
        try:
            grid = feishu_client.read_sheet_range(
                sheet_token,
                f"{sid}!A1:{max_cols}{max_rows}",
                token,
                value_render_option="Formula",
            )
        except RuntimeError as exc:
            hits.append(
                {
                    "sheet_tab": title,
                    "cell": "",
                    "label": "读取标签页失败",
                    "near_text": str(exc)[:300],
                    "links": "",
                }
            )
            continue
        hits.extend(find_links_in_grid(grid, title))
    return "", hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-rows", type=int, default=120)
    parser.add_argument("--max-cols", default="R")
    parser.add_argument("--out", default="data/staging/site_survey_links.csv")
    args = parser.parse_args()

    token = feishu_oauth.get_valid_user_token()
    base_path = settings.ROOT_DIR / "data" / "staging" / "base_table.csv"
    with base_path.open(encoding="utf-8-sig", newline="") as f:
        rows = [row for row in csv.DictReader(f) if row.get("测算表链接")]
    if args.limit:
        rows = rows[: args.limit]

    out_rows = []
    failures = []
    for idx, row in enumerate(rows, 1):
        site_id = row.get("点位ID", "")
        name = row.get("门店名称", "")
        link = row.get("测算表链接", "")
        try:
            reason, hits = scan_sheet(link, token, args.max_rows, args.max_cols)
        except RuntimeError as exc:
            failures.append((site_id, name, str(exc)[:200]))
            print(f"[{idx}/{len(rows)}] {name}: failed {str(exc)[:80]}")
            continue
        if reason:
            failures.append((site_id, name, reason))
        for hit in hits:
            out_rows.append(
                {
                    "点位ID": site_id,
                    "门店名称": name,
                    "测算表链接": link,
                    **hit,
                }
            )
        print(f"[{idx}/{len(rows)}] {name}: hits={len(hits)}")

    out = settings.ROOT_DIR / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    headers = ["点位ID", "门店名称", "测算表链接", "sheet_tab", "cell", "label", "near_text", "links"]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(out_rows)

    fail_out = settings.ROOT_DIR / "data" / "staging" / "site_survey_links_failures.csv"
    with fail_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["点位ID", "门店名称", "失败原因"])
        writer.writerows(failures)

    print(f"wrote {out} rows={len(out_rows)}")
    print(f"wrote {fail_out} rows={len(failures)}")


if __name__ == "__main__":
    main()

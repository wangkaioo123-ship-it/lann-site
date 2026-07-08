import csv

from config import settings
from services import feishu_client, feishu_oauth
from scripts.sample_forecasts import resolve_to_sheet_token


def main():
    token = feishu_oauth.get_valid_user_token()
    src = settings.ROOT_DIR / "data" / "staging" / "site_survey_links.csv"
    rows = list(csv.DictReader(src.open(encoding="utf-8-sig", newline="")))

    out = settings.ROOT_DIR / "data" / "staging" / "site_survey_report_meta.csv"
    sample_out = settings.ROOT_DIR / "data" / "staging" / "site_survey_report_samples.csv"
    meta_rows = []
    sample_rows = []
    failures = []

    for row in rows:
        link = row.get("links", "").split("；")[0]
        try:
            sheet_token = resolve_to_sheet_token(link, token)
            if not sheet_token:
                failures.append([row.get("点位ID", ""), row.get("门店名称", ""), link, "不是电子表格"])
                continue
            meta = feishu_client.get_spreadsheet_meta(sheet_token, token)
            sheets = meta.get("sheets", [])
            meta_rows.append(
                {
                    "点位ID": row.get("点位ID", ""),
                    "门店名称": row.get("门店名称", ""),
                    "报告名称": row.get("label", ""),
                    "报告链接": link,
                    "sheet_token": sheet_token,
                    "标签页数量": len(sheets),
                    "标签页": " | ".join(s.get("title", "") for s in sheets),
                    "状态": "可读取",
                }
            )
            for sheet in sheets[:3]:
                sid = sheet.get("sheet_id")
                title = sheet.get("title", "")
                values = feishu_client.read_sheet_range(
                    sheet_token,
                    f"{sid}!A1:H25",
                    token,
                    value_render_option="FormattedValue",
                )
                for idx, value_row in enumerate(values[:25], 1):
                    text = " | ".join("" if v is None else str(v) for v in value_row)
                    if text.strip():
                        sample_rows.append(
                            {
                                "点位ID": row.get("点位ID", ""),
                                "门店名称": row.get("门店名称", ""),
                                "报告名称": row.get("label", ""),
                                "标签页": title,
                                "行号": idx,
                                "内容": text[:1000],
                            }
                        )
        except RuntimeError as exc:
            failures.append([row.get("点位ID", ""), row.get("门店名称", ""), link, str(exc)[:300]])
            meta_rows.append(
                {
                    "点位ID": row.get("点位ID", ""),
                    "门店名称": row.get("门店名称", ""),
                    "报告名称": row.get("label", ""),
                    "报告链接": link,
                    "sheet_token": "",
                    "标签页数量": "",
                    "标签页": "",
                    "状态": str(exc)[:300],
                }
            )

    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["点位ID", "门店名称", "报告名称", "报告链接", "sheet_token", "标签页数量", "标签页", "状态"],
        )
        writer.writeheader()
        writer.writerows(meta_rows)

    with sample_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["点位ID", "门店名称", "报告名称", "标签页", "行号", "内容"])
        writer.writeheader()
        writer.writerows(sample_rows)

    fail_out = settings.ROOT_DIR / "data" / "staging" / "site_survey_report_failures.csv"
    with fail_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["点位ID", "门店名称", "报告链接", "失败原因"])
        writer.writerows(failures)

    print(f"wrote {out} rows={len(meta_rows)}")
    print(f"wrote {sample_out} rows={len(sample_rows)}")
    print(f"wrote {fail_out} rows={len(failures)}")
    readable = sum(1 for row in meta_rows if row["状态"] == "可读取")
    print(f"readable={readable}/{len(rows)} failures={len(failures)}")


if __name__ == "__main__":
    main()

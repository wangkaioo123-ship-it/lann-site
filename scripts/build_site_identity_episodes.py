import argparse
import calendar
import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from config import settings


EPISODES = "config/site_identity_episodes.json"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def read_records(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return read_csv(path)


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_date(value: str) -> date | None:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def month_bounds(value: str) -> tuple[date, date]:
    year, month = (int(part) for part in value.split("-"))
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def covers_full_month(episode: dict, month: str) -> bool:
    month_start, month_end = month_bounds(month)
    start = parse_date(episode.get("effective_start", ""))
    end = parse_date(episode.get("effective_end", ""))
    return (start is None or start <= month_start) and (end is None or end >= month_end)


def overlaps_month(episode: dict, month: str) -> bool:
    month_start, month_end = month_bounds(month)
    start = parse_date(episode.get("effective_start", "")) or date.min
    end = parse_date(episode.get("effective_end", "")) or date.max
    return start <= month_end and end >= month_start


def build_analysis_base(base_rows: list[dict], episodes: list[dict]) -> list[dict]:
    configured_record_ids = {row["source_record_id"] for row in episodes}
    confirmed_by_record = {
        row["source_record_id"]: row for row in episodes if row.get("resolution_status") == "confirmed"
    }
    output = []
    for row in base_rows:
        record_id = row.get("record_id", "")
        if record_id in configured_record_ids:
            episode = confirmed_by_record.get(record_id)
            if not episode:
                continue
            copied = dict(row)
            copied["源点位ID"] = row.get("点位ID", "")
            copied["点位ID"] = episode["analysis_point_id"]
            copied["门店名称"] = episode["point_name"]
            copied["经营期起"] = episode.get("effective_start", "")
            copied["经营期止"] = episode.get("effective_end", "")
            output.append(copied)
        elif row.get("点位ID"):
            copied = dict(row)
            copied["源点位ID"] = row.get("点位ID", "")
            copied["经营期起"] = ""
            copied["经营期止"] = ""
            output.append(copied)
    return output


def build_analysis_rent(rent_rows: list[dict], episodes: list[dict]) -> list[dict]:
    configured_record_ids = {row["source_record_id"] for row in episodes}
    confirmed_by_record = {
        row["source_record_id"]: row for row in episodes if row.get("resolution_status") == "confirmed"
    }
    output = []
    for row in rent_rows:
        record_id = row.get("record_id", "")
        if record_id in configured_record_ids:
            episode = confirmed_by_record.get(record_id)
            if not episode:
                continue
            copied = dict(row)
            copied["源点位ID"] = row.get("点位ID", "")
            copied["点位ID"] = episode["analysis_point_id"]
            copied["门店名"] = episode["point_name"]
            output.append(copied)
        else:
            copied = dict(row)
            copied["源点位ID"] = row.get("点位ID", "")
            output.append(copied)
    return output


def build_analysis_ops(ops_rows: list[dict], episodes: list[dict]) -> tuple[list[dict], list[dict]]:
    by_store = defaultdict(list)
    for episode in episodes:
        by_store[episode["hanson_store_name"]].append(episode)

    output = []
    issues = []
    for row in ops_rows:
        store = row.get("Hanson门店名称", "")
        store_episodes = by_store.get(store)
        if not store_episodes:
            copied = dict(row)
            copied["源点位ID"] = row.get("点位ID", "")
            copied["身份分配状态"] = "原映射保留"
            output.append(copied)
            continue

        confirmed = [episode for episode in store_episodes if episode.get("resolution_status") == "confirmed"]
        if not confirmed:
            issues.append({"Hanson门店名称": store, "月份": row.get("月份", ""), "问题": "身份方案待确认"})
            continue

        month = row.get("月份", "")
        full_matches = [episode for episode in confirmed if covers_full_month(episode, month)]
        if len(full_matches) == 1:
            episode = full_matches[0]
            copied = dict(row)
            copied["源点位ID"] = row.get("点位ID", "")
            copied["点位ID"] = episode["analysis_point_id"]
            copied["身份分配状态"] = "完整月份已分配"
            output.append(copied)
            continue

        if any(overlaps_month(episode, month) for episode in confirmed):
            issue = "换铺过渡月-月度数据不拆分"
        else:
            issue = "不在已确认经营期"
        issues.append({"Hanson门店名称": store, "月份": month, "问题": issue})
    return output, issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Build analysis-safe physical site episodes without mutating source data.")
    parser.add_argument("--episodes", default=EPISODES)
    parser.add_argument("--base", default="data/staging/base_table.csv")
    parser.add_argument("--rent", default="data/staging/rent_extract_feishu.csv")
    parser.add_argument("--ops", default="data/staging/site_ops_monthly_combined.csv")
    parser.add_argument("--base-out", default="data/staging/base_table_analysis.csv")
    parser.add_argument("--rent-out", default="data/staging/rent_extract_analysis.csv")
    parser.add_argument("--ops-out", default="data/staging/site_ops_monthly_analysis.csv")
    parser.add_argument("--issues-out", default="data/staging/site_identity_assignment_issues.csv")
    args = parser.parse_args()

    episodes = read_records(settings.ROOT_DIR / args.episodes)
    base_rows = read_csv(settings.ROOT_DIR / args.base)
    rent_rows = read_csv(settings.ROOT_DIR / args.rent)
    ops_rows = read_csv(settings.ROOT_DIR / args.ops)
    analysis_base = build_analysis_base(base_rows, episodes)
    analysis_rent = build_analysis_rent(rent_rows, episodes)
    analysis_ops, issues = build_analysis_ops(ops_rows, episodes)

    write_csv(settings.ROOT_DIR / args.base_out, analysis_base, list(analysis_base[0].keys()))
    write_csv(settings.ROOT_DIR / args.rent_out, analysis_rent, list(analysis_rent[0].keys()))
    ops_fields = list(ops_rows[0].keys()) + ["源点位ID", "身份分配状态"]
    write_csv(settings.ROOT_DIR / args.ops_out, analysis_ops, ops_fields)
    write_csv(settings.ROOT_DIR / args.issues_out, issues, ["Hanson门店名称", "月份", "问题"])
    print(f"analysis base={len(analysis_base)} rent={len(analysis_rent)} ops={len(analysis_ops)}")
    print("identity issues", dict(Counter(row["问题"] for row in issues)))


if __name__ == "__main__":
    main()

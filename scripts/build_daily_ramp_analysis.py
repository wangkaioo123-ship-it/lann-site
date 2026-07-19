"""Build read-only 7/14/28-day ramp observations from Hanson daily closes."""

import argparse
import calendar
import csv
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from config import settings
from scripts.refresh_hanson_daily_ops import load_mapping, number, parse_day, resolved_point_id


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def fmt(value, digits=2) -> str:
    if value in (None, ""):
        return ""
    return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")


def stable_latest_date(daily_rows: list[dict], mapping_rows: list[dict]) -> date | None:
    mapped, excluded = load_mapping(mapping_rows)
    coverage = defaultdict(set)
    for row in daily_rows:
        name = str(row.get("store_name") or "").strip()
        if name and name not in excluded and mapped.get(name):
            coverage[parse_day(row["data_date"])].add(name)
    peak = max((len(names) for names in coverage.values()), default=0)
    threshold = math.ceil(peak * 0.8)
    return max((day for day, names in coverage.items() if len(names) >= threshold), default=None)


def normalize_store_name(value: str) -> str:
    name = str(value or "").strip()
    name = re.sub(r"(旗舰)?店$", "", name)
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", name).lower()


def classification_by_site(
    base_rows: list[dict],
    classification_rows: list[dict],
    mapping_rows: list[dict] | None = None,
    confirmed_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    """Use only unique name containment matches; ambiguous names stay unclassified."""
    active_ids = {
        row.get("点位ID", "")
        for row in base_rows
        if row.get("点位ID") and row.get("门店状态") == "运营中"
    }
    aliases = [
        (row.get("点位ID", ""), normalize_store_name(row.get("门店名称", "")))
        for row in base_rows
        if row.get("点位ID") and normalize_store_name(row.get("门店名称", ""))
    ]
    aliases.extend(
        (
            row.get("site_id") or row.get("确认点位ID") or "",
            normalize_store_name(row.get("hanson_store_name") or row.get("Hanson门店名称") or ""),
        )
        for row in (mapping_rows or [])
        if (row.get("site_id") or row.get("确认点位ID"))
        and normalize_store_name(row.get("hanson_store_name") or row.get("Hanson门店名称") or "")
    )
    output = {}
    for row in classification_rows:
        target = normalize_store_name(row.get("门店名称", ""))
        tier = row.get("门店2026分类", "")
        confirmed_site = (confirmed_aliases or {}).get(row.get("门店名称", ""))
        if confirmed_site and tier in {"S", "A", "B", "C"}:
            output[confirmed_site] = tier
            continue
        exact = {site_id for site_id, name in aliases if target and target == name}
        candidates = exact or {site_id for site_id, name in aliases if target and (target in name or name in target)}
        active_candidates = candidates & active_ids
        if len(candidates) > 1 and len(active_candidates) == 1:
            candidates = active_candidates
        if len(candidates) == 1 and tier in {"S", "A", "B", "C"}:
            output[next(iter(candidates))] = tier
    return output


def opening_by_site(base_rows: list[dict]) -> dict[str, date]:
    output = {}
    for row in base_rows:
        site_id = row.get("点位ID", "")
        value = row.get("合同开业日期", "")
        if not site_id or not value:
            continue
        try:
            output[site_id] = datetime.fromisoformat(str(value)[:10]).date()
        except ValueError:
            continue
    return output


def window_values(rows: list[dict], latest: date, days: int) -> tuple[float, int, float]:
    start = latest - timedelta(days=days - 1)
    selected = [row for row in rows if start <= parse_day(row["data_date"]) <= latest]
    settled = len({parse_day(row["data_date"]) for row in selected})
    revenue = sum(number(row.get("prod_amt")) for row in selected)
    return revenue, settled, revenue / settled if settled else 0


def stage(settled_days: int) -> str:
    if settled_days < 7:
        return "数据不足"
    if settled_days < 14:
        return "7日爬坡观察"
    if settled_days < 28:
        return "14日爬坡观察"
    return "28日滚动观察"


def attach_peer_benchmarks(rows: list[dict]) -> None:
    values = defaultdict(list)
    for row in rows:
        tier = row.get("SABC", "")
        daily_average = number(row.get("近28日日均营收"))
        if tier and number(row.get("近28日结算日数")) >= 23 and daily_average > 0:
            values[tier].append(daily_average)
    for row in rows:
        tier_values = values.get(row.get("SABC", ""), [])
        median = statistics.median(tier_values) if tier_values else 0
        daily_average = number(row.get("近28日日均营收"))
        row["同类有效样本数"] = len(tier_values)
        row["同类近28日日均中位数"] = fmt(median) if median else ""
        row["相对同类中位数"] = fmt(daily_average / median - 1, 4) if median and daily_average else ""


def build(
    daily_rows: list[dict],
    mapping_rows: list[dict],
    base_rows: list[dict],
    benchmark_rows: list[dict],
    classification_rows: list[dict],
    episodes: list[dict] | None = None,
    classification_aliases: dict[str, str] | None = None,
) -> list[dict]:
    mapped, excluded = load_mapping(mapping_rows)
    latest = stable_latest_date(daily_rows, mapping_rows)
    if latest is None:
        return []
    openings = opening_by_site(base_rows)
    base_names = {row.get("点位ID", ""): row.get("门店名称", "") for row in base_rows}
    rents = {row.get("点位ID", ""): number(row.get("月租金")) for row in benchmark_rows}
    tiers = classification_by_site(base_rows, classification_rows, mapping_rows, classification_aliases)
    grouped = defaultdict(list)
    hanson_names = defaultdict(set)
    for row in daily_rows:
        day = parse_day(row["data_date"])
        name = str(row.get("store_name") or "").strip()
        if day > latest or not name or name in excluded or not mapped.get(name):
            continue
        site_id = resolved_point_id(name, day, mapped, episodes or [])
        if not site_id:
            continue
        opened = openings.get(site_id)
        if opened and day < opened:
            continue
        grouped[site_id].append(row)
        hanson_names[site_id].add(name)

    output = []
    for site_id, rows in sorted(grouped.items()):
        settled_dates = {parse_day(row["data_date"]) for row in rows}
        first_day = max(min(settled_dates), openings.get(site_id, date.min))
        expected_days = (latest - first_day).days + 1
        coverage = len(settled_dates) / expected_days if expected_days > 0 else 0
        item = {
            "点位ID": site_id,
            "门店名称": base_names.get(site_id, ""),
            "Hanson门店名称": "；".join(sorted(hanson_names[site_id])),
            "SABC": tiers.get(site_id, ""),
            "合同开业日期": openings.get(site_id, "").isoformat() if openings.get(site_id) else "",
            "数据截止日": latest.isoformat(),
            "已结算日数": len(settled_dates),
            "应结算日数_自然日代理": expected_days,
            "结算覆盖率": fmt(coverage, 4),
            "观察阶段": stage(len(settled_dates)),
            "开业零碎月": openings[site_id].strftime("%Y-%m") if openings.get(site_id) and openings[site_id].day > 1 else "",
        }
        for days in (7, 14, 28):
            revenue, settled, average = window_values(rows, latest, days)
            item[f"近{days}日营收"] = fmt(revenue)
            item[f"近{days}日结算日数"] = settled
            item[f"近{days}日日均营收"] = fmt(average)
        last_28_start = latest - timedelta(days=27)
        last_28 = [row for row in rows if last_28_start <= parse_day(row["data_date"]) <= latest]
        weekday_values = [number(row.get("prod_amt")) for row in last_28 if parse_day(row["data_date"]).weekday() < 5]
        weekend_values = [number(row.get("prod_amt")) for row in last_28 if parse_day(row["data_date"]).weekday() >= 5]
        item["近28日工作日日均营收"] = fmt(sum(weekday_values) / len(weekday_values) if weekday_values else None)
        item["近28日周末日均营收"] = fmt(sum(weekend_values) / len(weekend_values) if weekend_values else None)
        last_28_days = int(item["近28日结算日数"])
        projected = number(item["近28日日均营收"]) * calendar.monthrange(latest.year, latest.month)[1] if last_28_days >= 28 else 0
        rent = rents.get(site_id, 0)
        item["月营收暂估"] = fmt(projected) if projected else ""
        item["租售比暂估"] = fmt(rent / projected, 4) if rent and projected else ""
        item["输出限制"] = "仅作趋势和预警，不直接形成完整好店结论"
        output.append(item)
    attach_peer_benchmarks(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build daily ramp observations from Hanson closes.")
    parser.add_argument("--daily", default="data/staging/hanson_daily_prod_amt.csv")
    parser.add_argument("--mapping", default="config/store_site_mapping.json")
    parser.add_argument("--base", default="data/staging/base_table_analysis.csv")
    parser.add_argument("--benchmark", default="data/staging/site_benchmark.csv")
    parser.add_argument("--classification", default="data/staging/store_2026_classification.csv")
    parser.add_argument("--classification-aliases", default="config/store_classification_aliases.json")
    parser.add_argument("--episodes", default="config/site_identity_episodes.json")
    parser.add_argument("--out", default="data/staging/daily_ramp_analysis.csv")
    args = parser.parse_args()
    mapping_rows = json.loads((settings.ROOT_DIR / args.mapping).read_text(encoding="utf-8"))
    episodes = json.loads((settings.ROOT_DIR / args.episodes).read_text(encoding="utf-8"))
    aliases_path = settings.ROOT_DIR / args.classification_aliases
    classification_aliases = json.loads(aliases_path.read_text(encoding="utf-8")) if aliases_path.exists() else {}
    rows = build(
        read_csv(settings.ROOT_DIR / args.daily),
        mapping_rows,
        read_csv(settings.ROOT_DIR / args.base),
        read_csv(settings.ROOT_DIR / args.benchmark),
        read_csv(settings.ROOT_DIR / args.classification),
        episodes,
        classification_aliases,
    )
    out = settings.ROOT_DIR / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["点位ID", "门店名称"]
    with out.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {out} rows={len(rows)} classified={sum(bool(row.get('SABC')) for row in rows)}")


if __name__ == "__main__":
    main()

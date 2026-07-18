"""Build an evidence sheet for economically qualified stores without inventing business thresholds."""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def number(value) -> float:
    try:
        return float(value) if value not in ("", None) else 0.0
    except (TypeError, ValueError):
        return 0.0


def fmt(value, digits=2) -> str:
    return f"{value:.{digits}f}".rstrip("0").rstrip(".") if value is not None else ""


def coefficient_variation(values: list[float]) -> float | None:
    if not values or sum(values) == 0:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance) / mean


def build_metrics(rows: list[dict]) -> dict:
    rows = sorted((row for row in rows if number(row.get("实际营收")) > 0), key=lambda row: row.get("月份", ""))
    revenues = [number(row.get("实际营收")) for row in rows]
    new_values = [number(row.get("新客数")) for row in rows if row.get("新客数") not in ("", None)]
    old_values = [number(row.get("老客数")) for row in rows if row.get("老客数") not in ("", None)]
    retention_values = [number(row.get("留存率")) for row in rows if row.get("留存率") not in ("", None)]
    return_values = [number(row.get("返店频次")) for row in rows if row.get("返店频次") not in ("", None)]
    total_new = sum(new_values)
    total_old = sum(old_values)
    prior = revenues[:-3]
    recent = revenues[-3:]
    prior_avg = sum(prior) / len(prior) if prior else None
    recent_avg = sum(recent) / len(recent) if recent else None
    trend = (recent_avg / prior_avg - 1) if prior_avg and recent_avg is not None else None
    return {
        "统计月份起": rows[0].get("月份", "") if rows else "",
        "统计月份止": rows[-1].get("月份", "") if rows else "",
        "有效营收月份数": len(revenues),
        "平均月营收": fmt(sum(revenues) / len(revenues) if revenues else None),
        "最低月营收": fmt(min(revenues) if revenues else None),
        "最高月营收": fmt(max(revenues) if revenues else None),
        "营收变异系数": fmt(coefficient_variation(revenues), 4),
        "近3月平均营收": fmt(recent_avg),
        "近3月较此前变化": fmt(trend, 4),
        "客户指标月份数": min(len(new_values), len(old_values)),
        "平均月新客数": fmt(total_new / len(new_values) if new_values else None),
        "平均月老客数": fmt(total_old / len(old_values) if old_values else None),
        "老客人数占比": fmt(total_old / (total_new + total_old) if total_new + total_old else None, 4),
        "平均留存率": fmt(sum(retention_values) / len(retention_values) if retention_values else None),
        "平均返店频次": fmt(sum(return_values) / len(return_values) if return_values else None),
    }


def build(benchmark_rows: list[dict], monthly_rows: list[dict], episode_rows: list[dict] | None = None) -> list[dict]:
    by_site = defaultdict(list)
    for row in monthly_rows:
        by_site[row.get("点位ID", "")].append(row)
    episode_by_site = {
        row.get("analysis_point_id", ""): row
        for row in (episode_rows or [])
        if row.get("analysis_point_id") and row.get("resolution_status") == "confirmed"
    }
    output = []
    for row in benchmark_rows:
        if row.get("好店经济性Gate") != "经济性达标-待完整验证":
            continue
        start_month = row.get("统计月份起", "")
        end_month = row.get("统计月份止", "")
        comparable_rows = [
            monthly
            for monthly in by_site.get(row.get("点位ID", ""), [])
            if (not start_month or monthly.get("月份", "") >= start_month)
            and (not end_month or monthly.get("月份", "") <= end_month)
        ]
        episode = episode_by_site.get(row.get("点位ID", ""), {})
        relation = episode.get("relation_type", "")
        is_relocation = "换铺" in relation or "迁址" in relation
        output.append(
            {
                "点位ID": row.get("点位ID", ""),
                "门店名称": row.get("门店名称", ""),
                "月租金": row.get("月租金", ""),
                "租售比": row.get("租售比", ""),
                "留存率分位": row.get("留存率分位", ""),
                "返店频次分位": row.get("返店频次分位", ""),
                **build_metrics(comparable_rows),
                "经济性结论": row.get("好店经济性Gate", ""),
                "客户结构结论": "待王凯业务校准",
                "经营波动结论": "待王凯业务校准",
                "完整好店结论": "待验证",
                "样本类型": "迁址/换铺承接样本" if is_relocation else "独立经营点位样本",
                "选址使用限制": "可验证换铺承接，不直接作为全新选址成功证据" if is_relocation else "待结合选址调研验证",
                "口径说明": "老客人数占比不是复购率；复购字段仍需单独确认公式",
            }
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build good-store validation evidence for business review.")
    parser.add_argument("--benchmark", default="data/staging/site_benchmark.csv")
    parser.add_argument("--monthly", default="data/staging/site_performance_monthly_bi_feishu_rent.csv")
    parser.add_argument("--episodes", default="config/site_identity_episodes.json")
    parser.add_argument("--out", default="data/staging/good_store_validation.csv")
    args = parser.parse_args()
    episode_rows = json.loads(Path(args.episodes).read_text(encoding="utf-8"))
    rows = build(read_csv(Path(args.benchmark)), read_csv(Path(args.monthly)), episode_rows)
    fields = list(rows[0].keys()) if rows else ["点位ID", "门店名称"]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {out_path} rows={len(rows)}")


if __name__ == "__main__":
    main()

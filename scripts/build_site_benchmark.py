import argparse
import csv
from collections import defaultdict
from pathlib import Path


SUMMARY = Path("data/staging/site_performance_summary_bi_feishu_rent.csv")
BASE = Path("data/staging/base_table.csv")
OUT = Path("data/staging/site_benchmark.csv")
STATS_OUT = Path("data/staging/site_benchmark_stats.csv")


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))


def num(value) -> float:
    try:
        return float(value) if value not in ("", None) else 0.0
    except ValueError:
        return 0.0


def fmt(value, digits=2) -> str:
    if value in ("", None):
        return ""
    try:
        value = float(value)
    except ValueError:
        return str(value)
    if value == 0:
        return "0"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def percentile(values: list[float], p: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(values) - 1)
    weight = k - lo
    return values[lo] * (1 - weight) + values[hi] * weight


def rank_bucket(value: float, p25: float, p50: float, p75: float, high_good: bool = True) -> str:
    if value <= 0:
        return "无有效值"
    if high_good:
        if value >= p75:
            return "样本前25%"
        if value >= p50:
            return "样本中上"
        if value >= p25:
            return "样本中下"
        return "样本后25%"
    if value <= p25:
        return "样本前25%"
    if value <= p50:
        return "样本中上"
    if value <= p75:
        return "样本中下"
    return "样本后25%"


def rent_ratio_band(ratio: float) -> str:
    if ratio >= 0.5:
        return "异常高压"
    if ratio >= 0.3:
        return "高压"
    if ratio >= 0.2:
        return "关注"
    if ratio >= 0.15:
        return "正常偏高"
    return "健康"


def sample_role(ratio: float, revenue: float, revenue_p50: float, revenue_p75: float, months: int) -> str:
    if months < 6:
        return "观察样本-经营期不足"
    if ratio >= 0.5:
        return "反向样本-极端租金压力"
    if ratio >= 0.3 and revenue < revenue_p50:
        return "反向样本-租金高且营收弱"
    if ratio < 0.18 and revenue >= revenue_p75:
        return "正向样本-高营收低租售比"
    if ratio < 0.22 and revenue >= revenue_p50:
        return "正向样本-经营健康"
    if ratio >= 0.3:
        return "压力样本-租金偏高"
    return "中性样本"


def risk_note(ratio: float, revenue: float, months: int, new_customers: float, therapist_output: float) -> str:
    notes = []
    if months < 6:
        notes.append("有效月份少")
    if ratio >= 0.5:
        notes.append("租售比极高")
    elif ratio >= 0.3:
        notes.append("租售比高")
    if revenue < 100000:
        notes.append("月营收低")
    if new_customers and new_customers < 60:
        notes.append("新客偏弱")
    if therapist_output and therapist_output < 1200:
        notes.append("理疗师日均产值偏低")
    return "、".join(notes) if notes else "无明显异常"


def build(summary_path: Path, base_path: Path, out_path: Path, stats_out: Path) -> None:
    summary_rows = read_csv(summary_path)
    base_rows = read_csv(base_path)
    base_by_id = {row.get("点位ID", ""): row for row in base_rows if row.get("点位ID")}

    rows = [row for row in summary_rows if row.get("分析可用性") == "可用于租售比分析"]
    ratios = [num(row["租售比_按平均月营收"]) for row in rows]
    revenues = [num(row["近12月平均月营收"]) for row in rows]
    rents = [num(row["月租金"]) for row in rows]
    new_customers = [num(row["平均月新客数"]) for row in rows if num(row["平均月新客数"]) > 0]
    therapist_outputs = [num(row["平均理疗师日均产值"]) for row in rows if num(row["平均理疗师日均产值"]) > 0]

    stats = {
        "租售比": ratios,
        "近12月平均月营收": revenues,
        "月租金": rents,
        "平均月新客数": new_customers,
        "平均理疗师日均产值": therapist_outputs,
    }
    thresholds = {
        name: {
            "p25": percentile(values, 0.25),
            "p50": percentile(values, 0.50),
            "p75": percentile(values, 0.75),
        }
        for name, values in stats.items()
    }

    headers = [
        "点位ID",
        "门店名称",
        "城市",
        "门店属性",
        "门店状态",
        "合同开业日期",
        "租赁起始日",
        "门店面积",
        "统计月份起",
        "统计月份止",
        "有效营收月份数",
        "近12月平均月营收",
        "月租金",
        "租售比",
        "平均月新客数",
        "近12月总客数",
        "平均客单价_折扣后",
        "平均理疗师日均产值",
        "租售比分层",
        "营收分位",
        "租金分位",
        "新客分位",
        "理疗师产值分位",
        "样本角色",
        "风险提示",
        "选址使用建议",
    ]

    out = []
    for row in rows:
        site_id = row["点位ID"]
        base = base_by_id.get(site_id, {})
        ratio = num(row["租售比_按平均月营收"])
        revenue = num(row["近12月平均月营收"])
        rent = num(row["月租金"])
        months = int(num(row["有营收月份数"]))
        avg_new = num(row["平均月新客数"])
        therapist_output = num(row["平均理疗师日均产值"])
        role = sample_role(
            ratio,
            revenue,
            thresholds["近12月平均月营收"]["p50"],
            thresholds["近12月平均月营收"]["p75"],
            months,
        )
        if role.startswith("正向"):
            advice = "可作为新点位正向对标"
        elif role.startswith("反向"):
            advice = "用于识别同类风险和租金红线"
        elif role.startswith("压力"):
            advice = "可作为租金压力对标，谨慎直接作为好店样本"
        elif role.startswith("观察"):
            advice = "暂不作为稳定样本，后续补足经营周期"
        else:
            advice = "可作为中位参照样本"
        out.append(
            [
                site_id,
                row["门店名称"],
                row["城市"],
                row["门店属性"],
                row["门店状态"],
                base.get("合同开业日期", ""),
                base.get("租赁起始日", ""),
                fmt(base.get("门店面积", "")),
                row["统计月份起"],
                row["统计月份止"],
                row["有营收月份数"],
                fmt(revenue),
                fmt(rent),
                fmt(ratio, 4),
                fmt(avg_new),
                row["近12月总客数"],
                row["平均客单价_折扣后"],
                row["平均理疗师日均产值"],
                rent_ratio_band(ratio),
                rank_bucket(
                    revenue,
                    thresholds["近12月平均月营收"]["p25"],
                    thresholds["近12月平均月营收"]["p50"],
                    thresholds["近12月平均月营收"]["p75"],
                    high_good=True,
                ),
                rank_bucket(
                    rent,
                    thresholds["月租金"]["p25"],
                    thresholds["月租金"]["p50"],
                    thresholds["月租金"]["p75"],
                    high_good=False,
                ),
                rank_bucket(
                    avg_new,
                    thresholds["平均月新客数"]["p25"],
                    thresholds["平均月新客数"]["p50"],
                    thresholds["平均月新客数"]["p75"],
                    high_good=True,
                ),
                rank_bucket(
                    therapist_output,
                    thresholds["平均理疗师日均产值"]["p25"],
                    thresholds["平均理疗师日均产值"]["p50"],
                    thresholds["平均理疗师日均产值"]["p75"],
                    high_good=True,
                ),
                role,
                risk_note(ratio, revenue, months, avg_new, therapist_output),
                advice,
            ]
        )

    out.sort(key=lambda r: (r[23], -num(r[13]), -num(r[11])))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(out)

    stat_headers = ["指标", "样本数", "P25", "P50_中位数", "P75", "最小值", "最大值"]
    stat_rows = []
    for name, values in stats.items():
        values = [v for v in values if v > 0]
        stat_rows.append(
            [
                name,
                len(values),
                fmt(percentile(values, 0.25), 4 if name == "租售比" else 2),
                fmt(percentile(values, 0.50), 4 if name == "租售比" else 2),
                fmt(percentile(values, 0.75), 4 if name == "租售比" else 2),
                fmt(min(values), 4 if name == "租售比" else 2),
                fmt(max(values), 4 if name == "租售比" else 2),
            ]
        )
    with stats_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(stat_headers)
        writer.writerows(stat_rows)

    role_counts = defaultdict(int)
    band_counts = defaultdict(int)
    for row in out:
        band_counts[row[18]] += 1
        role_counts[row[23]] += 1
    print(f"wrote {out_path} rows={len(out)}")
    print(f"wrote {stats_out} rows={len(stat_rows)}")
    print("rent_ratio_bands=" + dict(band_counts).__repr__())
    print("sample_roles=" + dict(role_counts).__repr__())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", default=str(SUMMARY))
    parser.add_argument("--base", default=str(BASE))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--stats-out", default=str(STATS_OUT))
    args = parser.parse_args()
    build(Path(args.summary), Path(args.base), Path(args.out), Path(args.stats_out))


if __name__ == "__main__":
    main()

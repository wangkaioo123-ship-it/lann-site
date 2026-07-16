import argparse
import csv
from collections import defaultdict
from pathlib import Path


RAW = Path("data/staging/ops_monthly_raw_bi.csv")
MAPPING = Path("data/staging/store_month_mapping_review.csv")
BASE = Path("data/staging/base_table.csv")
OUT = Path("data/staging/resilient_site_candidates_2024q4.csv")


FIELDS = [
    "门店名称",
    "点位ID",
    "城市",
    "门店属性",
    "抗跌得分",
    "基准期月均营收",
    "下行期月均营收",
    "营收变化率",
    "基准期月均新客",
    "下行期月均新客",
    "新客变化率",
    "基准期留存率",
    "下行期留存率",
    "留存率变化",
    "基准期储值转化率",
    "下行期储值转化率",
    "储值转化率变化",
    "基准期折扣前客单",
    "下行期折扣前客单",
    "折扣前客单变化率",
    "基准期理疗师日均产值",
    "下行期理疗师日均产值",
    "抗跌标签",
]


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
    if abs(value) < 0.000001:
        return "0"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def pct(value) -> str:
    return fmt(value * 100, 2) + "%"


def period(month: str) -> str:
    if "2024-04" <= month <= "2024-09":
        return "base"
    if "2024-10" <= month <= "2025-12":
        return "downturn"
    return ""


def weighted_avg(rows: list[dict], field: str, weight_field: str) -> float:
    total_weight = sum(num(row.get(weight_field)) for row in rows)
    if total_weight <= 0:
        values = [num(row.get(field)) for row in rows if num(row.get(field)) > 0]
        return sum(values) / len(values) if values else 0.0
    return sum(num(row.get(field)) * num(row.get(weight_field)) for row in rows) / total_weight


def avg(rows: list[dict], field: str) -> float:
    if not rows:
        return 0.0
    return sum(num(row.get(field)) for row in rows) / len(rows)


def calc(rows: list[dict]) -> dict:
    return {
        "months": len(rows),
        "revenue": avg(rows, "real_income_with_marketing"),
        "new_customers": avg(rows, "new_customer_count"),
        "retention": weighted_avg(rows, "retention_rate", "old_customer_count"),
        "stored_conversion": weighted_avg(rows, "stored_member_conversion_rate", "new_customer_count"),
        "before_ticket": weighted_avg(rows, "per_customer_before_discount", "order_customer_times"),
        "therapist_output": weighted_avg(rows, "therapist_daily_output", "therapist_workdays"),
    }


def label(row: dict) -> str:
    revenue_change = row["revenue_change"]
    new_change = row["new_change"]
    retention_change = row["retention_change"]
    conversion_change = row["conversion_change"]
    if revenue_change >= 0 and new_change >= 0:
        return "逆势增长-营收新客双升"
    if revenue_change >= 0:
        return "逆势增长-营收稳定上升"
    if revenue_change >= -0.05 and (new_change >= 0 or retention_change >= 0 or conversion_change >= 0):
        return "抗跌稳定-轻微下滑但客群指标支撑"
    if revenue_change >= -0.10:
        return "抗跌观察-营收小幅下滑"
    return "非抗跌样本"


def build(raw_path: Path, mapping_path: Path, base_path: Path) -> list[dict]:
    raw_rows = read_csv(raw_path)
    mapping_rows = read_csv(mapping_path)
    base_rows = read_csv(base_path)

    store_to_site = {}
    excluded = set()
    for row in mapping_rows:
        store = row.get("Hanson门店名称", "")
        site_id = (row.get("确认点位ID") or "").strip()
        if site_id == "排除":
            excluded.add(store)
        elif site_id:
            store_to_site[store] = site_id

    base_by_site = {row.get("点位ID", ""): row for row in base_rows if row.get("点位ID")}
    grouped = defaultdict(lambda: defaultdict(list))
    for row in raw_rows:
        store = row.get("store_name", "")
        month = row.get("data_month", "")
        if store in excluded or store not in store_to_site:
            continue
        if num(row.get("real_income_with_marketing")) <= 0:
            continue
        phase = period(month)
        if not phase:
            continue
        grouped[store][phase].append(row)

    out = []
    for store, phases in grouped.items():
        if len(phases["base"]) < 4 or len(phases["downturn"]) < 9:
            continue
        base = calc(phases["base"])
        downturn = calc(phases["downturn"])
        if base["revenue"] <= 0:
            continue
        revenue_change = downturn["revenue"] / base["revenue"] - 1
        new_change = downturn["new_customers"] / base["new_customers"] - 1 if base["new_customers"] else 0.0
        ticket_change = downturn["before_ticket"] / base["before_ticket"] - 1 if base["before_ticket"] else 0.0
        retention_change = downturn["retention"] - base["retention"]
        conversion_change = downturn["stored_conversion"] - base["stored_conversion"]
        score = (
            revenue_change * 0.45
            + new_change * 0.25
            + (retention_change / 100) * 0.15
            + (conversion_change / 100) * 0.10
            + ticket_change * 0.05
        )
        site_id = store_to_site[store]
        site = base_by_site.get(site_id, {})
        item = {
            "门店名称": site.get("门店名称", store),
            "点位ID": site_id,
            "城市": site.get("城市", ""),
            "门店属性": site.get("门店属性", ""),
            "抗跌得分": fmt(score, 4),
            "基准期月均营收": fmt(base["revenue"]),
            "下行期月均营收": fmt(downturn["revenue"]),
            "营收变化率": pct(revenue_change),
            "基准期月均新客": fmt(base["new_customers"]),
            "下行期月均新客": fmt(downturn["new_customers"]),
            "新客变化率": pct(new_change),
            "基准期留存率": fmt(base["retention"]),
            "下行期留存率": fmt(downturn["retention"]),
            "留存率变化": fmt(retention_change),
            "基准期储值转化率": fmt(base["stored_conversion"]),
            "下行期储值转化率": fmt(downturn["stored_conversion"]),
            "储值转化率变化": fmt(conversion_change),
            "基准期折扣前客单": fmt(base["before_ticket"]),
            "下行期折扣前客单": fmt(downturn["before_ticket"]),
            "折扣前客单变化率": pct(ticket_change),
            "基准期理疗师日均产值": fmt(base["therapist_output"]),
            "下行期理疗师日均产值": fmt(downturn["therapist_output"]),
            "_score": score,
            "revenue_change": revenue_change,
            "new_change": new_change,
            "retention_change": retention_change,
            "conversion_change": conversion_change,
        }
        item["抗跌标签"] = label(item)
        out.append(item)
    out.sort(key=lambda row: row["_score"], reverse=True)
    return out


def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", default=str(RAW))
    parser.add_argument("--mapping", default=str(MAPPING))
    parser.add_argument("--base", default=str(BASE))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    rows = build(Path(args.raw), Path(args.mapping), Path(args.base))
    write(Path(args.out), rows)
    print(f"wrote {args.out} rows={len(rows)}")
    for row in rows[:20]:
        print(
            row["门店名称"],
            row["城市"],
            row["抗跌标签"],
            row["营收变化率"],
            row["新客变化率"],
            row["下行期月均营收"],
        )


if __name__ == "__main__":
    main()

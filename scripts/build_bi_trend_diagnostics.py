import argparse
import csv
from collections import defaultdict
from pathlib import Path

from config import settings


RAW = Path("data/staging/ops_monthly_raw_bi.csv")
MAPPING = Path("data/staging/store_month_mapping_review.csv")
MONTHLY_OUT = Path("data/staging/bi_trend_monthly_2023_2025.csv")
QUARTERLY_OUT = Path("data/staging/bi_trend_quarterly_2023_2025.csv")
ANNUAL_OUT = Path("data/staging/bi_trend_annual_2023_2025.csv")


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


def load_mapping(path: Path) -> tuple[dict[str, str], set[str]]:
    rows = read_csv(path)
    store_to_site = {}
    excluded = set()
    for row in rows:
        store = row.get("Hanson门店名称", "")
        site_id = (row.get("确认点位ID") or "").strip()
        if site_id == "排除":
            excluded.add(store)
        elif site_id:
            store_to_site[store] = site_id
    return store_to_site, excluded


def weighted_avg(numerators: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in numerators if weight > 0)
    if total_weight <= 0:
        values = [value for value, _ in numerators if value > 0]
        return sum(values) / len(values) if values else 0.0
    return sum(value * weight for value, weight in numerators if weight > 0) / total_weight


def quarter_of(month: str) -> str:
    year, month_num = month.split("-")
    q = (int(month_num) - 1) // 3 + 1
    return f"{year}Q{q}"


class Agg:
    def __init__(self):
        self.rows = []

    def add(self, row: dict):
        self.rows.append(row)

    def result(self, period: str) -> dict:
        rows = self.rows
        active = [row for row in rows if num(row.get("real_income_with_marketing")) > 0]
        revenue = sum(num(row.get("real_income_with_marketing")) for row in active)
        cash_flow = sum(num(row.get("cash_flow")) for row in active)
        open_card_income = sum(num(row.get("open_card_income")) for row in active)
        new_customers = sum(num(row.get("new_customer_count")) for row in active)
        old_customers = sum(num(row.get("old_customer_count")) for row in active)
        order_times = sum(num(row.get("order_customer_times")) for row in active)
        open_card_people = sum(num(row.get("open_card_people")) for row in active)
        point_count = sum(num(row.get("point_count")) for row in active)
        therapist_workdays = sum(num(row.get("therapist_workdays")) for row in active)
        stores = {row.get("store_name", "") for row in active if row.get("store_name")}

        before_ticket = weighted_avg(
            [(num(row.get("per_customer_before_discount")), num(row.get("order_customer_times"))) for row in active]
        )
        after_ticket = weighted_avg(
            [(num(row.get("per_customer_after_discount")), num(row.get("order_customer_times"))) for row in active]
        )
        new_before_ticket = weighted_avg(
            [(num(row.get("new_per_customer_before_discount")), num(row.get("new_customer_count"))) for row in active]
        )
        retention = weighted_avg(
            [(num(row.get("retention_rate")), num(row.get("old_customer_count"))) for row in active]
        )
        second_store = weighted_avg(
            [(num(row.get("second_store_rate")), num(row.get("old_customer_count"))) for row in active]
        )
        return_frequency = weighted_avg(
            [(num(row.get("return_store_frequency")), num(row.get("old_customer_count"))) for row in active]
        )
        stored_conversion = weighted_avg(
            [(num(row.get("stored_member_conversion_rate")), num(row.get("new_customer_count"))) for row in active]
        )
        therapist_output = weighted_avg(
            [(num(row.get("therapist_daily_output")), num(row.get("therapist_workdays"))) for row in active]
        )
        therapist_productivity = weighted_avg(
            [(num(row.get("therapist_production_rate")), num(row.get("therapist_workdays"))) for row in active]
        )

        return {
            "周期": period,
            "活跃门店数": len(stores),
            "活跃门店月数": len(active),
            "实际营收": fmt(revenue),
            "现金流": fmt(cash_flow),
            "开卡收入": fmt(open_card_income),
            "新客数": fmt(new_customers),
            "老客数": fmt(old_customers),
            "订单客次": fmt(order_times),
            "折扣前客单价": fmt(before_ticket),
            "折扣后客单价": fmt(after_ticket),
            "新客折扣前客单价": fmt(new_before_ticket),
            "留存率": fmt(retention),
            "二次到店率": fmt(second_store),
            "返店频次": fmt(return_frequency, 4),
            "开卡人次": fmt(open_card_people),
            "新客开卡人次比": fmt(open_card_people / new_customers * 100 if new_customers else 0),
            "储值会员转化率": fmt(stored_conversion),
            "点钟数": fmt(point_count),
            "理疗师工作人天": fmt(therapist_workdays),
            "理疗师日均产值": fmt(therapist_output),
            "理疗师生产率": fmt(therapist_productivity),
        }


FIELDS = [
    "周期",
    "活跃门店数",
    "活跃门店月数",
    "实际营收",
    "现金流",
    "开卡收入",
    "新客数",
    "老客数",
    "订单客次",
    "折扣前客单价",
    "折扣后客单价",
    "新客折扣前客单价",
    "留存率",
    "二次到店率",
    "返店频次",
    "开卡人次",
    "新客开卡人次比",
    "储值会员转化率",
    "点钟数",
    "理疗师工作人天",
    "理疗师日均产值",
    "理疗师生产率",
]


def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(raw_path: Path, mapping_path: Path, start_year: int, end_year: int) -> tuple[list[dict], list[dict], list[dict]]:
    store_to_site, excluded = load_mapping(mapping_path)
    raw_rows = read_csv(raw_path)
    monthly = defaultdict(Agg)
    quarterly = defaultdict(Agg)
    annual = defaultdict(Agg)

    for row in raw_rows:
        store = row.get("store_name", "")
        month = row.get("data_month", "")
        if not month or store in excluded or store not in store_to_site:
            continue
        year = int(month[:4])
        if year < start_year or year > end_year:
            continue
        monthly[month].add(row)
        quarterly[quarter_of(month)].add(row)
        annual[str(year)].add(row)

    monthly_rows = [monthly[key].result(key) for key in sorted(monthly)]
    quarterly_rows = [quarterly[key].result(key) for key in sorted(quarterly)]
    annual_rows = [annual[key].result(key) for key in sorted(annual)]
    return monthly_rows, quarterly_rows, annual_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", default=str(RAW))
    parser.add_argument("--mapping", default=str(MAPPING))
    parser.add_argument("--start-year", type=int, default=2023)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--monthly-out", default=str(MONTHLY_OUT))
    parser.add_argument("--quarterly-out", default=str(QUARTERLY_OUT))
    parser.add_argument("--annual-out", default=str(ANNUAL_OUT))
    args = parser.parse_args()

    monthly, quarterly, annual = build(
        settings.ROOT_DIR / args.raw,
        settings.ROOT_DIR / args.mapping,
        args.start_year,
        args.end_year,
    )
    write(settings.ROOT_DIR / args.monthly_out, monthly)
    write(settings.ROOT_DIR / args.quarterly_out, quarterly)
    write(settings.ROOT_DIR / args.annual_out, annual)
    print(f"monthly rows={len(monthly)} -> {args.monthly_out}")
    print(f"quarterly rows={len(quarterly)} -> {args.quarterly_out}")
    print(f"annual rows={len(annual)} -> {args.annual_out}")
    for row in annual:
        print(row)


if __name__ == "__main__":
    main()

"""Read-only BI freshness probe. Prints aggregate metadata only, never row-level business data."""

import argparse

from services import bi_client


def query(database: int, sql: str) -> dict:
    payload = {
        "database": database,
        "type": "native",
        "native": {"query": sql},
        "constraints": {"max-results": 10, "max-results-bare-rows": 10},
    }
    response = bi_client.post("/api/dataset", payload)
    response.raise_for_status()
    data = response.json().get("data", {})
    headers = [column.get("name") or column.get("display_name") or "" for column in data.get("cols", [])]
    rows = data.get("rows", [])
    values = dict(zip(headers, rows[0] if rows else []))
    return values


def print_values(source: str, values: dict) -> None:
    print(source, " ".join(f"{key}={value}" for key, value in values.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe aggregate freshness for approved BI sources.")
    parser.add_argument("--candidates", action="store_true", help="Also probe potential daily operating sources.")
    args = parser.parse_args()

    monthly = query(
        3,
        "SELECT MIN(`data_month`) AS min_month, MAX(`data_month`) AS max_month, "
        "COUNT(*) AS row_count, COUNT(DISTINCT `store_id`) AS store_count "
        "FROM `report_store_month_indicator_export`",
    )
    print_values("monthly_indicator", monthly)

    if args.candidates:
        copilot_daily = query(
            3,
            "SELECT MIN(`data_date`) AS min_date, MAX(`data_date`) AS max_date, "
            "COUNT(*) AS row_count, COUNT(DISTINCT `store_id`) AS store_count, "
            "COUNT(DISTINCT `indicator_id`) AS indicator_count FROM `copilot_indicator_day_data`",
        )
        print_values("copilot_indicator_daily", copilot_daily)

        day_check = query(
            2,
            "SELECT MIN(s.`DAY_CHECK_DATE`) AS min_date, MAX(s.`DAY_CHECK_DATE`) AS max_date, "
            "COUNT(*) AS row_count, COUNT(DISTINCT s.`STORE_ID`) AS store_count "
            "FROM `store_day_check` s JOIN `store_day_check_general_data` g ON g.`day_check_id` = s.`id`",
        )
        print_values("store_day_check_revenue", day_check)


if __name__ == "__main__":
    main()

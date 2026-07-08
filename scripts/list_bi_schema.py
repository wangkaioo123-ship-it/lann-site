import csv

from config import settings
from services import bi_client


KEYWORDS = (
    "store",
    "shop",
    "site",
    "revenue",
    "income",
    "order",
    "sales",
    "month",
    "date",
    "门店",
    "店铺",
    "收入",
    "营收",
    "营业",
    "订单",
    "月份",
    "日期",
)


def text_hit(*values) -> bool:
    text = " ".join(str(value or "").lower() for value in values)
    return any(keyword.lower() in text for keyword in KEYWORDS)


def main():
    if not settings.BI_API_BASE_URL:
        raise RuntimeError("Missing BI_API_BASE_URL in .env")

    db_resp = bi_client.get("/api/database")
    db_resp.raise_for_status()
    dbs = db_resp.json().get("data", [])

    db_out = settings.ROOT_DIR / "data" / "staging" / "bi_databases.csv"
    table_out = settings.ROOT_DIR / "data" / "staging" / "bi_tables.csv"
    field_out = settings.ROOT_DIR / "data" / "staging" / "bi_fields.csv"
    db_out.parent.mkdir(parents=True, exist_ok=True)

    with db_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "engine", "is_sample"])
        writer.writeheader()
        for db in dbs:
            writer.writerow(
                {
                    "id": db.get("id", ""),
                    "name": db.get("name", ""),
                    "engine": db.get("engine", ""),
                    "is_sample": db.get("is_sample", ""),
                }
            )

    table_rows = []
    field_rows = []
    for db in dbs:
        db_id = db.get("id")
        if not db_id:
            continue
        meta_resp = bi_client.get(f"/api/database/{db_id}/metadata")
        if meta_resp.status_code != 200:
            table_rows.append(
                {
                    "database_id": db_id,
                    "database_name": db.get("name", ""),
                    "table_id": "",
                    "schema": "",
                    "table_name": "",
                    "display_name": "",
                    "field_count": "",
                    "status": f"metadata_status_{meta_resp.status_code}",
                }
            )
            continue
        tables = meta_resp.json().get("tables", [])
        for table in tables:
            fields = table.get("fields") or []
            table_row = {
                "database_id": db_id,
                "database_name": db.get("name", ""),
                "table_id": table.get("id", ""),
                "schema": table.get("schema", ""),
                "table_name": table.get("name", ""),
                "display_name": table.get("display_name", ""),
                "field_count": len(fields),
                "status": "ok",
            }
            table_rows.append(table_row)
            for field in fields:
                field_rows.append(
                    {
                        "database_id": db_id,
                        "database_name": db.get("name", ""),
                        "table_id": table.get("id", ""),
                        "table_name": table.get("name", ""),
                        "field_id": field.get("id", ""),
                        "field_name": field.get("name", ""),
                        "display_name": field.get("display_name", ""),
                        "base_type": field.get("base_type", ""),
                        "semantic_type": field.get("semantic_type", ""),
                    }
                )

    with table_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "database_id",
                "database_name",
                "table_id",
                "schema",
                "table_name",
                "display_name",
                "field_count",
                "status",
            ],
        )
        writer.writeheader()
        writer.writerows(table_rows)

    with field_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "database_id",
                "database_name",
                "table_id",
                "table_name",
                "field_id",
                "field_name",
                "display_name",
                "base_type",
                "semantic_type",
            ],
        )
        writer.writeheader()
        writer.writerows(field_rows)

    print(f"wrote {db_out} rows={len(dbs)}")
    print(f"wrote {table_out} rows={len(table_rows)}")
    print(f"wrote {field_out} rows={len(field_rows)}")
    print("\ncandidate tables:")
    for row in table_rows:
        if row["status"] == "ok" and text_hit(row["table_name"], row["display_name"]):
            print(
                f"db={row['database_id']} table={row['table_id']} "
                f"name={row['table_name']} display={row['display_name']} fields={row['field_count']}"
            )

    print("\ncandidate fields:")
    for row in field_rows:
        if text_hit(row["table_name"], row["field_name"], row["display_name"]):
            print(
                f"db={row['database_id']} table={row['table_id']} "
                f"table_name={row['table_name']} field={row['field_name']} display={row['display_name']}"
            )


if __name__ == "__main__":
    main()

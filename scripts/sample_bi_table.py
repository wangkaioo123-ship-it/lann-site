import argparse
import csv

from config import settings
from services import bi_client


def main():
    parser = argparse.ArgumentParser(description="Sample rows from a Metabase table.")
    parser.add_argument("--database-id", type=int, required=True)
    parser.add_argument("--table-id", type=int, required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    payload = {
        "database": args.database_id,
        "type": "query",
        "query": {
            "source-table": args.table_id,
            "limit": args.limit,
        },
    }
    resp = bi_client.post("/api/dataset", payload)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    cols = data.get("cols", [])
    rows = data.get("rows", [])
    headers = [col.get("name") or col.get("display_name") or "" for col in cols]

    out = (
        settings.ROOT_DIR
        / "data"
        / "staging"
        / f"bi_table_{args.table_id}_sample.csv"
    )
    if args.out:
        out = settings.ROOT_DIR / args.out
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    print(f"wrote {out} rows={len(rows)} cols={len(headers)}")
    print(",".join(headers))


if __name__ == "__main__":
    main()

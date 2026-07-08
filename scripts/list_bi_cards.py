import csv

from config import settings
from services import bi_client


def main():
    if not settings.BI_API_BASE_URL:
        raise RuntimeError("Missing BI_API_BASE_URL in .env")

    resp = bi_client.get("/api/card")
    resp.raise_for_status()
    cards = resp.json()
    if not isinstance(cards, list):
        raise RuntimeError("Unexpected /api/card response")

    out = settings.ROOT_DIR / "data" / "staging" / "bi_cards.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "id",
        "name",
        "collection_id",
        "collection_name",
        "database_id",
        "table_id",
        "query_type",
        "display",
        "archived",
        "updated_at",
    ]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for card in cards:
            collection = card.get("collection") or {}
            writer.writerow(
                {
                    "id": card.get("id", ""),
                    "name": card.get("name", ""),
                    "collection_id": card.get("collection_id", ""),
                    "collection_name": collection.get("name", ""),
                    "database_id": card.get("database_id", ""),
                    "table_id": card.get("table_id", ""),
                    "query_type": card.get("query_type", ""),
                    "display": card.get("display", ""),
                    "archived": card.get("archived", ""),
                    "updated_at": card.get("updated_at", ""),
                }
            )

    print(f"wrote {out} rows={len(cards)}")
    for card in cards:
        name = str(card.get("name", ""))
        if any(key in name for key in ("营收", "营业", "收入", "门店", "月", "经营")):
            print(
                f"id={card.get('id')} name={name} "
                f"collection={(card.get('collection') or {}).get('name', '')} "
                f"query_type={card.get('query_type', '')}"
            )


if __name__ == "__main__":
    main()

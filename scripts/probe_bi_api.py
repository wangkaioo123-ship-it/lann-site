import argparse
import json

from config import settings
from services import bi_client


def print_info(title: str, info: dict) -> None:
    print(f"\n== {title} ==")
    print(json.dumps(info, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Probe BI API shape without printing secrets.")
    parser.add_argument("--path", default="", help="API path to test. Defaults to BI_API_TEST_PATH.")
    parser.add_argument("--revenue", action="store_true", help="Probe BI_API_REVENUE_PATH.")
    args = parser.parse_args()

    if not settings.BI_API_BASE_URL:
        raise RuntimeError("Missing BI_API_BASE_URL in .env")

    if args.revenue:
        path = settings.BI_API_REVENUE_PATH
        if not path:
            raise RuntimeError("Missing BI_API_REVENUE_PATH in .env")
        title = "revenue path"
    else:
        path = args.path or settings.BI_API_TEST_PATH or "/"
        title = "test path"

    resp = bi_client.get(path)
    print_info(title, bi_client.describe_response(resp))


if __name__ == "__main__":
    main()

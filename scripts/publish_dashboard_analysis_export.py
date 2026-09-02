"""Publish the latest successful Site analysis to the dedicated Dashboard export root."""

from __future__ import annotations

import argparse
import json

from services.dashboard_analysis_export import (
    DEFAULT_EXPORT_ROOT,
    DEFAULT_SOURCE_ROOT,
    DEFAULT_SUMMARY_PATH,
    publish_dashboard_analysis_export,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    parser.add_argument("--export-root", default=str(DEFAULT_EXPORT_ROOT))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY_PATH))
    args = parser.parse_args()
    manifest = publish_dashboard_analysis_export(
        source_root=args.source_root,
        export_root=args.export_root,
        summary_path=args.summary,
    )
    print(
        json.dumps(
            {
                "status": "published",
                "schema_version": manifest["schema_version"],
                "run_month": manifest["source_run"]["run_month"],
                "run_id": manifest["source_run"]["run_id"],
                "dashboard_write_allowed": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()


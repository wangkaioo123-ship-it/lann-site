"""Run franchise review from a verified remote lann-data package."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from requests.exceptions import SSLError

from scripts.build_franchise_operating_review import WORKFORCE_CONTRACT, build, run_auto_backfill
from services.dashboard_analysis_export import publish_dashboard_analysis_export
from services.remote_data_package import (
    PackageIntegrityError,
    RemoteDataPackageError,
    atomic_write_json,
    load_latest_success,
    sync_remote_data_package,
)


DEFAULT_INPUT_ROOT = Path("/var/lib/lann-site/remote-data")
DEFAULT_OUTPUT_ROOT = Path("/var/lib/lann-site/output/franchise_operating_reviews")
DEFAULT_DASHBOARD_EXPORT_ROOT = Path("/var/lib/lann-site/output/dashboard-v0.1")
STATUS_SCHEMA_VERSION = "lann-site-remote-review-status/v1"


class DataGateBlockedError(RemoteDataPackageError):
    pass


def safe_transport_error(error):
    return re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?<redacted>", str(error))[:500]


def acquire_package(manifest_url, input_root, token_file=None, sync_function=sync_remote_data_package):
    try:
        pointer = sync_function(manifest_url, input_root, token_file=token_file)
        return pointer, "fresh", None
    except (PackageIntegrityError, RemoteDataPackageError):
        raise
    except SSLError as error:
        raise RemoteDataPackageError("远程数据包 TLS 校验失败，已拒绝使用旧缓存掩盖") from error
    except Exception as error:
        pointer = load_latest_success(input_root)
        return pointer, "fallback_last_success", safe_transport_error(error)


def execute(
    manifest_url,
    input_root=DEFAULT_INPUT_ROOT,
    output_root=DEFAULT_OUTPUT_ROOT,
    token_file=None,
    target_month=None,
    auto_backfill_from="2026-06",
    workforce_contract=WORKFORCE_CONTRACT,
    dashboard_export_root=DEFAULT_DASHBOARD_EXPORT_ROOT,
    publish_function=publish_dashboard_analysis_export,
    now=None,
):
    now = now or datetime.now(timezone.utc)
    input_root = Path(input_root)
    output_root = Path(output_root)
    status_path = output_root / "remote_run_status.json"
    status = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "started_at": now.isoformat(),
        "finished_at": None,
        "status": "running",
        "sync_status": None,
        "sync_error": None,
        "package": None,
        "review": None,
        "dashboard_export": None,
    }
    atomic_write_json(status_path, status)
    try:
        pointer, sync_status, sync_error = acquire_package(manifest_url, input_root, token_file)
        status["sync_status"] = sync_status
        status["sync_error"] = sync_error
        status["package"] = {
            key: pointer.get(key)
            for key in ("package_id", "data_period", "generated_at", "source_commit", "manifest_sha256")
        }
        operating_path = pointer["role_paths"]["operating_monthly"]
        workforce_path = pointer["role_paths"]["workforce_monthly"]
        if target_month:
            manifest, run_dir, duplicate = build(
                operating_path=operating_path,
                workforce_path=workforce_path,
                output_root=output_root,
                target_month=target_month,
                workforce_contract=workforce_contract,
                now=now,
            )
            backfill_status = None
        else:
            manifest, run_dir, duplicate, backfill_status = run_auto_backfill(
                operating_path=operating_path,
                workforce_path=workforce_path,
                output_root=output_root,
                start_month=auto_backfill_from,
                workforce_contract=workforce_contract,
                now=now,
            )
        status["review"] = {
            "run_id": manifest.get("run_id"),
            "run_month": manifest.get("run_month"),
            "run_status": manifest.get("status"),
            "run_path": str(run_dir),
            "duplicate_input": duplicate,
            "auto_backfill": backfill_status,
        }
        if manifest.get("status") != "ready_for_business_review":
            status["status"] = "blocked_by_data_gate"
            raise DataGateBlockedError("Site 数据 Gate 未通过")
        export_manifest = publish_function(
            source_root=output_root,
            export_root=dashboard_export_root,
            summary_path=None,
            source_data={
                "sync_status": sync_status,
                "stale": sync_status == "fallback_last_success",
                "package_id": pointer.get("package_id"),
                "data_period": pointer.get("data_period"),
                "generated_at": pointer.get("generated_at"),
                "manifest_sha256": pointer.get("manifest_sha256"),
            },
            now=now,
        )
        status["dashboard_export"] = {
            "schema_version": export_manifest.get("schema_version"),
            "run_month": (export_manifest.get("source_run") or {}).get("run_month"),
            "run_id": (export_manifest.get("source_run") or {}).get("run_id"),
            "stale": (export_manifest.get("source_data") or {}).get("stale"),
            "dashboard_write_allowed": export_manifest.get("dashboard_write_allowed"),
        }
        status["status"] = "success_stale_data" if sync_status == "fallback_last_success" else "success"
        return status
    except DataGateBlockedError as error:
        status["status"] = "blocked_by_data_gate"
        status["failure"] = str(error)
        raise
    except Exception as error:
        status["status"] = "failed"
        status["failure"] = str(error)
        raise
    finally:
        status["finished_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(status_path, status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-url", default=os.getenv("LANN_DATA_PACKAGE_MANIFEST_URL"))
    parser.add_argument("--token-file", default=os.getenv("LANN_DATA_PACKAGE_TOKEN_FILE"))
    parser.add_argument("--input-root", default=os.getenv("LANN_SITE_REMOTE_INPUT_ROOT", str(DEFAULT_INPUT_ROOT)))
    parser.add_argument("--output-root", default=os.getenv("LANN_FRANCHISE_OPERATING_REVIEW_ROOT", str(DEFAULT_OUTPUT_ROOT)))
    parser.add_argument(
        "--dashboard-export-root",
        default=os.getenv("LANN_SITE_DASHBOARD_EXPORT_ROOT", str(DEFAULT_DASHBOARD_EXPORT_ROOT)),
    )
    parser.add_argument("--month")
    parser.add_argument("--auto-backfill-from", default="2026-06")
    parser.add_argument("--workforce-contract", default=str(WORKFORCE_CONTRACT))
    args = parser.parse_args()
    if not args.manifest_url:
        parser.error("缺少 --manifest-url 或 LANN_DATA_PACKAGE_MANIFEST_URL")
    status = execute(
        manifest_url=args.manifest_url,
        input_root=args.input_root,
        output_root=args.output_root,
        token_file=args.token_file,
        target_month=args.month,
        auto_backfill_from=args.auto_backfill_from,
        workforce_contract=args.workforce_contract,
        dashboard_export_root=args.dashboard_export_root,
    )
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

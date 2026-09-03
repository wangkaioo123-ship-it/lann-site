"""Publish a minimal immutable Site analysis bundle for read-only Dashboard pull."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from services.franchise_operating_review import REVIEW_SCHEMA_VERSION
from services.franchise_review_display import (
    BUSINESS_REVIEW_SCHEMA_VERSION,
    THREE_MONTH_OPERATING_SCHEMA_VERSION,
)
from services.professional_analysis import (
    ANALYSIS_CATALOG_SCHEMA_VERSION,
    ANALYSIS_RECORD_SCHEMA_VERSION,
    validate_analysis_catalog,
)


EXPORT_SCHEMA_VERSION = "site-dashboard-analysis-export/v0.1"
POINTER_SCHEMA_VERSION = "site-dashboard-analysis-pointer/v0.1"
RUN_SCHEMA_VERSION = "franchise-operating-run/v0.1"
DEFAULT_SOURCE_ROOT = Path("data/staging/franchise_operating_reviews")
DEFAULT_EXPORT_ROOT = Path("data/exports/dashboard-v0.1")
DEFAULT_SUMMARY_PATH = Path("data/staging/site_performance_summary_bi_feishu_rent.csv")
SUMMARY_FILE_NAME = "site_performance_summary_bi_feishu_rent.csv"
RUN_FILE_KEYS = {
    "manifest": "manifest.json",
    "business_review_json": "business_review.json",
    "analysis_catalog_json": "analysis_catalog.json",
    "review_json": "review.json",
}
MONTH_PATTERN = re.compile(r"^20\d{2}-(0[1-9]|1[0-2])$")
RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{8,64}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class DashboardAnalysisExportError(ValueError):
    """Raised when a Site output cannot be safely published."""


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DashboardAnalysisExportError(f"无法读取合法 JSON：{path}") from error
    if not isinstance(payload, dict):
        raise DashboardAnalysisExportError(f"JSON 根节点必须为对象：{path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, payload: dict) -> None:
    _atomic_bytes(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _publish_immutable(source: Path, target: Path) -> None:
    source_hash = _sha256(source)
    if target.is_symlink():
        raise DashboardAnalysisExportError(f"导出目标不得为符号链接：{target}")
    if target.is_file():
        if _sha256(target) != source_hash:
            raise DashboardAnalysisExportError(
                f"相同 run 的导出文件内容发生变化，拒绝覆盖：{target.name}"
            )
        return
    if target.exists():
        raise DashboardAnalysisExportError(f"导出目标不是普通文件：{target}")
    _atomic_bytes(target, source.read_bytes())


def _safe_run_root(source_root: Path, run_month: str, run_id: str) -> Path:
    source_root = source_root.resolve()
    run_root = (source_root / run_month / run_id).resolve()
    if source_root not in run_root.parents:
        raise DashboardAnalysisExportError("最新成功指针越出经营评审目录")
    return run_root


def _validate_pointer(pointer: dict) -> tuple[str, str]:
    run_month = str(pointer.get("run_month") or "")
    run_id = str(pointer.get("run_id") or "")
    if not MONTH_PATTERN.fullmatch(run_month):
        raise DashboardAnalysisExportError("最新成功月份格式非法")
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise DashboardAnalysisExportError("最新成功 run_id 格式非法")
    if pointer.get("status") not in {None, "ready_for_business_review"}:
        raise DashboardAnalysisExportError("最新成功指针并非可供业务评审状态")
    return run_month, run_id


def _require_read_only_ready(payload: dict, label: str, run_month: str) -> None:
    if payload.get("status") != "ready_for_business_review":
        raise DashboardAnalysisExportError(f"{label}未通过业务评审 Gate")
    if payload.get("dashboard_write_allowed") is not False:
        raise DashboardAnalysisExportError(f"{label}必须保持 dashboard_write_allowed=false")
    if payload.get("target_month") not in {None, run_month}:
        raise DashboardAnalysisExportError(f"{label}月份与最新成功指针不一致")


def _normalize_source_data(source_data: dict | None) -> dict | None:
    if source_data is None:
        return None
    if not isinstance(source_data, dict):
        raise DashboardAnalysisExportError("Data 来源状态必须为对象")
    sync_status = source_data.get("sync_status")
    if sync_status not in {"fresh", "fallback_last_success"}:
        raise DashboardAnalysisExportError("Data 来源状态非法")
    stale = source_data.get("stale")
    if not isinstance(stale, bool) or stale != (sync_status == "fallback_last_success"):
        raise DashboardAnalysisExportError("Data 新鲜度与同步状态不一致")
    data_period = str(source_data.get("data_period") or "")
    if not MONTH_PATTERN.fullmatch(data_period):
        raise DashboardAnalysisExportError("Data 数据期间格式非法")
    generated_at = str(source_data.get("generated_at") or "")
    try:
        parsed_generated_at = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise DashboardAnalysisExportError("Data 生成时间格式非法") from error
    if parsed_generated_at.tzinfo is None:
        raise DashboardAnalysisExportError("Data 生成时间必须包含时区")
    package_id = str(source_data.get("package_id") or "")
    if not package_id or "/" in package_id or "\\" in package_id:
        raise DashboardAnalysisExportError("Data package_id 非法")
    manifest_sha256 = str(source_data.get("manifest_sha256") or "")
    if not SHA256_PATTERN.fullmatch(manifest_sha256):
        raise DashboardAnalysisExportError("Data manifest SHA-256 非法")
    return {
        "sync_status": sync_status,
        "stale": stale,
        "package_id": package_id,
        "data_period": data_period,
        "generated_at": generated_at,
        "manifest_sha256": manifest_sha256,
    }


def validate_source_bundle(source_root: str | Path) -> dict:
    """Validate and return the exact allowlisted files for the current successful run."""
    source_root = Path(source_root)
    pointer = _read_json(source_root / "latest_success.json")
    run_month, run_id = _validate_pointer(pointer)
    run_root = _safe_run_root(source_root, run_month, run_id)
    manifest = _read_json(run_root / "manifest.json")

    expected_manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "run_month": run_month,
        "status": "ready_for_business_review",
        "dashboard_write_allowed": False,
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "business_review_schema_version": BUSINESS_REVIEW_SCHEMA_VERSION,
        "three_month_operating_schema_version": THREE_MONTH_OPERATING_SCHEMA_VERSION,
        "analysis_catalog_schema_version": ANALYSIS_CATALOG_SCHEMA_VERSION,
        "analysis_record_schema_version": ANALYSIS_RECORD_SCHEMA_VERSION,
    }
    for key, expected in expected_manifest.items():
        if manifest.get(key) != expected:
            raise DashboardAnalysisExportError(
                f"manifest 字段 {key} 不符合导出契约"
            )

    outputs = manifest.get("outputs") or {}
    for key, expected in RUN_FILE_KEYS.items():
        if key == "manifest":
            continue
        if outputs.get(key) != expected:
            raise DashboardAnalysisExportError(f"manifest 输出 {key} 必须为 {expected}")

    business_review = _read_json(run_root / RUN_FILE_KEYS["business_review_json"])
    if business_review.get("schema_version") != BUSINESS_REVIEW_SCHEMA_VERSION:
        raise DashboardAnalysisExportError("business_review schema 版本不支持")
    _require_read_only_ready(business_review, "business_review", run_month)
    gate = business_review.get("data_gate") or {}
    if not (gate.get("operating") or {}).get("ready"):
        raise DashboardAnalysisExportError("business_review 经营数据 Gate 未通过")
    if not (gate.get("workforce") or {}).get("ready"):
        raise DashboardAnalysisExportError("business_review 人员数据 Gate 未通过")

    review = _read_json(run_root / RUN_FILE_KEYS["review_json"])
    if review.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise DashboardAnalysisExportError("review schema 版本不支持")
    _require_read_only_ready(review, "review", run_month)

    analysis_catalog = _read_json(run_root / RUN_FILE_KEYS["analysis_catalog_json"])
    try:
        validate_analysis_catalog(analysis_catalog)
    except ValueError as error:
        raise DashboardAnalysisExportError(f"analysis_catalog 校验失败：{error}") from error
    if analysis_catalog.get("source_run_id") != run_id:
        raise DashboardAnalysisExportError("analysis_catalog 与 run_id 不一致")

    run_files = {}
    for file_name in RUN_FILE_KEYS.values():
        file_path = run_root / file_name
        if file_path.is_symlink() or not file_path.is_file():
            raise DashboardAnalysisExportError(f"必要 run 文件缺失或为符号链接：{file_name}")
        if run_root.resolve() not in file_path.resolve().parents:
            raise DashboardAnalysisExportError(f"必要 run 文件越出运行目录：{file_name}")
        run_files[file_name] = file_path

    return {
        "run_month": run_month,
        "run_id": run_id,
        "run_root": run_root,
        "manifest": manifest,
        "files": run_files,
    }


def publish_dashboard_analysis_export(
    source_root: str | Path = DEFAULT_SOURCE_ROOT,
    export_root: str | Path = DEFAULT_EXPORT_ROOT,
    summary_path: str | Path | None = DEFAULT_SUMMARY_PATH,
    source_data: dict | None = None,
    now: datetime | None = None,
) -> dict:
    """Publish a minimal pull-only bundle without exposing staging or the repository."""
    source_root = Path(source_root).resolve()
    export_root = Path(export_root).resolve()
    if (
        source_root == export_root
        or source_root in export_root.parents
        or export_root in source_root.parents
    ):
        raise DashboardAnalysisExportError("导出目录与源经营评审目录不得互相包含")

    bundle = validate_source_bundle(source_root)
    normalized_source_data = _normalize_source_data(source_data)
    review_export_root = export_root / "franchise_operating_reviews"
    run_export_root = review_export_root / bundle["run_month"] / bundle["run_id"]
    exported_files = []
    for file_name, source in sorted(bundle["files"].items()):
        target = run_export_root / file_name
        _publish_immutable(source, target)
        exported_files.append(
            {
                "path": target.relative_to(export_root).as_posix(),
                "sha256": _sha256(target),
                "bytes": target.stat().st_size,
            }
        )

    summary = {"status": "not_published", "reason": "source_missing"}
    if summary_path:
        summary_source = Path(summary_path).resolve()
        if (
            summary_source.name != SUMMARY_FILE_NAME
            or summary_source.parent != source_root.parent
        ):
            raise DashboardAnalysisExportError("经营汇总必须是 staging 下的固定正式文件")
        if summary_source.is_file():
            if summary_source.is_symlink():
                raise DashboardAnalysisExportError("经营汇总不得为符号链接")
            summary_target = export_root / SUMMARY_FILE_NAME
            _atomic_bytes(summary_target, summary_source.read_bytes())
            summary = {
                "status": "published",
                "path": SUMMARY_FILE_NAME,
                "sha256": _sha256(summary_target),
                "bytes": summary_target.stat().st_size,
            }

    pointer = {
        "schema_version": POINTER_SCHEMA_VERSION,
        "run_month": bundle["run_month"],
        "run_id": bundle["run_id"],
        "status": "ready_for_business_review",
        "dashboard_write_allowed": False,
    }
    if normalized_source_data:
        pointer["source_data"] = normalized_source_data
    pointer_bytes = (json.dumps(pointer, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    pointer_path = review_export_root / "latest_success.json"
    export_manifest = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "published_at": (now or datetime.now(timezone.utc)).isoformat(),
        "source_run": {
            "run_month": bundle["run_month"],
            "run_id": bundle["run_id"],
            "run_schema_version": RUN_SCHEMA_VERSION,
        },
        "layout": {
            "review_root": "franchise_operating_reviews",
            "latest_success": "franchise_operating_reviews/latest_success.json",
            "run_path": (
                f"franchise_operating_reviews/{bundle['run_month']}/{bundle['run_id']}"
            ),
            "required_run_files": sorted(RUN_FILE_KEYS.values()),
        },
        "files": exported_files,
        "summary": summary,
        "latest_success_sha256": hashlib.sha256(pointer_bytes).hexdigest(),
        "dashboard_write_allowed": False,
    }
    if normalized_source_data:
        export_manifest["source_data"] = normalized_source_data
    _atomic_json(review_export_root / "export_manifest.json", export_manifest)
    _atomic_bytes(pointer_path, pointer_bytes)
    return export_manifest

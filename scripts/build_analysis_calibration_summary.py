"""Build a read-only Site calibration summary from Dashboard-owned review exports."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from services.analysis_feedback import build_calibration_summary
from services.professional_analysis import validate_analysis_catalog


OUTPUT_ROOT = Path("data/staging/analysis_calibration")
RUN_SCHEMA_VERSION = "professional-analysis-calibration-run/v0.1"
FAILURE_STATUSES = {
    "catalog": "blocked_by_analysis_catalog",
    "feedback": "blocked_by_feedback_input",
    "output": "blocked_by_output",
}


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 根节点必须为对象：{path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _latest_success(output_root: Path):
    path = output_root / "latest_success.json"
    if not path.is_file():
        return None
    try:
        return _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"status": "unknown", "reason": "latest_success 指针无法读取"}


def _record_failure(
    output_root: Path,
    source: str,
    error: Exception,
    attempted_at: str,
) -> None:
    attempt = {
        "status": FAILURE_STATUSES[source],
        "failure_source": source,
        "stale": True,
        "attempted_at": attempted_at,
        "reason": str(error),
        "error_type": type(error).__name__,
        "latest_success": _latest_success(output_root),
        "dashboard_write_allowed": False,
    }
    try:
        _write_json(output_root / "last_attempt.json", attempt)
    except Exception as status_error:
        raise RuntimeError(
            f"{source} 失败：{error}；同时无法保存失败状态：{status_error}"
        ) from error


def build_from_files(
    analysis_catalog_path: str | Path,
    feedback_export_path: str | Path,
    output_root: str | Path = OUTPUT_ROOT,
    now: datetime | None = None,
) -> tuple[dict, Path, bool]:
    now = now or datetime.now(timezone.utc)
    output_root = Path(output_root)
    analysis_catalog_path = Path(analysis_catalog_path)
    feedback_export_path = Path(feedback_export_path)
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except Exception as error:
        # The output root itself is unavailable, so no status file can be persisted there.
        raise RuntimeError(f"output 失败：{error}") from error
    try:
        catalog = _read_json(analysis_catalog_path)
        validate_analysis_catalog(catalog)
        catalog_sha256 = _sha256(analysis_catalog_path)
    except Exception as error:
        _record_failure(output_root, "catalog", error, now.isoformat())
        raise
    try:
        feedback = _read_json(feedback_export_path)
        feedback_sha256 = _sha256(feedback_export_path)
    except Exception as error:
        _record_failure(output_root, "feedback", error, now.isoformat())
        raise
    try:
        summary = build_calibration_summary(catalog, feedback, now.isoformat())
    except Exception as error:
        _record_failure(output_root, "feedback", error, now.isoformat())
        raise
    try:
        run_dir = output_root / summary["summary_id"]
        manifest_path = run_dir / "manifest.json"
        if manifest_path.is_file():
            manifest = _read_json(manifest_path)
            pointer = {
                "summary_id": summary["summary_id"],
                "status": "ready",
                "path": str(run_dir),
                "generated_at": manifest.get("generated_at"),
                "stale": False,
            }
            _write_json(output_root / "last_attempt.json", pointer)
            _write_json(output_root / "latest_success.json", pointer)
            return manifest, run_dir, True
        run_dir.mkdir(parents=True, exist_ok=False)
        _write_json(run_dir / "calibration_summary.json", summary)
        manifest = {
            "schema_version": RUN_SCHEMA_VERSION,
            "summary_id": summary["summary_id"],
            "status": "ready",
            "generated_at": now.isoformat(),
            "dashboard_write_allowed": False,
            "inputs": {
                "analysis_catalog": {
                    "path": str(analysis_catalog_path),
                    "sha256": catalog_sha256,
                    "catalog_id": catalog.get("catalog_id"),
                },
                "feedback_export": {
                    "path": str(feedback_export_path),
                    "sha256": feedback_sha256,
                    "export_id": feedback.get("export_id"),
                },
            },
            "outputs": {"calibration_summary": "calibration_summary.json"},
        }
        _write_json(manifest_path, manifest)
        pointer = {
            "summary_id": summary["summary_id"],
            "status": "ready",
            "path": str(run_dir),
            "generated_at": now.isoformat(),
            "stale": False,
        }
        _write_json(output_root / "last_attempt.json", pointer)
        _write_json(output_root / "latest_success.json", pointer)
        return manifest, run_dir, False
    except Exception as error:
        _record_failure(output_root, "output", error, now.isoformat())
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a Site calibration summary without changing analysis rules or Dashboard."
    )
    parser.add_argument("--analysis-catalog", required=True)
    parser.add_argument("--feedback-export", required=True)
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    args = parser.parse_args()
    manifest, run_dir, duplicate = build_from_files(
        args.analysis_catalog,
        args.feedback_export,
        args.output_root,
    )
    state = "unchanged" if duplicate else "wrote"
    print(
        f"{state} summary_id={manifest['summary_id']} "
        f"status={manifest['status']} path={run_dir}"
    )


if __name__ == "__main__":
    main()

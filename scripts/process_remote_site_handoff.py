"""Consume Bot site packages and return preview or confirmed results to Dashboard."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "staging" / "remote-handoff"


class HandoffClient:
    def __init__(self, base_url: str, token: str, timeout: int = 90) -> None:
        if not base_url:
            raise ValueError("缺少 SITE_HANDOFF_BASE_URL")
        if len(token) < 32:
            raise ValueError("SITE_HANDOFF_PROCESSOR_TOKEN 至少需要 32 位")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def list_ready(self) -> list[dict[str, Any]]:
        payload = self._json("GET", "/site-handoff/packages")
        return list(payload.get("data", {}).get("records", []))

    def read_package(self, project_id: str) -> dict[str, Any]:
        return self._json(
            "GET",
            f"/site-handoff/packages/{quote(project_id, safe='')}?download=1",
            unwrap=False,
        )

    def read_source(self, project_id: str, source_id: str) -> bytes:
        return self._request(
            "GET",
            f"/site-handoff/packages/{quote(project_id, safe='')}/sources/{quote(source_id, safe='')}",
        )

    def submit_result(self, project_id: str, candidate: dict[str, Any]) -> dict[str, Any]:
        return self._json(
            "POST",
            f"/site-handoff/packages/{quote(project_id, safe='')}/result",
            candidate,
        )

    def submit_progress(
        self,
        project_id: str,
        *,
        status: str,
        stage: str,
        message: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "status": status,
            "stage": stage,
            "message": message,
        }
        if error:
            payload["error"] = error
        return self._json(
            "POST",
            f"/site-handoff/packages/{quote(project_id, safe='')}/progress",
            payload,
        )

    def _json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        unwrap: bool = True,
    ) -> dict[str, Any]:
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        raw = self._request(method, path, body=body, headers=headers)
        parsed = json.loads(raw.decode("utf-8"))
        if unwrap and not parsed.get("success"):
            raise RuntimeError(parsed.get("message") or "工作台中转接口返回失败")
        return parsed

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "X-Lann-Site-Processor-Token": self.token,
                "User-Agent": "lann-site-handoff/1.0",
                **(headers or {}),
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"工作台中转接口 HTTP {error.code}: {detail[:500]}") from error
        except URLError as error:
            raise RuntimeError(f"无法连接工作台中转接口: {error.reason}") from error


def process_ready_package(
    client: HandoffClient,
    item: dict[str, Any],
    *,
    output_root: Path,
    analyzer: Callable[[Path, Path, Path, bool], dict[str, Any]],
) -> dict[str, Any]:
    project_id = str(item.get("projectId") or "")
    if not project_id:
        raise ValueError("待分析项目缺少 projectId")
    stage = "reading_package"
    try:
        report_progress(client, project_id, stage, "Site 已领取资料，正在核对资料包")
        project_root = safe_child(output_root, project_id)
        storage_root = project_root / "storage"
        input_package = client.read_package(project_id)
        confirmed = bool(input_package.get("confirmation", {}).get("input_summary_confirmed"))
        if not confirmed and input_package.get("external_writes", {}).get("dashboard_allowed") is not False:
            raise ValueError("未确认资料只能进行只读初审")

        project_root.mkdir(parents=True, exist_ok=True)
        package_path = project_root / "input-package.json"
        package_path.write_text(
            json.dumps(input_package, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        stage = "downloading_sources"
        report_progress(client, project_id, stage, "正在下载并核验原始资料")
        for source in input_package.get("sources", []):
            storage = source.get("storage") or {}
            relative_path = storage.get("relative_path")
            if not relative_path:
                continue
            raw = client.read_source(project_id, str(source.get("source_id") or ""))
            verify_source(raw, storage)
            target = safe_child(storage_root, str(relative_path))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)

        stage = "analyzing"
        report_progress(client, project_id, stage, "正在读取正文并形成选址初审")
        candidate = analyzer(package_path, storage_root, project_root / "analysis", not confirmed)
        stage = "returning_result"
        report_progress(client, project_id, stage, "分析完成，正在回传结果")
        client.submit_result(project_id, candidate)
        return {
            "project_id": project_id,
            "project_name": item.get("projectName"),
            "candidate_site_id": candidate.get("site_id", {}).get("value"),
            "analysis_mode": "confirmed" if confirmed else "preview",
        }
    except Exception as error:
        report_failure(client, project_id, stage, error)
        raise


def run_analysis(
    package_path: Path,
    storage_root: Path,
    output_dir: Path,
    allow_unconfirmed: bool,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "scripts.run_new_store_handoff",
        "--input-package",
        str(package_path),
        "--storage-root",
        str(storage_root),
        "--output-dir",
        str(output_dir),
    ]
    if env_bool("SITE_HANDOFF_ENABLE_OCR", False):
        command.append("--enable-ocr")
    if allow_unconfirmed:
        command.append("--allow-unconfirmed")
    subprocess.run(command, cwd=REPO_ROOT, check=True)
    candidate_path = output_dir / package_path.parent.name / "site-record-candidate.json"
    if not candidate_path.exists():
        raise FileNotFoundError(f"Site 分析未生成候选结果: {candidate_path}")
    return json.loads(candidate_path.read_text(encoding="utf-8"))


def run_once(
    client: HandoffClient,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    analyzer: Callable[[Path, Path, Path, bool], dict[str, Any]] = run_analysis,
) -> list[dict[str, Any]]:
    results = []
    failures = []
    for item in client.list_ready():
        try:
            results.append(
                process_ready_package(
                    client,
                    item,
                    output_root=output_root,
                    analyzer=analyzer,
                )
            )
        except Exception as error:  # noqa: BLE001 - batch must continue with other projects
            failures.append({
                "project_id": item.get("projectId"),
                "error": str(error),
            })
    print(json.dumps({"processed": results, "failures": failures}, ensure_ascii=False, indent=2))
    if failures:
        raise RuntimeError(f"{len(failures)} 个选址项目自动交接失败")
    return results


def verify_source(raw: bytes, storage: dict[str, Any]) -> None:
    expected_hash = str(storage.get("sha256") or "")
    if expected_hash and hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("下载原件摘要与资料包不一致")
    expected_bytes = storage.get("bytes")
    if expected_bytes is not None and len(raw) != int(expected_bytes):
        raise ValueError("下载原件大小与资料包不一致")


def report_progress(client: HandoffClient, project_id: str, stage: str, message: str) -> None:
    try:
        client.submit_progress(
            project_id,
            status="processing",
            stage=stage,
            message=message,
        )
    except Exception as error:  # noqa: BLE001 - progress reporting must not block analysis
        print(f"选址交接进度回传失败: {error}", file=sys.stderr)


def report_failure(client: HandoffClient, project_id: str, stage: str, error: Exception) -> None:
    try:
        client.submit_progress(
            project_id,
            status="failed",
            stage=stage,
            message="Site 处理遇到问题，系统将自动重试",
            error=str(error),
        )
    except Exception as report_error:  # noqa: BLE001 - preserve the original processing error
        print(f"选址交接失败状态回传失败: {report_error}", file=sys.stderr)


def safe_child(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    resolved = (resolved_root / relative_path).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError("资料路径越出 Site 交接目录")
    return resolved


def env_bool(name: str, fallback: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return fallback
    return value.lower() in {"1", "true", "yes", "on"}


def main() -> None:
    client = HandoffClient(
        os.getenv("SITE_HANDOFF_BASE_URL", ""),
        os.getenv("SITE_HANDOFF_PROCESSOR_TOKEN", ""),
        int(os.getenv("SITE_HANDOFF_TIMEOUT_SECONDS", "90")),
    )
    output_root = Path(os.getenv("SITE_HANDOFF_OUTPUT_DIR", str(DEFAULT_OUTPUT_ROOT)))
    run_once(client, output_root=output_root)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"远程选址交接失败: {error}", file=sys.stderr)
        raise SystemExit(1) from error

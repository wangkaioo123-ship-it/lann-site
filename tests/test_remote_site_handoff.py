from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.process_remote_site_handoff import process_ready_package, run_analysis, safe_child


class FakeClient:
    def __init__(self, package: dict, source: bytes) -> None:
        self.package = package
        self.source = source
        self.submitted = None
        self.progress = []

    def read_package(self, project_id: str) -> dict:
        return self.package

    def read_source(self, project_id: str, source_id: str) -> bytes:
        return self.source

    def submit_result(self, project_id: str, candidate: dict) -> dict:
        self.submitted = (project_id, candidate)
        return {"success": True}

    def submit_progress(
        self,
        project_id: str,
        *,
        status: str,
        stage: str,
        message: str,
        error: str | None = None,
    ) -> dict:
        self.progress.append({
            "project_id": project_id,
            "status": status,
            "stage": stage,
            "message": message,
            "error": error,
        })
        return {"success": True}


class RemoteSiteHandoffTests(unittest.TestCase):
    def test_materializes_sources_runs_analysis_and_submits_candidate(self) -> None:
        raw = b"fake pdf bytes"
        package = {
            "schema_version": "lann-site-neutral-input/v0.1",
            "project": {"id": "site_20260807_remote", "name": "测试商场"},
            "case_identity": {
                "case_id": "site_20260807_remote",
                "case_type": "site_opportunity",
                "business_domain": "new_store_growth",
                "business_stage": "待研判",
            },
            "business_context": {"stage": "待研判"},
            "confirmation": {"input_summary_confirmed": True},
            "sources": [{
                "source_id": "source_001",
                "storage": {
                    "relative_path": "blobs/aa/test.pdf",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                },
            }],
        }
        client = FakeClient(package, raw)
        candidate = {
            "schema_version": "site_record/v0.1",
            "site_id": {"value": "site_20260807_remote"},
        }

        def analyzer(
            package_path: Path,
            storage_root: Path,
            output_dir: Path,
            allow_unconfirmed: bool,
        ) -> dict:
            self.assertTrue(package_path.exists())
            self.assertEqual((storage_root / "blobs/aa/test.pdf").read_bytes(), raw)
            self.assertFalse(allow_unconfirmed)
            return candidate

        with tempfile.TemporaryDirectory() as temp_dir:
            result = process_ready_package(
                client,
                {"projectId": "site_20260807_remote", "projectName": "测试商场"},
                output_root=Path(temp_dir),
                analyzer=analyzer,
            )

        self.assertEqual(result["candidate_site_id"], "site_20260807_remote")
        self.assertEqual(result["case_id"], "site_20260807_remote")
        self.assertEqual(result["business_stage"], "待研判")
        self.assertEqual(client.submitted, ("site_20260807_remote", candidate))
        self.assertEqual(
            [item["stage"] for item in client.progress],
            ["reading_package", "downloading_sources", "analyzing", "returning_result"],
        )

    def test_unconfirmed_package_runs_read_only_preview(self) -> None:
        raw = b"preview pdf bytes"
        package = {
            "schema_version": "lann-site-neutral-input/v0.1",
            "project": {"id": "site_20260807_preview", "name": "初审商场"},
            "confirmation": {"input_summary_confirmed": False},
            "external_writes": {"dashboard_allowed": False},
            "sources": [{
                "source_id": "source_preview",
                "storage": {
                    "relative_path": "blobs/preview.pdf",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                },
            }],
        }
        client = FakeClient(package, raw)
        candidate = {
            "schema_version": "site_record/v0.1",
            "site_id": {"value": "site_20260807_preview"},
        }

        def analyzer(
            package_path: Path,
            storage_root: Path,
            output_dir: Path,
            allow_unconfirmed: bool,
        ) -> dict:
            self.assertTrue(allow_unconfirmed)
            return candidate

        with tempfile.TemporaryDirectory() as temp_dir:
            result = process_ready_package(
                client,
                {"projectId": "site_20260807_preview", "projectName": "初审商场"},
                output_root=Path(temp_dir),
                analyzer=analyzer,
            )

        self.assertEqual(result["analysis_mode"], "preview")
        self.assertEqual(client.submitted, ("site_20260807_preview", candidate))

    def test_reports_failure_stage_without_losing_original_error(self) -> None:
        raw = b"broken preview"
        package = {
            "schema_version": "lann-site-neutral-input/v0.1",
            "project": {"id": "site_20260807_failure", "name": "失败商场"},
            "confirmation": {"input_summary_confirmed": False},
            "external_writes": {"dashboard_allowed": False},
            "sources": [{
                "source_id": "source_failure",
                "storage": {
                    "relative_path": "blobs/failure.pdf",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                },
            }],
        }
        client = FakeClient(package, raw)

        def analyzer(*args, **kwargs) -> dict:
            raise RuntimeError("PDF 正文读取失败")

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "PDF 正文读取失败"):
                process_ready_package(
                    client,
                    {"projectId": "site_20260807_failure", "projectName": "失败商场"},
                    output_root=Path(temp_dir),
                    analyzer=analyzer,
                )

        failure = client.progress[-1]
        self.assertEqual(failure["status"], "failed")
        self.assertEqual(failure["stage"], "analyzing")
        self.assertEqual(failure["error"], "PDF 正文读取失败")

    def test_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "越出"):
                safe_child(Path(temp_dir), "../outside.pdf")

    def test_rejects_mismatched_case_identity(self) -> None:
        raw = b"fake pdf bytes"
        package = {
            "schema_version": "lann-site-neutral-input/v0.1",
            "project": {"id": "site_20260807_expected", "name": "测试商场"},
            "case_identity": {
                "case_id": "site_20260807_other",
                "case_type": "site_opportunity",
                "business_domain": "new_store_growth",
            },
            "confirmation": {"input_summary_confirmed": True},
            "sources": [],
        }
        client = FakeClient(package, raw)
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "事项编号"):
                process_ready_package(
                    client,
                    {"projectId": "site_20260807_expected", "projectName": "测试商场"},
                    output_root=Path(temp_dir),
                    analyzer=lambda *args: {},
                )

    @patch("scripts.process_remote_site_handoff.subprocess.run")
    def test_surfaces_child_process_error(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=["python"],
            returncode=1,
            stdout="",
            stderr="PDF 解析失败：文件结构损坏",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_path = root / "input-package.json"
            package_path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "PDF 解析失败"):
                run_analysis(package_path, root / "storage", root / "output", False)


if __name__ == "__main__":
    unittest.main()

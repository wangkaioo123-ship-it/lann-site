from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.process_remote_site_handoff import process_ready_package, safe_child


class FakeClient:
    def __init__(self, package: dict, source: bytes) -> None:
        self.package = package
        self.source = source
        self.submitted = None

    def read_package(self, project_id: str) -> dict:
        return self.package

    def read_source(self, project_id: str, source_id: str) -> bytes:
        return self.source

    def submit_result(self, project_id: str, candidate: dict) -> dict:
        self.submitted = (project_id, candidate)
        return {"success": True}


class RemoteSiteHandoffTests(unittest.TestCase):
    def test_materializes_sources_runs_analysis_and_submits_candidate(self) -> None:
        raw = b"fake pdf bytes"
        package = {
            "schema_version": "lann-site-neutral-input/v0.1",
            "project": {"id": "site_20260807_remote", "name": "测试商场"},
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
        self.assertEqual(client.submitted, ("site_20260807_remote", candidate))

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

    def test_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "越出"):
                safe_child(Path(temp_dir), "../outside.pdf")


if __name__ == "__main__":
    unittest.main()

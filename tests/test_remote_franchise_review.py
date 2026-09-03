import tempfile
import unittest
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from scripts.run_remote_franchise_review import DataGateBlockedError, acquire_package, execute
from services.remote_data_package import PackageIntegrityError, atomic_write_json


class RemoteFranchiseReviewTests(unittest.TestCase):
    def test_sync_failure_uses_last_success_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            operating = Path(temp) / "operating.csv"
            workforce = Path(temp) / "workforce.csv"
            operating.write_text("a", encoding="utf-8")
            workforce.write_text("b", encoding="utf-8")
            package_path = Path(temp) / "package"
            package_path.mkdir()
            cached_operating = package_path / "site_performance_monthly_bi_feishu_rent.csv"
            cached_workforce = package_path / "store_workforce_monthly.csv"
            cached_operating.write_bytes(operating.read_bytes())
            cached_workforce.write_bytes(workforce.read_bytes())
            manifest = {
                "schema_version": "lann-data-site-package/v1",
                "package_id": "last-good",
                "generated_at": "2026-09-01T08:00:00+08:00",
                "source_commit": "a" * 40,
                "data_period": "2026-07",
                "files": [
                    {
                        "role": "operating_monthly",
                        "url": "https://data.example.test/operating.csv",
                        "sha256": hashlib.sha256(cached_operating.read_bytes()).hexdigest(),
                        "size_bytes": cached_operating.stat().st_size,
                    },
                    {
                        "role": "workforce_monthly",
                        "url": "https://data.example.test/workforce.csv",
                        "sha256": hashlib.sha256(cached_workforce.read_bytes()).hexdigest(),
                        "size_bytes": cached_workforce.stat().st_size,
                    },
                ],
            }
            manifest_body = json.dumps(manifest, separators=(",", ":")).encode()
            (package_path / "manifest.json").write_bytes(manifest_body)
            atomic_write_json(
                Path(temp) / "latest_success.json",
                {
                    "schema_version": "lann-site-remote-package-pointer/v1",
                    "package_id": "last-good",
                    "manifest_sha256": hashlib.sha256(manifest_body).hexdigest(),
                    "package_path": str(package_path),
                    "role_paths": {
                        "operating_monthly": str(cached_operating),
                        "workforce_monthly": str(cached_workforce),
                    },
                },
            )

            def fail_sync(*args, **kwargs):
                raise RuntimeError("temporary unavailable")

            pointer, status, error = acquire_package(
                "https://data.example.test/manifest.json",
                temp,
                sync_function=fail_sync,
            )
            self.assertEqual(pointer["package_id"], "last-good")
            self.assertEqual(status, "fallback_last_success")
            self.assertIn("temporary unavailable", error)

    def test_data_gate_failure_preserves_blocked_status(self):
        with tempfile.TemporaryDirectory() as temp:
            input_root = Path(temp) / "input"
            output_root = Path(temp) / "output"
            operating = input_root / "operating.csv"
            workforce = input_root / "workforce.csv"
            input_root.mkdir()
            operating.write_text("x", encoding="utf-8")
            workforce.write_text("y", encoding="utf-8")
            pointer = {
                "package_id": "package-v1",
                "data_period": "2026-07",
                "generated_at": "2026-09-01T08:00:00+08:00",
                "source_commit": "a" * 40,
                "manifest_sha256": "b" * 64,
                "role_paths": {
                    "operating_monthly": str(operating),
                    "workforce_monthly": str(workforce),
                },
            }
            blocked_manifest = {
                "run_id": "blocked-run",
                "run_month": "2026-07",
                "status": "blocked_by_data_gate",
            }
            with patch(
                "scripts.run_remote_franchise_review.acquire_package",
                return_value=(pointer, "fresh", None),
            ), patch(
                "scripts.run_remote_franchise_review.build",
                return_value=(blocked_manifest, output_root / "2026-07" / "blocked-run", False),
            ):
                with self.assertRaises(DataGateBlockedError):
                    execute(
                        "https://data.example.test/manifest.json",
                        input_root=input_root,
                        output_root=output_root,
                        target_month="2026-07",
                    )
            status = json.loads((output_root / "remote_run_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "blocked_by_data_gate")
            self.assertEqual(status["review"]["run_status"], "blocked_by_data_gate")

    def test_integrity_error_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            def fail_sync(*args, **kwargs):
                raise PackageIntegrityError("package conflict")

            with self.assertRaisesRegex(PackageIntegrityError, "package conflict"):
                acquire_package(
                    "https://data.example.test/manifest.json",
                    temp,
                    sync_function=fail_sync,
                )

    def test_execute_marks_network_fallback_as_stale_success(self):
        with tempfile.TemporaryDirectory() as temp:
            input_root = Path(temp) / "input"
            output_root = Path(temp) / "output"
            operating = input_root / "operating.csv"
            workforce = input_root / "workforce.csv"
            input_root.mkdir()
            operating.write_text("x", encoding="utf-8")
            workforce.write_text("y", encoding="utf-8")
            pointer = {
                "package_id": "package-v1",
                "data_period": "2026-07",
                "generated_at": "2026-09-01T08:00:00+08:00",
                "source_commit": "a" * 40,
                "manifest_sha256": "b" * 64,
                "role_paths": {
                    "operating_monthly": str(operating),
                    "workforce_monthly": str(workforce),
                },
            }
            manifest = {
                "run_id": "ready-run",
                "run_month": "2026-07",
                "status": "ready_for_business_review",
            }
            with patch(
                "scripts.run_remote_franchise_review.acquire_package",
                return_value=(pointer, "fallback_last_success", "temporary unavailable"),
            ), patch(
                "scripts.run_remote_franchise_review.build",
                return_value=(manifest, output_root / "2026-07" / "ready-run", False),
            ):
                result = execute(
                    "https://data.example.test/manifest.json",
                    input_root=input_root,
                    output_root=output_root,
                    target_month="2026-07",
                )
            self.assertEqual(result["status"], "success_stale_data")
            saved = json.loads((output_root / "remote_run_status.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["sync_status"], "fallback_last_success")
            self.assertEqual(saved["status"], "success_stale_data")

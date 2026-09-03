import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from services.remote_data_package import (
    PackageIntegrityError,
    RemoteDataPackageError,
    load_latest_success,
    sync_remote_data_package,
    validate_manifest,
)


class FakeResponse:
    def __init__(self, url, payload, status_code=200):
        self.url = url
        self.content = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses[url]


def build_fixture(package_id="package-2026-07-v1", operating=b"operating", workforce=b"workforce"):
    base_url = "https://data.example.test/lann-site/"
    manifest_url = f"{base_url}manifest.json"
    manifest = {
        "schema_version": "lann-data-site-package/v1",
        "package_id": package_id,
        "generated_at": "2026-09-01T08:00:00+08:00",
        "source_commit": "a" * 40,
        "data_period": "2026-07",
        "files": [
            {
                "role": "operating_monthly",
                "url": "operating.csv",
                "sha256": hashlib.sha256(operating).hexdigest(),
                "size_bytes": len(operating),
            },
            {
                "role": "workforce_monthly",
                "url": "workforce.csv",
                "sha256": hashlib.sha256(workforce).hexdigest(),
                "size_bytes": len(workforce),
            },
        ],
    }
    manifest_body = json.dumps(manifest, separators=(",", ":")).encode()
    responses = {
        manifest_url: FakeResponse(manifest_url, manifest_body),
        f"{base_url}operating.csv": FakeResponse(f"{base_url}operating.csv", operating),
        f"{base_url}workforce.csv": FakeResponse(f"{base_url}workforce.csv", workforce),
    }
    return manifest_url, responses


class RemoteDataPackageTests(unittest.TestCase):
    def test_sync_verifies_files_and_writes_atomic_pointer(self):
        manifest_url, responses = build_fixture()
        with tempfile.TemporaryDirectory() as temp:
            token_path = Path(temp) / "token"
            token_path.write_text("secret-token", encoding="utf-8")
            session = FakeSession(responses)
            pointer = sync_remote_data_package(manifest_url, temp, token_file=token_path, session=session)
            loaded = load_latest_success(temp)
            self.assertEqual(pointer["package_id"], "package-2026-07-v1")
            self.assertEqual(loaded["package_id"], pointer["package_id"])
            self.assertEqual(Path(loaded["role_paths"]["operating_monthly"]).read_bytes(), b"operating")
            self.assertEqual(Path(loaded["role_paths"]["workforce_monthly"]).read_bytes(), b"workforce")
            self.assertTrue(all(call[1]["headers"]["Authorization"] == "Bearer secret-token" for call in session.calls))

    def test_cross_origin_file_does_not_receive_bearer_token(self):
        manifest_url, responses = build_fixture()
        manifest = json.loads(responses[manifest_url].content)
        manifest["files"][0]["url"] = "https://objects.example.test/operating.csv"
        responses[manifest_url].content = json.dumps(manifest, separators=(",", ":")).encode()
        responses["https://objects.example.test/operating.csv"] = responses.pop(
            "https://data.example.test/lann-site/operating.csv"
        )
        responses["https://objects.example.test/operating.csv"].url = "https://objects.example.test/operating.csv"
        with tempfile.TemporaryDirectory() as temp:
            token_path = Path(temp) / "token"
            token_path.write_text("secret-token", encoding="utf-8")
            session = FakeSession(responses)
            sync_remote_data_package(manifest_url, temp, token_file=token_path, session=session)
            cross_origin_call = next(call for call in session.calls if call[0].startswith("https://objects.example.test/"))
            self.assertNotIn("Authorization", cross_origin_call[1]["headers"])

    def test_manifest_rejects_naive_generated_at_and_invalid_month(self):
        manifest_url, responses = build_fixture()
        manifest = json.loads(responses[manifest_url].content)
        manifest["generated_at"] = "2026-09-01T08:00:00"
        with self.assertRaisesRegex(RemoteDataPackageError, "必须包含时区"):
            validate_manifest(manifest, manifest_url)
        manifest["generated_at"] = "2026-09-01T08:00:00+08:00"
        manifest["data_period"] = "2026-13"
        with self.assertRaisesRegex(RemoteDataPackageError, "YYYY-MM"):
            validate_manifest(manifest, manifest_url)
        manifest["data_period"] = "2026-07"
        manifest["files"][0]["size_bytes"] = 1.5
        with self.assertRaisesRegex(RemoteDataPackageError, "必须是整数"):
            validate_manifest(manifest, manifest_url)

    def test_failed_new_package_does_not_replace_last_success(self):
        first_url, first_responses = build_fixture()
        second_url, second_responses = build_fixture(package_id="package-2026-08-v1", operating=b"new-operating")
        second_responses["https://data.example.test/lann-site/operating.csv"].content = b"corrupt"
        with tempfile.TemporaryDirectory() as temp:
            sync_remote_data_package(first_url, temp, session=FakeSession(first_responses))
            with self.assertRaises(RemoteDataPackageError):
                sync_remote_data_package(second_url, temp, session=FakeSession(second_responses))
            pointer = load_latest_success(temp)
            self.assertEqual(pointer["package_id"], "package-2026-07-v1")

    def test_same_package_id_conflict_is_integrity_error(self):
        manifest_url, responses = build_fixture()
        with tempfile.TemporaryDirectory() as temp:
            sync_remote_data_package(manifest_url, temp, session=FakeSession(responses))
            changed_url, changed_responses = build_fixture(operating=b"changed")
            with self.assertRaisesRegex(PackageIntegrityError, "相同 package_id"):
                sync_remote_data_package(changed_url, temp, session=FakeSession(changed_responses))

    def test_redirect_is_rejected_without_following(self):
        manifest_url, responses = build_fixture()
        responses[manifest_url] = FakeResponse(manifest_url, b"", status_code=302)
        with tempfile.TemporaryDirectory() as temp:
            session = FakeSession(responses)
            with self.assertRaisesRegex(PackageIntegrityError, "不允许 HTTP 重定向"):
                sync_remote_data_package(manifest_url, temp, session=session)
            self.assertEqual(len(session.calls), 1)
            self.assertFalse(session.calls[0][1]["allow_redirects"])

    def test_manifest_4xx_is_hard_failure_without_fallback_semantics(self):
        manifest_url, responses = build_fixture()
        responses[manifest_url] = FakeResponse(manifest_url, b"", status_code=401)
        with tempfile.TemporaryDirectory() as temp:
            session = FakeSession(responses)
            with self.assertRaisesRegex(RemoteDataPackageError, "不允许回退旧数据"):
                sync_remote_data_package(manifest_url, temp, session=session)
            self.assertEqual(len(session.calls), 1)

    def test_file_4xx_is_hard_failure_without_replacing_last_success(self):
        first_url, first_responses = build_fixture()
        second_url, second_responses = build_fixture(package_id="package-2026-08-v1")
        second_responses["https://data.example.test/lann-site/operating.csv"] = FakeResponse(
            "https://data.example.test/lann-site/operating.csv",
            b"",
            status_code=404,
        )
        with tempfile.TemporaryDirectory() as temp:
            sync_remote_data_package(first_url, temp, session=FakeSession(first_responses))
            with self.assertRaisesRegex(RemoteDataPackageError, "不允许回退旧数据"):
                sync_remote_data_package(second_url, temp, session=FakeSession(second_responses))
            self.assertEqual(load_latest_success(temp)["package_id"], "package-2026-07-v1")

    def test_rollback_manifest_is_rejected(self):
        manifest_url, responses = build_fixture()
        with tempfile.TemporaryDirectory() as temp:
            sync_remote_data_package(manifest_url, temp, session=FakeSession(responses))
            older_url, older_responses = build_fixture(package_id="package-2026-06-v1")
            older_manifest = json.loads(older_responses[older_url].content)
            older_manifest["data_period"] = "2026-06"
            older_manifest["generated_at"] = "2026-08-01T08:00:00+08:00"
            older_responses[older_url].content = json.dumps(older_manifest, separators=(",", ":")).encode()
            with self.assertRaisesRegex(PackageIntegrityError, "拒绝回滚"):
                sync_remote_data_package(older_url, temp, session=FakeSession(older_responses))

    def test_http_manifest_is_rejected_by_default(self):
        with self.assertRaises(RemoteDataPackageError):
            validate_manifest(
                {
                    "schema_version": "lann-data-site-package/v1",
                    "package_id": "package-v1",
                    "generated_at": "2026-09-01T08:00:00+08:00",
                    "source_commit": "a" * 40,
                    "data_period": "2026-07",
                    "files": [],
                },
                "http://data.example.test/manifest.json",
            )

    def test_fallback_rejects_tampered_cached_file(self):
        manifest_url, responses = build_fixture()
        with tempfile.TemporaryDirectory() as temp:
            pointer = sync_remote_data_package(manifest_url, temp, session=FakeSession(responses))
            Path(pointer["role_paths"]["operating_monthly"]).write_bytes(b"tampered")
            with self.assertRaisesRegex(RemoteDataPackageError, "校验失败"):
                load_latest_success(temp)

    def test_manifest_rejects_missing_required_role(self):
        manifest_url, responses = build_fixture()
        manifest = json.loads(responses[manifest_url].content)
        manifest["files"] = manifest["files"][:1]
        with self.assertRaisesRegex(RemoteDataPackageError, "缺少正式输入"):
            validate_manifest(manifest, manifest_url)

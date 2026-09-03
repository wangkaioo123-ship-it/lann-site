"""Fetch and verify immutable read-only data packages for lann-site."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests


SCHEMA_VERSION = "lann-data-site-package/v1"
POINTER_SCHEMA_VERSION = "lann-site-remote-package-pointer/v1"
REQUIRED_ROLES = {
    "operating_monthly": "site_performance_monthly_bi_feishu_rent.csv",
    "workforce_monthly": "store_workforce_monthly.csv",
}
PACKAGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SOURCE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_MANIFEST_BYTES = 1024 * 1024
DEFAULT_TIMEOUT = (10, 60)
MONTH_PATTERN = re.compile(r"^20\d{2}-(0[1-9]|1[0-2])$")


class RemoteDataPackageError(RuntimeError):
    pass


class PackageIntegrityError(RemoteDataPackageError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: str | Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
        temporary_path = Path(handle.name)
    temporary_path.replace(path)


def read_token(token_file: str | Path | None) -> str | None:
    if not token_file:
        return None
    token_path = Path(token_file)
    if not token_path.is_file():
        raise RemoteDataPackageError(f"数据出口凭证文件不存在：{token_path}")
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise RemoteDataPackageError("数据出口凭证文件为空")
    return token


def request_headers(token: str | None) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "lann-site-data-bridge/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def validate_transport(url: str, allow_insecure: bool) -> None:
    scheme = urlparse(url).scheme.lower()
    if scheme == "https":
        return
    if allow_insecure and scheme in {"http", "file"}:
        return
    raise RemoteDataPackageError("正式数据出口只允许 HTTPS")


def same_origin(first_url: str, second_url: str) -> bool:
    first = urlparse(first_url)
    second = urlparse(second_url)
    return (first.scheme.lower(), first.hostname, first.port) == (
        second.scheme.lower(), second.hostname, second.port
    )


def reject_redirect(response, context: str) -> None:
    status_code = int(getattr(response, "status_code", 0) or 0)
    if 300 <= status_code < 400:
        raise PackageIntegrityError(f"{context} 不允许 HTTP 重定向")


def reject_non_retryable_http_error(response, context: str) -> None:
    status_code = int(getattr(response, "status_code", 0) or 0)
    if 400 <= status_code < 500:
        raise RemoteDataPackageError(
            f"{context} 返回 HTTP {status_code}，属于地址、权限或请求配置错误，不允许回退旧数据"
        )


def parse_generated_at(value: str) -> datetime:
    try:
        generated_datetime = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RemoteDataPackageError("数据包 generated_at 非法") from error
    if generated_datetime.tzinfo is None:
        raise RemoteDataPackageError("数据包 generated_at 必须包含时区")
    return generated_datetime


def parse_data_period(value: str) -> tuple[int, int]:
    if not isinstance(value, str) or not MONTH_PATTERN.fullmatch(value):
        raise RemoteDataPackageError("数据包 data_period 必须是 YYYY-MM")
    year, month = value.split("-")
    return int(year), int(month)


def ensure_not_rollback(root: Path, manifest: dict) -> None:
    pointer_path = root / "latest_success.json"
    if not pointer_path.is_file():
        return
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PackageIntegrityError("最近成功数据包指针损坏，无法校验回滚") from error
    if pointer.get("schema_version") != POINTER_SCHEMA_VERSION:
        raise PackageIntegrityError("最近成功数据包指针版本不受支持，无法校验回滚")
    previous_period = str(pointer.get("data_period") or "")
    previous_generated_at = str(pointer.get("generated_at") or "")
    if not previous_generated_at:
        raise PackageIntegrityError("最近成功数据包缺少回滚校验字段")
    try:
        previous_period_value = parse_data_period(previous_period)
        current_period_value = parse_data_period(manifest["data_period"])
    except RemoteDataPackageError as error:
        raise PackageIntegrityError("最近成功数据包月份无法用于回滚校验") from error
    if current_period_value < previous_period_value:
        raise PackageIntegrityError("远端数据包月份早于最近成功包，已拒绝回滚")
    if parse_generated_at(manifest["generated_at"]) < parse_generated_at(previous_generated_at):
        raise PackageIntegrityError("远端数据包生成时间早于最近成功包，已拒绝回滚")


def validate_manifest(payload: dict, manifest_url: str, allow_insecure: bool = False) -> dict:
    if not isinstance(payload, dict):
        raise RemoteDataPackageError("数据包 manifest 必须是 JSON 对象")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RemoteDataPackageError("数据包 schema_version 不受支持")
    package_id = str(payload.get("package_id") or "")
    if not PACKAGE_ID_PATTERN.fullmatch(package_id):
        raise RemoteDataPackageError("数据包 package_id 非法")
    source_commit = str(payload.get("source_commit") or "")
    if not SOURCE_COMMIT_PATTERN.fullmatch(source_commit):
        raise RemoteDataPackageError("数据包 source_commit 必须是完整 40 位提交")
    generated_at = str(payload.get("generated_at") or "")
    parse_generated_at(generated_at)
    data_period = str(payload.get("data_period") or "")
    parse_data_period(data_period)
    files = payload.get("files")
    if not isinstance(files, list):
        raise RemoteDataPackageError("数据包 files 必须是数组")
    normalized_files = {}
    for item in files:
        if not isinstance(item, dict):
            raise RemoteDataPackageError("数据包文件定义非法")
        role = str(item.get("role") or "")
        if role not in REQUIRED_ROLES:
            raise RemoteDataPackageError(f"数据包包含未批准角色：{role or '空'}")
        if role in normalized_files:
            raise RemoteDataPackageError(f"数据包角色重复：{role}")
        file_url = urljoin(manifest_url, str(item.get("url") or ""))
        validate_transport(file_url, allow_insecure)
        expected_sha256 = str(item.get("sha256") or "")
        if not SHA256_PATTERN.fullmatch(expected_sha256):
            raise RemoteDataPackageError(f"{role} 的 sha256 非法")
        size_bytes = item.get("size_bytes")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
            raise RemoteDataPackageError(f"{role} 的 size_bytes 必须是整数")
        if size_bytes < 1:
            raise RemoteDataPackageError(f"{role} 的 size_bytes 必须大于 0")
        normalized_files[role] = {
            "role": role,
            "url": file_url,
            "sha256": expected_sha256,
            "size_bytes": size_bytes,
            "local_name": REQUIRED_ROLES[role],
            "send_authorization": same_origin(manifest_url, file_url),
        }
    missing_roles = sorted(set(REQUIRED_ROLES) - set(normalized_files))
    if missing_roles:
        raise RemoteDataPackageError(f"数据包缺少正式输入：{', '.join(missing_roles)}")
    return {
        "schema_version": SCHEMA_VERSION,
        "package_id": package_id,
        "generated_at": generated_at,
        "source_commit": source_commit,
        "data_period": data_period,
        "files": normalized_files,
    }


def fetch_manifest(
    manifest_url: str,
    token: str | None = None,
    session=None,
    allow_insecure: bool = False,
    timeout=DEFAULT_TIMEOUT,
    max_manifest_bytes=DEFAULT_MAX_MANIFEST_BYTES,
) -> tuple[dict, str, bytes]:
    validate_transport(manifest_url, allow_insecure)
    session = session or requests.Session()
    response = session.get(
        manifest_url,
        headers=request_headers(token),
        timeout=timeout,
        allow_redirects=False,
    )
    reject_redirect(response, "数据包 manifest")
    reject_non_retryable_http_error(response, "数据包 manifest")
    response.raise_for_status()
    validate_transport(getattr(response, "url", manifest_url), allow_insecure)
    body = response.content
    if len(body) > max_manifest_bytes:
        raise RemoteDataPackageError("数据包 manifest 超过允许大小")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RemoteDataPackageError("数据包 manifest 不是有效 UTF-8 JSON") from error
    return validate_manifest(payload, manifest_url, allow_insecure), sha256_bytes(body), body


def download_file(
    session,
    item: dict,
    destination: Path,
    token: str | None,
    allow_insecure: bool,
    timeout,
    max_file_bytes: int,
) -> None:
    if item["size_bytes"] > max_file_bytes:
        raise RemoteDataPackageError(f"{item['role']} 超过允许大小")
    response = session.get(
        item["url"],
        headers=request_headers(token if item.get("send_authorization") else None),
        timeout=timeout,
        stream=True,
        allow_redirects=False,
    )
    reject_redirect(response, item["role"])
    reject_non_retryable_http_error(response, item["role"])
    response.raise_for_status()
    validate_transport(getattr(response, "url", item["url"]), allow_insecure)
    digest = hashlib.sha256()
    total = 0
    with destination.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_file_bytes:
                raise RemoteDataPackageError(f"{item['role']} 下载内容超过允许大小")
            digest.update(chunk)
            handle.write(chunk)
        handle.flush()
        os.fsync(handle.fileno())
    if total != item["size_bytes"]:
        raise RemoteDataPackageError(f"{item['role']} 文件大小不一致")
    if digest.hexdigest() != item["sha256"]:
        raise RemoteDataPackageError(f"{item['role']} SHA-256 校验失败")


def verified_existing_package(package_path: Path, manifest_sha256: str, manifest: dict) -> bool:
    stored_manifest_path = package_path / "manifest.json"
    if not stored_manifest_path.is_file() or sha256_file(stored_manifest_path) != manifest_sha256:
        return False
    for item in manifest["files"].values():
        local_path = package_path / item["local_name"]
        if not local_path.is_file() or local_path.stat().st_size != item["size_bytes"]:
            return False
        if sha256_file(local_path) != item["sha256"]:
            return False
    return True


def build_pointer(root: Path, package_path: Path, manifest: dict, manifest_sha256: str) -> dict:
    return {
        "schema_version": POINTER_SCHEMA_VERSION,
        "package_id": manifest["package_id"],
        "data_period": manifest["data_period"],
        "generated_at": manifest["generated_at"],
        "source_commit": manifest["source_commit"],
        "manifest_sha256": manifest_sha256,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "package_path": str(package_path.resolve()),
        "role_paths": {
            role: str((package_path / item["local_name"]).resolve())
            for role, item in manifest["files"].items()
        },
        "root_path": str(root.resolve()),
    }


def sync_remote_data_package(
    manifest_url: str,
    root: str | Path,
    token_file: str | Path | None = None,
    session=None,
    allow_insecure: bool = False,
    timeout=DEFAULT_TIMEOUT,
    max_file_bytes=DEFAULT_MAX_FILE_BYTES,
) -> dict:
    root = Path(root)
    packages_root = root / "packages"
    packages_root.mkdir(parents=True, exist_ok=True)
    token = read_token(token_file)
    session = session or requests.Session()
    manifest, manifest_sha256, manifest_body = fetch_manifest(
        manifest_url,
        token=token,
        session=session,
        allow_insecure=allow_insecure,
        timeout=timeout,
    )
    ensure_not_rollback(root, manifest)
    package_path = packages_root / manifest["package_id"]
    if package_path.exists():
        if not verified_existing_package(package_path, manifest_sha256, manifest):
            raise PackageIntegrityError("相同 package_id 的本地内容与远端 manifest 不一致")
    else:
        temporary_path = packages_root / f".{manifest['package_id']}.partial"
        if temporary_path.exists():
            shutil.rmtree(temporary_path)
        temporary_path.mkdir(parents=True)
        try:
            for item in manifest["files"].values():
                download_file(
                    session,
                    item,
                    temporary_path / item["local_name"],
                    token,
                    allow_insecure,
                    timeout,
                    max_file_bytes,
                )
            (temporary_path / "manifest.json").write_bytes(manifest_body)
            if sha256_file(temporary_path / "manifest.json") != manifest_sha256:
                raise RemoteDataPackageError("落盘 manifest 与远端内容不一致")
            temporary_path.replace(package_path)
        except Exception:
            shutil.rmtree(temporary_path, ignore_errors=True)
            raise
    pointer = build_pointer(root, package_path, manifest, manifest_sha256)
    atomic_write_json(root / "latest_success.json", pointer)
    return pointer


def load_latest_success(root: str | Path) -> dict:
    root = Path(root).resolve()
    pointer_path = root / "latest_success.json"
    if not pointer_path.is_file():
        raise RemoteDataPackageError("尚无可回退的最近成功数据包")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RemoteDataPackageError("最近成功数据包指针损坏") from error
    if pointer.get("schema_version") != POINTER_SCHEMA_VERSION:
        raise RemoteDataPackageError("最近成功数据包指针版本不受支持")
    package_path = Path(str(pointer.get("package_path") or "")).resolve()
    packages_root = (root / "packages").resolve()
    try:
        relative_package_path = package_path.relative_to(packages_root)
    except ValueError as error:
        raise RemoteDataPackageError("最近成功数据包 package_path 越出配置根目录") from error
    if len(relative_package_path.parts) != 1 or relative_package_path.name != pointer.get("package_id"):
        raise RemoteDataPackageError("最近成功数据包 package_path 与 package_id 不一致")
    manifest_path = package_path / "manifest.json"
    if not manifest_path.is_file():
        raise RemoteDataPackageError("最近成功数据包缺少 manifest")
    manifest_body = manifest_path.read_bytes()
    if sha256_bytes(manifest_body) != pointer.get("manifest_sha256"):
        raise RemoteDataPackageError("最近成功数据包 manifest 校验失败")
    try:
        manifest = json.loads(manifest_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RemoteDataPackageError("最近成功数据包 manifest 损坏") from error
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("package_id") != pointer.get("package_id"):
        raise RemoteDataPackageError("最近成功数据包身份不一致")
    manifest_files = {
        str(item.get("role") or ""): item
        for item in manifest.get("files") or []
        if isinstance(item, dict)
    }
    role_paths = pointer.get("role_paths") or {}
    resolved_package_path = package_path.resolve()
    for role, expected_name in REQUIRED_ROLES.items():
        path = Path(str(role_paths.get(role) or ""))
        if not path.is_file():
            raise RemoteDataPackageError(f"最近成功数据包缺少 {role}")
        try:
            path.resolve().relative_to(resolved_package_path)
        except ValueError as error:
            raise RemoteDataPackageError(f"最近成功数据包 {role} 路径越界") from error
        if path.name != expected_name:
            raise RemoteDataPackageError(f"最近成功数据包 {role} 文件名非法")
        item = manifest_files.get(role) or {}
        expected_sha256 = str(item.get("sha256") or "")
        try:
            expected_size = int(item.get("size_bytes"))
        except (TypeError, ValueError) as error:
            raise RemoteDataPackageError(f"最近成功数据包 {role} 定义损坏") from error
        if not SHA256_PATTERN.fullmatch(expected_sha256):
            raise RemoteDataPackageError(f"最近成功数据包 {role} SHA-256 非法")
        if path.stat().st_size != expected_size or sha256_file(path) != expected_sha256:
            raise RemoteDataPackageError(f"最近成功数据包 {role} 校验失败")
    return pointer

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path


CONTRACT_VERSION = "store-workforce-monthly/v1"
CONTRACT_SCHEMA_VERSION = "site-workforce-contract/v0.1"
EXPECTED_COLUMN_COUNT = 25
CANONICAL_STORE_ID = re.compile(r"^L\d{4}$")
MONTH_VALUE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

SEMANTIC_FIELDS = (
    "store_id", "month", "month_start_headcount", "month_end_headcount", "month_average_headcount",
    "hire_count", "exit_count", "transfer_in_count", "transfer_out_count", "support_in_count",
    "support_out_count", "net_change", "manager_change_candidate", "confidence_level", "coverage_status",
    "cutoff_date", "event_coverage_status", "support_in_person_days", "support_out_person_days",
    "manager_change_candidate_count", "manager_change_first_date", "snapshot_coverage_days",
    "expected_snapshot_days", "store_coverage_status",
)
REQUIRED_FIELDS = SEMANTIC_FIELDS
NUMERIC_FIELDS = (
    "month_start_headcount", "month_end_headcount", "month_average_headcount", "hire_count", "exit_count",
    "transfer_in_count", "transfer_out_count", "support_in_count", "support_out_count", "net_change",
    "support_in_person_days", "support_out_person_days",
    "manager_change_candidate_count", "snapshot_coverage_days", "expected_snapshot_days",
)
NONNEGATIVE_FIELDS = tuple(field for field in NUMERIC_FIELDS if field != "net_change")
PERSONAL_FIELD_TOKENS = {
    "name", "person_name", "employee_name", "therapist_name", "姓名", "phone", "mobile", "手机号", "电话",
    "id_card", "identity_card", "身份证", "salary", "payroll", "薪资", "工资", "employee_id", "person_id",
    "therapist_id", "人员键", "员工编号", "个人排班", "schedule_detail",
}
BAD_COVERAGE = {
    "missing", "none", "failed", "unavailable",
    "缺失", "无覆盖", "不可用", "失败",
}
CONFIDENCE_MAP = {
    "high": "高", "high_confidence": "高", "高": "高", "高可信": "高",
    "medium": "中", "medium_confidence": "中", "middle": "中", "中": "中", "中可信": "中",
    "low": "低", "low_confidence": "低", "低": "低", "低可信": "低",
}


class WorkforceContractError(ValueError):
    pass


def normalize_header(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    value = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "_", value)
    return value.strip("_")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_bool(value):
    normalized = normalize_header(value)
    if normalized in {"1", "true", "yes", "y", "是", "有", "候选"}:
        return True
    if normalized in {"0", "false", "no", "n", "否", "无", "非候选"}:
        return False
    return None


def read_workforce_contract(path: str | Path | None) -> dict:
    if not path:
        return {}
    contract_path = Path(path)
    if not contract_path.is_file():
        raise WorkforceContractError(f"人员生产契约文件不存在：{contract_path}")
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise WorkforceContractError(f"人员生产契约不是合法 JSON：{error.msg}") from error
    if not isinstance(payload, dict):
        raise WorkforceContractError("人员生产契约必须是 JSON object")
    payload = dict(payload)
    payload["_path"] = str(contract_path)
    payload["_sha256"] = sha256_file(contract_path)
    return payload


def validate_contract(contract: dict) -> list[str]:
    if not contract:
        return ["缺少经数据发布方确认的人员生产契约"]
    issues = []
    if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        issues.append(f"人员生产契约 schema_version 必须为 {CONTRACT_SCHEMA_VERSION}")
    if contract.get("data_version") != CONTRACT_VERSION:
        issues.append(f"人员生产契约 data_version 必须为 {CONTRACT_VERSION}")
    expected_headers = contract.get("expected_headers")
    if not isinstance(expected_headers, list) or len(expected_headers) != EXPECTED_COLUMN_COUNT:
        issues.append(f"人员生产契约必须逐项列出精确 {EXPECTED_COLUMN_COUNT} 列表头")
    elif len(set(expected_headers)) != len(expected_headers) or not all(isinstance(value, str) and value for value in expected_headers):
        issues.append("人员生产契约表头必须是非空且不重复的字符串")
    if not contract.get("data_version_column"):
        issues.append("人员生产契约缺少 data_version_column")
    mapping = contract.get("field_mapping")
    if not isinstance(mapping, dict):
        issues.append("人员生产契约缺少 field_mapping")
    source_commit = str(contract.get("source_commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        issues.append("人员生产契约缺少40位生产 source_commit")
    return issues


def resolve_columns(headers: list[str], explicit_map: dict[str, str] | None = None) -> tuple[dict[str, str], list[str]]:
    explicit_map = explicit_map or {}
    resolved = {}
    issues = []
    unknown_semantics = sorted(set(explicit_map) - set(SEMANTIC_FIELDS))
    if unknown_semantics:
        issues.append(f"人员字段映射包含未知语义字段：{', '.join(unknown_semantics)}")
    for semantic in SEMANTIC_FIELDS:
        requested = explicit_map.get(semantic)
        if requested:
            if requested not in headers:
                issues.append(f"字段映射 {semantic} 指向不存在的列 {requested}")
            else:
                resolved[semantic] = requested
        elif semantic in REQUIRED_FIELDS:
            issues.append(f"缺少人员聚合字段的显式映射：{semantic}")
    duplicated_sources = sorted({value for value in resolved.values() if list(resolved.values()).count(value) > 1})
    if duplicated_sources:
        issues.append(f"同一生产列被映射到多个语义字段：{', '.join(duplicated_sources)}")
    return resolved, issues


def load_workforce_monthly(path: str | Path, contract: dict | None = None) -> dict:
    path = Path(path)
    if not path.is_file():
        raise WorkforceContractError(f"人员聚合文件不存在：{path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        raw_rows = list(reader)

    contract = contract or {}
    issues = validate_contract(contract)
    if len(headers) != EXPECTED_COLUMN_COUNT:
        issues.append(f"人员聚合 schema 应为 {EXPECTED_COLUMN_COUNT} 列，实际 {len(headers)} 列")
    expected_headers = contract.get("expected_headers")
    if isinstance(expected_headers, list) and headers != expected_headers:
        mismatch = next(
            (
                index for index, (actual, expected) in enumerate(zip(headers, expected_headers), start=1)
                if actual != expected
            ),
            min(len(headers), len(expected_headers)) + 1,
        )
        issues.append(f"人员聚合表头与正式契约不一致（首个差异列 {mismatch}）")
    personal_headers = [header for header in headers if normalize_header(header) in PERSONAL_FIELD_TOKENS]
    personal_headers.extend(
        header for header in headers
        if re.search(
            r"(^|_)(employee|person|therapist|staff|worker)_(id|key|name|phone|mobile|identity|salary|payroll|schedule)($|_)",
            normalize_header(header),
        )
        or re.search(
            r"(^|_)(phone|mobile|id_card|identity_card|salary|payroll)($|_)",
            normalize_header(header),
        )
    )
    if personal_headers:
        issues.append(f"人员聚合文件包含禁止的个人级字段：{', '.join(dict.fromkeys(personal_headers))}")

    data_version_column = contract.get("data_version_column")
    if data_version_column and data_version_column not in headers:
        issues.append(f"人员聚合缺少 data_version 列：{data_version_column}")
    elif data_version_column:
        versions = sorted({str(row.get(data_version_column) or "").strip() for row in raw_rows})
        if versions != [contract.get("data_version")]:
            issues.append(f"人员聚合 data_version 不符合正式契约：{', '.join(versions) or '<空>'}")

    mapping, mapping_issues = resolve_columns(headers, contract.get("field_mapping"))
    issues.extend(mapping_issues)
    rows = []
    seen = set()
    if issues:
        return {
            "contract_version": CONTRACT_VERSION,
            "contract_schema_version": contract.get("schema_version"),
            "contract_path": contract.get("_path"),
            "contract_sha256": contract.get("_sha256"),
            "source_commit": contract.get("source_commit"),
            "data_version": contract.get("data_version"),
            "path": str(path),
            "sha256": sha256_file(path),
            "headers": headers,
            "column_count": len(headers),
            "row_count": len(raw_rows),
            "column_mapping": mapping,
            "rows": [],
            "issues": list(dict.fromkeys(issues)),
        }
    for line_number, raw in enumerate(raw_rows, start=2):
        if any(field not in mapping for field in REQUIRED_FIELDS):
            break
        store_id = str(raw.get(mapping["store_id"], "")).strip()
        month = str(raw.get(mapping["month"], "")).strip()[:7]
        row = {"store_id": store_id, "month": month, "source_line": line_number}
        for field in NUMERIC_FIELDS:
            row[field] = number(raw.get(mapping[field])) if field in mapping else None
        row["manager_change_candidate"] = parse_bool(raw.get(mapping["manager_change_candidate"]))
        confidence_raw = str(raw.get(mapping["confidence_level"], "")).strip()
        row["confidence_level"] = CONFIDENCE_MAP.get(normalize_header(confidence_raw), confidence_raw or "未知")
        row["coverage_status"] = str(raw.get(mapping["coverage_status"], "")).strip()
        row["cutoff_date"] = str(raw.get(mapping["cutoff_date"], "")).strip()[:10]
        if "event_coverage_status" in mapping:
            row["event_coverage_status"] = str(raw.get(mapping["event_coverage_status"], "")).strip()
        else:
            row["event_coverage_status"] = "未单列"
        row["manager_change_first_date"] = (
            str(raw.get(mapping["manager_change_first_date"], "")).strip()[:10]
            if "manager_change_first_date" in mapping else ""
        )
        row["store_coverage_status"] = (
            str(raw.get(mapping["store_coverage_status"], "")).strip()
            if "store_coverage_status" in mapping else "未单列"
        )

        if not CANONICAL_STORE_ID.fullmatch(store_id):
            issues.append(f"第 {line_number} 行不是 canonical Lxxxx 门店编号：{store_id or '<空>'}")
        if not MONTH_VALUE.fullmatch(month):
            issues.append(f"第 {line_number} 行月份非法：{month or '<空>'}")
        key = (store_id, month)
        if key in seen:
            issues.append(f"人员聚合存在重复门店月：{store_id}/{month}")
        seen.add(key)
        for field in NONNEGATIVE_FIELDS:
            if row[field] is not None and row[field] < 0:
                issues.append(f"第 {line_number} 行 {field} 不能为负数")
        rows.append(row)

    return {
        "contract_version": CONTRACT_VERSION,
        "contract_schema_version": contract.get("schema_version"),
        "contract_path": contract.get("_path"),
        "contract_sha256": contract.get("_sha256"),
        "source_commit": contract.get("source_commit"),
        "data_version": contract.get("data_version"),
        "path": str(path),
        "sha256": sha256_file(path),
        "headers": headers,
        "column_count": len(headers),
        "row_count": len(raw_rows),
        "column_mapping": mapping,
        "rows": rows,
        "issues": list(dict.fromkeys(issues)),
    }


def build_workforce_gate(dataset: dict, target_month: str, scope_store_ids, candidate_store_ids) -> dict:
    rows = [row for row in dataset.get("rows", []) if row.get("month") == target_month]
    valid_rows = [row for row in rows if CANONICAL_STORE_ID.fullmatch(row.get("store_id", ""))]
    by_store = {row["store_id"]: row for row in valid_rows}
    dataset_rows = dataset.get("rows", [])
    dataset_store_ids = sorted({row.get("store_id") for row in dataset_rows if row.get("store_id")})
    dataset_months = sorted({row.get("month") for row in dataset_rows if row.get("month")})
    scope_store_ids = sorted(set(scope_store_ids))
    candidate_store_ids = list(dict.fromkeys(candidate_store_ids))
    scope_covered = [store_id for store_id in scope_store_ids if store_id in by_store]
    scope_missing = [store_id for store_id in scope_store_ids if store_id not in by_store]
    candidate_missing = [store_id for store_id in candidate_store_ids if store_id not in by_store]
    scope_coverage = len(scope_covered) / len(scope_store_ids) if scope_store_ids else 1.0
    required_values = list(NUMERIC_FIELDS) + [
        "manager_change_candidate", "confidence_level", "coverage_status", "event_coverage_status",
        "store_coverage_status", "cutoff_date",
    ]
    candidate_rows = [by_store[store_id] for store_id in candidate_store_ids if store_id in by_store]
    expected_values = len(candidate_rows) * len(required_values)
    present_values = sum(
        value not in (None, "", "未知")
        for row in candidate_rows
        for value in (row.get(field) for field in required_values)
    )
    field_completeness = present_values / expected_values if expected_values else (1.0 if not candidate_store_ids else 0.0)
    mapping_completeness = len(valid_rows) / len(rows) if rows else 0.0
    confidence_levels = sorted({row.get("confidence_level", "未知") for row in candidate_rows})
    cutoff_dates = sorted({row.get("cutoff_date") for row in candidate_rows if row.get("cutoff_date")})
    bad_snapshot_coverage_stores = [
        row["store_id"] for row in candidate_rows if normalize_header(row.get("coverage_status")) in BAD_COVERAGE
    ]
    issues = list(dataset.get("issues", []))
    if not rows:
        issues.append(f"人员聚合没有目标完整月 {target_month}")
    if scope_coverage < 0.8:
        issues.append(f"人员数据加盟/合资门店覆盖率不足（{scope_coverage * 100:.1f}%）")
    if candidate_missing:
        issues.append(f"人员数据缺少候选门店：{', '.join(candidate_missing)}")
    if mapping_completeness < 1.0:
        issues.append(f"人员门店映射完整度不足（{mapping_completeness * 100:.1f}%）")
    if field_completeness < 1.0:
        issues.append(f"候选门店人员字段完整度不足（{field_completeness * 100:.1f}%）")
    if any(level not in {"中", "高"} for level in confidence_levels):
        issues.append(f"候选门店人员可信等级不足：{', '.join(confidence_levels) or '未知'}")
    if bad_snapshot_coverage_stores:
        issues.append(f"候选门店人数快照覆盖不足：{', '.join(bad_snapshot_coverage_stores)}")

    return {
        "ready": not issues,
        "target_month": target_month,
        "data_cutoff_dates": cutoff_dates,
        "source_row_count": dataset.get("row_count", len(dataset_rows)),
        "source_store_count": len(dataset_store_ids),
        "source_months": dataset_months,
        "scope_store_count": len(scope_store_ids),
        "covered_scope_store_count": len(scope_covered),
        "missing_scope_stores": scope_missing,
        "scope_coverage": scope_coverage,
        "mapping_completeness": mapping_completeness,
        "field_completeness": field_completeness,
        "confidence_levels": confidence_levels,
        "candidate_store_count": len(candidate_store_ids),
        "missing_candidate_stores": candidate_missing,
        "trend_only_months": sorted({row.get("month") for row in dataset.get("rows", []) if row.get("month", "") > target_month}),
        "issues": list(dict.fromkeys(issues)),
        "message": "；".join(dict.fromkeys(issues)) if issues else (
            f"人员数据截止 {max(cutoff_dates) if cutoff_dates else '待确认'}；候选覆盖 100.0%；"
            f"字段完整度 {field_completeness * 100:.1f}%；可信等级 {','.join(confidence_levels)}"
        ),
    }

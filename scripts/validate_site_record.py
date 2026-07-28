"""Minimal runtime validator for the site_record/v0.1 contract.

The repository does not depend on a general JSON Schema runtime. This validator
enforces the contract rules that protect the formal record boundary, while the
JSON Schema remains the source of field shapes and enum definitions.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_format(value: str, format_name: str, path: str) -> None:
    try:
        if format_name == "date":
            date.fromisoformat(value)
        elif format_name == "date-time":
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path}格式不是{format_name}") from exc


def _validate_simple_value(value: Any, spec: dict[str, Any], path: str) -> None:
    if "enum" in spec and value not in spec["enum"]:
        raise ValueError(f"{path}不在允许枚举中")
    expected = spec.get("type")
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        type_checks = {
            "null": value is None,
            "string": isinstance(value, str),
            "number": _is_number(value),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "array": isinstance(value, list),
            "object": isinstance(value, dict),
        }
        if not any(type_checks.get(item, False) for item in types):
            raise ValueError(f"{path}类型不符合schema")
    if isinstance(value, str):
        if spec.get("minLength", 0) and len(value) < spec["minLength"]:
            raise ValueError(f"{path}不能为空")
        if spec.get("format"):
            _validate_format(value, spec["format"], path)
    if _is_number(value):
        if "minimum" in spec and value < spec["minimum"]:
            raise ValueError(f"{path}小于最小值")
        if "exclusiveMinimum" in spec and value <= spec["exclusiveMinimum"]:
            raise ValueError(f"{path}必须大于最小值")
        if "maximum" in spec and value > spec["maximum"]:
            raise ValueError(f"{path}超过最大值")
    if isinstance(value, list):
        if spec.get("uniqueItems") and len({json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value}) != len(value):
            raise ValueError(f"{path}包含重复项")
        item_spec = spec.get("items")
        if item_spec:
            for index, item in enumerate(value):
                _validate_simple_value(item, item_spec, f"{path}[{index}]")
    if isinstance(value, dict):
        required = spec.get("required", [])
        missing = [item for item in required if item not in value]
        if missing:
            raise ValueError(f"{path}缺少字段: {', '.join(missing)}")
        properties = spec.get("properties", {})
        if spec.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ValueError(f"{path}包含未定义字段: {', '.join(unknown)}")
        for key, item in value.items():
            if key in properties:
                _validate_simple_value(item, properties[key], f"{path}.{key}")


def _field_value_spec(field_schema: dict[str, Any]) -> dict[str, Any]:
    for item in field_schema.get("allOf", []):
        value_spec = item.get("properties", {}).get("value")
        if value_spec:
            return value_spec
    return {}


def _validate_value_options(value: Any, spec: dict[str, Any], path: str) -> None:
    options = spec.get("oneOf")
    if not options:
        _validate_simple_value(value, spec, path)
        return
    errors = []
    for option in options:
        try:
            _validate_simple_value(value, option, path)
            return
        except ValueError as exc:
            errors.append(str(exc))
    raise ValueError(f"{path}不符合任何允许结构")


def validate_site_record(record: dict[str, Any], schema: dict[str, Any]) -> None:
    if record.get("schema_version") != schema["properties"]["schema_version"]["const"]:
        raise ValueError("schema_version不受支持")
    missing = [field for field in schema["required"] if field not in record]
    if missing:
        raise ValueError(f"正式记录缺少核心字段: {', '.join(missing)}")
    unknown = sorted(set(record) - set(schema["properties"]))
    if unknown:
        raise ValueError(f"正式记录包含未定义字段: {', '.join(unknown)}")

    envelope_schema = schema["$defs"]["fieldEnvelope"]
    envelope_required = envelope_schema["required"]
    allowed_layers = set(envelope_schema["properties"]["record_layer"]["enum"])
    allowed_confirmation = set(
        envelope_schema["properties"]["confirmation_status"]["enum"]
    )
    for field, field_schema in schema["properties"].items():
        if field == "schema_version" or field not in record:
            continue
        envelope = record[field]
        if not isinstance(envelope, dict):
            raise ValueError(f"{field}必须使用字段信封")
        missing_envelope = [item for item in envelope_required if item not in envelope]
        if missing_envelope:
            raise ValueError(f"{field}缺少信封字段: {', '.join(missing_envelope)}")
        unknown_envelope = sorted(
            set(envelope) - set(envelope_schema["properties"])
        )
        if unknown_envelope:
            raise ValueError(f"{field}包含未定义信封字段")
        layer = envelope["record_layer"]
        confirmation = envelope["confirmation_status"]
        confirmed_by = envelope["confirmed_by"]
        if layer not in allowed_layers or confirmation not in allowed_confirmation:
            raise ValueError(f"{field}记录层或确认状态无效")
        if not isinstance(envelope["source_refs"], list) or not envelope["source_refs"]:
            raise ValueError(f"{field}.source_refs不能为空")
        if len(set(envelope["source_refs"])) != len(envelope["source_refs"]):
            raise ValueError(f"{field}.source_refs不能重复")
        if layer == "原始资料事实":
            if confirmation != "无需确认" or confirmed_by is not None:
                raise ValueError(f"{field}的原始资料事实不得伪装成负责人确认")
        elif layer == "AI提取候选事实":
            if confirmation != "待负责人确认" or confirmed_by is not None:
                raise ValueError(f"{field}的AI候选不能伪装成负责人确认")
        elif layer in {"负责人确认", "正式业务状态"}:
            if confirmation != "已确认" or not isinstance(confirmed_by, str) or not confirmed_by:
                raise ValueError(f"{field}缺少真实确认人或可信系统")
        elif layer == "AI经营判断":
            if confirmation != "无需确认" or confirmed_by is not None:
                raise ValueError(f"{field}的AI经营判断不能伪装成正式状态")
        _validate_value_options(
            envelope["value"], _field_value_spec(field_schema), f"{field}.value"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a site_record/v0.1 JSON file.")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--record", required=True)
    args = parser.parse_args()
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    validate_site_record(record, schema)
    print("site_record/v0.1校验通过")


if __name__ == "__main__":
    main()

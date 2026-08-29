from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy


ANALYSIS_RECORD_SCHEMA_VERSION = "professional-analysis-record/v0.1"
ANALYSIS_CATALOG_SCHEMA_VERSION = "professional-analysis-catalog/v0.1"
ANALYSIS_TYPE = "franchise_operating_review"
CANONICAL_STORE_ID = re.compile(r"^L\d{4}$")


def _stable_id(prefix: str, payload: dict, length: int = 24) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:length]}"


def _input_identity(manifest: dict) -> dict:
    inputs = manifest.get("inputs") or {}
    fingerprints = []
    for source_name in ("operating", "workforce", "candidate_freeze"):
        source = inputs.get(source_name)
        if not source:
            continue
        fingerprints.append(
            {
                "source": source_name,
                "sha256": source.get("sha256"),
                "data_version": source.get("data_version"),
                "source_version": source.get("source_commit"),
                "row_count": source.get("row_count"),
            }
        )
    workforce = inputs.get("workforce") or {}
    if workforce.get("contract_sha256"):
        fingerprints.append(
            {
                "source": "workforce_contract",
                "sha256": workforce.get("contract_sha256"),
                "data_version": manifest.get("workforce_contract_version"),
                "source_version": workforce.get("source_commit"),
                "row_count": None,
            }
        )
    return {
        "source_run_id": manifest.get("run_id"),
        "analysis_pipeline_version": manifest.get("rule_version"),
        "input_fingerprints": fingerprints,
    }


def _personnel_sections(personnel: dict) -> tuple[dict, dict, dict]:
    if not personnel:
        return {}, {}, {"availability": "unknown"}
    direct_keys = (
        "available",
        "target_month",
        "confidence_level",
        "coverage_status",
        "event_coverage_status",
        "cutoff_date",
        "month_start_headcount",
        "month_end_headcount",
        "month_average_headcount",
    )
    statistical_keys = (
        "average_headcount_previous_3m",
        "average_headcount_recent_2m",
        "average_headcount_change",
        "recent_2m_hires",
        "recent_2m_exits",
        "recent_2m_transfer_in",
        "recent_2m_transfer_out",
        "recent_2m_support_in",
        "recent_2m_support_out",
    )
    direct = {key: deepcopy(personnel.get(key)) for key in direct_keys if key in personnel}
    statistical = {
        key: deepcopy(personnel.get(key)) for key in statistical_keys if key in personnel
    }
    proxies = {
        "workdays_per_average_therapist": deepcopy(
            personnel.get("workdays_per_average_therapist")
        ),
        "manager_change_candidate": deepcopy(personnel.get("manager_change_candidate")),
        "evidence_role": personnel.get("evidence_role"),
        "note": personnel.get("note"),
    }
    return direct, statistical, proxies


def _confidence(store: dict, business_review: dict) -> dict:
    personnel = store.get("personnel_history") or {}
    workforce_level = personnel.get("confidence_level") if personnel.get("available") else None
    ready = business_review.get("status") == "ready_for_business_review"
    if not ready:
        level = "insufficient"
    elif workforce_level in {"中", "高"}:
        level = "medium"
    else:
        level = "limited"
    return {
        "level": level,
        "operating_gate": (
            "passed"
            if (business_review.get("data_gate") or {}).get("operating", {}).get("ready")
            else "not_passed"
        ),
        "workforce_gate": (
            "passed"
            if (business_review.get("data_gate") or {}).get("workforce", {}).get("ready")
            else "not_passed"
        ),
        "workforce_data_trust": workforce_level or "unknown",
        "note": (
            "人员证据只用于交叉解释；低可信或缺失时不支持较强人员结论。"
        ),
    }


def _latest_operating_facts(store: dict) -> dict:
    latest = deepcopy(store.get("latest_month_facts") or {})
    source_ratio = latest.pop("rent_ratio", None)
    recent_contract = store.get("recent_three_month_operating") or {}
    months = recent_contract.get("months") or []
    formal_ratio = deepcopy((months[-1].get("rent_to_sales_ratio") if months else None))
    latest["rent_to_sales_ratio"] = formal_ratio
    latest["source_rent_ratio_diagnostic"] = source_ratio
    return latest


def _analysis_id_payload(
    run_id: str,
    analysis_type: str,
    canonical_object_type: str,
    canonical_id: str,
    period: dict,
    rule_version: str,
) -> dict:
    return {
        "analysis_type": analysis_type,
        "source_run_id": run_id,
        "canonical_object_type": canonical_object_type,
        "canonical_object_id": canonical_id,
        "period": period,
        "rule_version": rule_version,
    }


def build_analysis_catalog(business_review: dict, manifest: dict) -> dict:
    run_id = manifest.get("run_id")
    target_month = business_review.get("target_month")
    rule_version = manifest.get("candidate_rule_version")
    generated_at = manifest.get("generated_at")
    input_identity = _input_identity(manifest)
    records = []
    for store in business_review.get("stores") or []:
        store_id = store.get("store_id")
        period = {"grain": "month", "start": target_month, "end": target_month}
        analysis_id = _stable_id(
            "ana",
            _analysis_id_payload(
                run_id,
                ANALYSIS_TYPE,
                "store",
                store_id,
                period,
                rule_version,
            ),
        )
        personnel_facts, personnel_statistics, personnel_proxies = _personnel_sections(
            store.get("personnel_history") or {}
        )
        candidate_check = deepcopy(store.get("candidate_rule_check") or {})
        conclusion = {
            "candidate_triggered": bool(store.get("candidate_triggered")),
            "candidate_id": store.get("candidate_id"),
            "trigger_codes": deepcopy(store.get("trigger_codes") or []),
            "operating_status": store.get("operating_status") or "unknown",
            "revenue_change_rank": store.get("revenue_change_rank"),
            "rule_check": candidate_check,
            "interpretation": (
                "达到现行候选规则，需由业务人员评审后决定是否形成正式事项。"
                if store.get("candidate_triggered")
                else "未达到现行候选规则；不等于门店不存在经营问题。"
            ),
        }
        gaps = deepcopy(store.get("evidence_gaps") or [])
        records.append(
            {
                "schema_version": ANALYSIS_RECORD_SCHEMA_VERSION,
                "analysis_id": analysis_id,
                "analysis_type": ANALYSIS_TYPE,
                "canonical_object": {
                    "object_type": "store",
                    "canonical_id": store_id,
                    "display_name": store.get("store_name") or None,
                },
                "analysis_period": period,
                "input_identity": deepcopy(input_identity),
                "rule_version": rule_version,
                "confidence": _confidence(store, business_review),
                "evidence": {
                    "direct_facts": {
                        "latest_month": _latest_operating_facts(store),
                        "recent_three_month_operating": deepcopy(
                            store.get("recent_three_month_operating") or {}
                        ),
                        "personnel_aggregate": personnel_facts,
                    },
                    "statistical_differences": {
                        "operating": deepcopy(store.get("statistical_differences") or {}),
                        "personnel": personnel_statistics,
                    },
                    "proxy_metrics": {
                        "personnel": personnel_proxies,
                        "peer_evidence": deepcopy(store.get("peer_evidence") or {}),
                    },
                    "hypotheses": deepcopy(store.get("possible_explanations") or []),
                },
                "evidence_gaps": gaps,
                "conclusion": conclusion,
                "suggestions": [
                    {"type": "human_verification", "text": gap} for gap in gaps
                ],
                "generated_at": generated_at,
                "dashboard_write_allowed": False,
            }
        )
    catalog_identity = {
        "source_run_id": run_id,
        "record_schema_version": ANALYSIS_RECORD_SCHEMA_VERSION,
        "analysis_ids": [record["analysis_id"] for record in records],
    }
    payload = {
        "schema_version": ANALYSIS_CATALOG_SCHEMA_VERSION,
        "analysis_record_schema_version": ANALYSIS_RECORD_SCHEMA_VERSION,
        "catalog_id": _stable_id("catalog", catalog_identity),
        "source_run_id": run_id,
        "analysis_type": ANALYSIS_TYPE,
        "generated_at": generated_at,
        "dashboard_write_allowed": False,
        "records": records,
    }
    return validate_analysis_catalog(payload)


def validate_analysis_catalog(payload: dict) -> dict:
    if payload.get("schema_version") != ANALYSIS_CATALOG_SCHEMA_VERSION:
        raise ValueError("专业分析目录版本不支持")
    if payload.get("analysis_record_schema_version") != ANALYSIS_RECORD_SCHEMA_VERSION:
        raise ValueError("专业分析记录版本不支持")
    if payload.get("dashboard_write_allowed") is not False:
        raise ValueError("专业分析目录不得允许写入Dashboard")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("专业分析目录 records 必须为数组")
    seen = set()
    for record in records:
        if record.get("schema_version") != ANALYSIS_RECORD_SCHEMA_VERSION:
            raise ValueError("专业分析记录版本不支持")
        if record.get("analysis_type") != payload.get("analysis_type"):
            raise ValueError("专业分析记录类型与目录不一致")
        if record.get("dashboard_write_allowed") is not False:
            raise ValueError("专业分析记录不得允许写入Dashboard")
        analysis_id = record.get("analysis_id")
        if not analysis_id or analysis_id in seen:
            raise ValueError("专业分析记录 analysis_id 为空或重复")
        seen.add(analysis_id)
        canonical_object = record.get("canonical_object") or {}
        object_type = canonical_object.get("object_type")
        canonical_id = canonical_object.get("canonical_id")
        if not object_type or not canonical_id:
            raise ValueError("专业分析记录缺少 canonical 对象类型或编号")
        if record.get("analysis_type") == ANALYSIS_TYPE and (
            object_type != "store"
            or not CANONICAL_STORE_ID.fullmatch(str(canonical_id or ""))
        ):
            raise ValueError("加盟经营分析必须使用 canonical Lxxxx 门店编号")
        period = record.get("analysis_period") or {}
        if not period.get("grain") or not period.get("start") or not period.get("end"):
            raise ValueError("专业分析记录月份范围非法")
        if record.get("analysis_type") == ANALYSIS_TYPE and (
            period.get("grain") != "month" or period.get("start") != period.get("end")
        ):
            raise ValueError("加盟经营分析必须对应单一自然月")
        rule_version = record.get("rule_version")
        input_identity = record.get("input_identity") or {}
        if not rule_version or input_identity.get("source_run_id") != payload.get("source_run_id"):
            raise ValueError("专业分析记录规则或来源运行身份缺失")
        expected_id = _stable_id(
            "ana",
            _analysis_id_payload(
                payload.get("source_run_id"),
                record.get("analysis_type"),
                object_type,
                canonical_id,
                period,
                rule_version,
            ),
        )
        if analysis_id != expected_id:
            raise ValueError("专业分析记录 analysis_id 与共同身份不一致")
        required = {
            "confidence",
            "evidence",
            "evidence_gaps",
            "conclusion",
            "suggestions",
            "generated_at",
        }
        missing = sorted(required - set(record))
        if missing:
            raise ValueError(f"专业分析记录缺少字段：{','.join(missing)}")
    expected_catalog_id = _stable_id(
        "catalog",
        {
            "source_run_id": payload.get("source_run_id"),
            "record_schema_version": ANALYSIS_RECORD_SCHEMA_VERSION,
            "analysis_ids": [record["analysis_id"] for record in records],
        },
    )
    if payload.get("catalog_id") != expected_catalog_id:
        raise ValueError("专业分析目录 catalog_id 与内容不一致")
    return payload

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from services.professional_analysis import validate_analysis_catalog


FEEDBACK_SCHEMA_VERSION = "professional-analysis-feedback/v0.1"
CALIBRATION_SCHEMA_VERSION = "professional-analysis-calibration-summary/v0.1"
REVIEW_STATUSES = (
    "accepted",
    "false_positive",
    "continue_observation",
    "data_missing",
    "known_special_cause",
)
ACTION_STATUSES = ("planned", "in_progress", "completed", "cancelled")
OUTCOME_STATUSES = ("observed", "not_observed", "inconclusive")


def _stable_hash(payload) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _exact_keys(payload: dict, required: set[str], optional: set[str], label: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} 必须是对象")
    missing = sorted(required - set(payload))
    extra = sorted(set(payload) - required - optional)
    if missing:
        raise ValueError(f"{label} 缺少字段：{','.join(missing)}")
    if extra:
        raise ValueError(f"{label} 包含未知字段：{','.join(extra)}")


def _analysis_reference(record: dict) -> dict:
    return {
        "analysis_id": record["analysis_id"],
        "canonical_object": deepcopy(record["canonical_object"]),
        "analysis_period": deepcopy(record["analysis_period"]),
        "rule_version": record["rule_version"],
    }


def _validate_reference(feedback: dict, analysis: dict) -> None:
    feedback_object = feedback.get("canonical_object") or {}
    analysis_object = analysis.get("canonical_object") or {}
    _exact_keys(
        feedback_object,
        {"object_type", "canonical_id"},
        {"display_name"},
        "反馈 canonical object",
    )
    if (
        feedback_object.get("object_type") != analysis_object.get("object_type")
        or feedback_object.get("canonical_id") != analysis_object.get("canonical_id")
    ):
        raise ValueError("反馈 canonical object 与原始分析不匹配")
    feedback_period = feedback.get("analysis_period") or {}
    _exact_keys(
        feedback_period,
        {"grain", "start", "end"},
        set(),
        "反馈分析期间",
    )
    if feedback_period != analysis.get("analysis_period"):
        raise ValueError("反馈分析期间与原始分析不匹配")
    if feedback.get("rule_version") != analysis.get("rule_version"):
        raise ValueError("反馈规则版本与原始分析不匹配")


def _validate_review(review: dict) -> None:
    _exact_keys(
        review,
        {"status", "reviewed_at", "reviewer_id", "note", "special_cause"},
        set(),
        "人工评审",
    )
    if review.get("status") not in REVIEW_STATUSES:
        raise ValueError("人工评审状态不支持")
    if not review.get("reviewed_at") or not review.get("reviewer_id"):
        raise ValueError("人工评审缺少时间或评审人")
    if review.get("status") == "known_special_cause" and not review.get("special_cause"):
        raise ValueError("已知特殊原因必须提供 special_cause")
    if review.get("status") != "known_special_cause" and review.get("special_cause") is not None:
        raise ValueError("非特殊原因评审不得填写 special_cause")


def _validate_actions(actions) -> None:
    if actions is None:
        return
    if not isinstance(actions, list):
        raise ValueError("执行动作必须为数组或 null")
    seen = set()
    for action in actions:
        _exact_keys(
            action,
            {"action_id", "status", "summary", "updated_at"},
            set(),
            "执行动作",
        )
        if not action.get("action_id") or action["action_id"] in seen:
            raise ValueError("执行动作 action_id 为空或重复")
        seen.add(action["action_id"])
        if action.get("status") not in ACTION_STATUSES:
            raise ValueError("执行动作状态不支持")
        if not action.get("summary") or not action.get("updated_at"):
            raise ValueError("执行动作缺少摘要或更新时间")


def _validate_outcome(outcome) -> None:
    if outcome is None:
        return
    _exact_keys(
        outcome,
        {"outcome_id", "status", "summary", "observed_at", "source_reference"},
        set(),
        "后续业务结果",
    )
    if outcome.get("status") not in OUTCOME_STATUSES:
        raise ValueError("后续业务结果状态不支持")
    if not outcome.get("outcome_id") or not outcome.get("summary") or not outcome.get("observed_at"):
        raise ValueError("后续业务结果缺少身份、摘要或观察时间")


def validate_feedback_export(payload: dict, catalog: dict) -> tuple[list[dict], int]:
    validate_analysis_catalog(catalog)
    _exact_keys(
        payload,
        {"schema_version", "export_id", "source_system", "exported_at", "feedbacks"},
        set(),
        "反馈导出",
    )
    if payload.get("schema_version") != FEEDBACK_SCHEMA_VERSION:
        raise ValueError("反馈导出版本不支持")
    if payload.get("source_system") != "lann-dashboard":
        raise ValueError("反馈必须来自 lann-dashboard 正式导出")
    if not payload.get("export_id") or not payload.get("exported_at"):
        raise ValueError("反馈导出缺少身份或时间")
    feedbacks = payload.get("feedbacks")
    if not isinstance(feedbacks, list):
        raise ValueError("反馈导出 feedbacks 必须为数组")

    analyses = {record["analysis_id"]: record for record in catalog["records"]}
    by_feedback_id = {}
    analysis_to_feedback = {}
    normalized = []
    idempotent_duplicates = 0
    for feedback in feedbacks:
        _exact_keys(
            feedback,
            {
                "feedback_id",
                "analysis_id",
                "canonical_object",
                "analysis_period",
                "rule_version",
                "review",
                "actions",
                "outcome",
            },
            set(),
            "分析反馈",
        )
        feedback_id = feedback.get("feedback_id")
        if not feedback_id:
            raise ValueError("分析反馈 feedback_id 不能为空")
        fingerprint = _stable_hash(feedback)
        if feedback_id in by_feedback_id:
            if by_feedback_id[feedback_id] != fingerprint:
                raise ValueError("同一 feedback_id 出现冲突内容")
            idempotent_duplicates += 1
            continue
        analysis_id = feedback.get("analysis_id")
        analysis = analyses.get(analysis_id)
        if analysis is None:
            raise ValueError("反馈 analysis_id 不存在于原始分析目录")
        if analysis_id in analysis_to_feedback:
            raise ValueError("同一原始分析出现多个不同 feedback_id")
        _validate_reference(feedback, analysis)
        _validate_review(feedback.get("review"))
        _validate_actions(feedback.get("actions"))
        _validate_outcome(feedback.get("outcome"))
        by_feedback_id[feedback_id] = fingerprint
        analysis_to_feedback[analysis_id] = feedback_id
        normalized.append(deepcopy(feedback))
    return normalized, idempotent_duplicates


def build_calibration_summary(
    catalog: dict,
    feedback_export: dict,
    generated_at: str,
) -> dict:
    catalog = validate_analysis_catalog(deepcopy(catalog))
    feedbacks, duplicate_count = validate_feedback_export(feedback_export, catalog)
    by_analysis = {row["analysis_id"]: row for row in feedbacks}
    review_counts = {status: 0 for status in REVIEW_STATUSES}
    reviewed_records = []
    unreviewed = []
    missing_action_linkage = []
    missing_outcome = []
    with_actions = 0
    with_outcomes = 0
    for analysis in catalog["records"]:
        reference = _analysis_reference(analysis)
        feedback = by_analysis.get(analysis["analysis_id"])
        if feedback is None:
            unreviewed.append(reference)
            continue
        review_status = feedback["review"]["status"]
        review_counts[review_status] += 1
        actions = feedback.get("actions")
        outcome = feedback.get("outcome")
        if actions is None:
            action_linkage_status = "unknown"
            missing_action_linkage.append(reference)
        elif actions:
            action_linkage_status = "present"
            with_actions += 1
        else:
            action_linkage_status = "confirmed_none"
        if outcome is None:
            outcome_status = "unknown"
            missing_outcome.append(reference)
        else:
            outcome_status = "present"
            with_outcomes += 1
        reviewed_records.append(
            {
                **reference,
                "feedback_id": feedback["feedback_id"],
                "review_status": review_status,
                "action_linkage_status": action_linkage_status,
                "outcome_linkage_status": outcome_status,
            }
        )

    summary_identity = {
        "catalog_id": catalog["catalog_id"],
        "feedback_export_id": feedback_export["export_id"],
        "feedback_fingerprint": _stable_hash(feedbacks),
    }
    return {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "summary_id": f"cal_{_stable_hash(summary_identity)[:24]}",
        "status": "ready",
        "generated_at": generated_at,
        "dashboard_write_allowed": False,
        "source": {
            "analysis_catalog_id": catalog["catalog_id"],
            "analysis_catalog_run_id": catalog["source_run_id"],
            "feedback_export_id": feedback_export["export_id"],
            "feedback_exported_at": feedback_export["exported_at"],
            "feedback_source_system": feedback_export["source_system"],
        },
        "counts": {
            "total_analyses": len(catalog["records"]),
            "reviewed_analyses": len(reviewed_records),
            "review_statuses": review_counts,
            "analyses_with_actions": with_actions,
            "analyses_with_outcomes": with_outcomes,
            "idempotent_duplicate_feedback_rows": duplicate_count,
        },
        "reviewed_records": reviewed_records,
        "unreviewed_analyses": unreviewed,
        "unknown_action_linkage": missing_action_linkage,
        "missing_outcomes": missing_outcome,
        "calibration_policy": {
            "original_analysis_immutable": True,
            "automatic_rule_change_allowed": False,
            "reason": "人工评审与后续结果只形成校准样本；单次反馈不得自动修改分析规则。",
        },
    }

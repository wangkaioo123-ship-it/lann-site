"""Publish strict, immutable Site analysis DTOs for Dashboard pull."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from services.franchise_operating_review import REVIEW_SCHEMA_VERSION
from services.franchise_review_display import (
    BUSINESS_REVIEW_SCHEMA_VERSION, THREE_MONTH_OPERATING_SCHEMA_VERSION,
    validate_three_month_operating_contract,
)
from services.professional_analysis import (
    ANALYSIS_CATALOG_SCHEMA_VERSION, ANALYSIS_RECORD_SCHEMA_VERSION,
    validate_analysis_catalog,
)

EXPORT_SCHEMA_VERSION = "site-dashboard-analysis-export/v0.1"
POINTER_SCHEMA_VERSION = "site-dashboard-analysis-pointer/v0.1"
RUN_SCHEMA_VERSION = "franchise-operating-run/v0.1"
DEFAULT_SOURCE_ROOT = Path("data/staging/franchise_operating_reviews")
DEFAULT_EXPORT_ROOT = Path("data/exports/dashboard-v0.1")
DEFAULT_SUMMARY_PATH = Path("data/staging/site_performance_summary_bi_feishu_rent.csv")
SUMMARY_FILE_NAME = "site_performance_summary_bi_feishu_rent.csv"
EXPORT_MANIFEST_FILE_NAME = "export_manifest.json"
RUN_FILE_KEYS = {
    "manifest": "manifest.json", "business_review_json": "business_review.json",
    "analysis_catalog_json": "analysis_catalog.json", "review_json": "review.json",
}
DTO_VERSIONS = {
    "manifest": "site-dashboard-run-manifest-dto/v0.1",
    "business_review": "site-dashboard-business-review-dto/v0.1",
    "analysis_catalog": "site-dashboard-analysis-catalog-dto/v0.1",
    "review": "site-dashboard-review-dto/v0.1",
    "summary_csv": "site-dashboard-performance-summary-dto/v0.1",
}
MONTH_PATTERN = re.compile(r"^20\d{2}-(0[1-9]|1[0-2])$")
RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{8,64}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SUMMARY_COLUMNS = (
    "点位ID", "门店名称", "Hanson门店名称", "城市", "门店属性", "门店状态", "统计月份起",
    "统计月份止", "有数据月份数", "有营收月份数", "近12月营收", "近12月平均月营收", "月租金",
    "租金状态", "租售比_按平均月营收", "近12月新客数", "平均月新客数", "客户指标月份数",
    "客户指标截至月份", "近12月总客数", "平均客单价_折扣后", "平均理疗师日均产值",
    "分析可用性", "营收来源说明", "平均留存率", "平均返店频次", "经营核查数据状态",
    "经营核查数据检查", "经营核查候选", "经营核查候选ID", "经营核查为什么现在提出",
    "经营核查异常持续月数", "经营核查关键证据", "经营核查可能解释", "经营核查证据缺口",
    "经营核查建议核查",
)


class DashboardAnalysisExportError(ValueError):
    pass


def _read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DashboardAnalysisExportError(f"无法读取合法 JSON：{path}") from error
    if not isinstance(value, dict):
        raise DashboardAnalysisExportError(f"JSON 根节点必须为对象：{path}")
    return value


def _exact(value, keys, label):
    if not isinstance(value, dict):
        raise DashboardAnalysisExportError(f"{label}必须为对象")
    missing, extra = set(keys) - set(value), set(value) - set(keys)
    if missing or extra:
        bits = (["缺少:" + ",".join(sorted(missing))] if missing else []) + (["额外:" + ",".join(sorted(extra))] if extra else [])
        raise DashboardAnalysisExportError(f"{label}不符合脱敏白名单；{'；'.join(bits)}")
    return value


def _subset(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise DashboardAnalysisExportError(f"{label}含非白名单字段")
    return value


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def _hash_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _atomic_bytes(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name); handle.write(value); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists(): temporary.unlink()


OPERATING_GATE_KEYS = ("ready", "latest_month", "coverage", "field_completeness", "message", "rule_version")
WORKFORCE_GATE_KEYS = (
    "ready", "target_month", "data_cutoff_dates", "source_row_count", "source_store_count", "source_months",
    "scope_store_count", "covered_scope_store_count", "missing_scope_stores", "scope_coverage",
    "mapping_completeness", "field_completeness", "confidence_levels", "candidate_store_count",
    "missing_candidate_stores", "trend_only_months", "limitations", "issues", "message",
)
METRICS = ("revenue", "service_visits", "total_customers", "new_customers", "returning_customers", "discounted_average_ticket", "therapist_workdays", "therapist_daily_output", "therapist_productivity")
LATEST_KEYS = METRICS + ("month", "rent_ratio", "data_source", "data_completeness")
PERSONNEL_KEYS = (
    "available", "target_month", "evidence_role", "confidence_level", "coverage_status", "event_coverage_status",
    "cutoff_date", "month_start_headcount", "month_end_headcount", "month_average_headcount",
    "average_headcount_previous_3m", "average_headcount_recent_2m", "average_headcount_change", "recent_2m_hires",
    "recent_2m_exits", "recent_2m_transfer_in", "recent_2m_transfer_out", "recent_2m_support_in",
    "recent_2m_support_out", "manager_change_candidate", "workdays_per_average_therapist", "missing_months", "note",
)
PERSONNEL_MISSING_KEYS = ("available", "target_month", "evidence_role", "missing_months", "note")


def _gate(value, label):
    _exact(value, OPERATING_GATE_KEYS, label)
    if type(value["ready"]) is not bool or value["ready"] is not True:
        raise DashboardAnalysisExportError(f"{label}.ready 必须是布尔值 true")
    return deepcopy(value)


def _workforce_gate(value, label):
    _exact(value, WORKFORCE_GATE_KEYS, label)
    if type(value["ready"]) is not bool or value["ready"] is not True:
        raise DashboardAnalysisExportError(f"{label}.ready 必须是布尔值 true")
    return deepcopy(value)


def _threshold(value, label):
    _exact(value, ("actual", "threshold", "comparison", "met", "distance_to_threshold", "crossed_by"), label)
    return deepcopy(value)


def _rule(value):
    _exact(value, ("triggered", "reason", "operating_combination_decline", "rent_pressure_with_revenue_decline"), "candidate_rule_check")
    combo = value["operating_combination_decline"]
    _exact(combo, ("met", "revenue", "total_customers", "returning_customers", "new_customers", "therapist_workdays"), "candidate_rule_check.combination")
    for key in ("revenue", "total_customers", "returning_customers", "new_customers", "therapist_workdays"):
        _threshold(combo[key], f"candidate_rule_check.{key}")
    rent = value["rent_pressure_with_revenue_decline"]
    _exact(rent, ("met", "rent_ratio", "revenue"), "candidate_rule_check.rent")
    _threshold(rent["rent_ratio"], "candidate_rule_check.rent_ratio"); _threshold(rent["revenue"], "candidate_rule_check.rent_revenue")
    return deepcopy(value)


def _differences(value, label):
    _exact(value, METRICS, label)
    for key in METRICS: _exact(value[key], ("label", "baseline_previous_3m", "recent_2m", "change"), f"{label}.{key}")
    return deepcopy(value)


def _normalize_source_data(source_data):
    if source_data is None:
        raise DashboardAnalysisExportError("阿里云集成导出必须包含 source_data")
    _exact(
        source_data,
        ("sync_status", "stale", "package_id", "data_period", "generated_at", "manifest_sha256"),
        "source_data",
    )
    sync_status = source_data["sync_status"]
    if sync_status not in {"fresh", "fallback_last_success"}:
        raise DashboardAnalysisExportError("Data 来源状态非法")
    stale = source_data["stale"]
    if not isinstance(stale, bool) or stale != (sync_status == "fallback_last_success"):
        raise DashboardAnalysisExportError("Data 新鲜度与同步状态不一致")
    if not isinstance(source_data["data_period"], str) or not MONTH_PATTERN.fullmatch(source_data["data_period"]):
        raise DashboardAnalysisExportError("Data 数据期间格式非法")
    try:
        generated_at = datetime.fromisoformat(source_data["generated_at"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise DashboardAnalysisExportError("Data 生成时间格式非法") from error
    if generated_at.tzinfo is None:
        raise DashboardAnalysisExportError("Data 生成时间必须包含时区")
    package_id = source_data["package_id"]
    if not isinstance(package_id, str) or not package_id or "/" in package_id or "\\" in package_id:
        raise DashboardAnalysisExportError("Data package_id 非法")
    manifest_sha256 = source_data["manifest_sha256"]
    if not isinstance(manifest_sha256, str) or not SHA256_PATTERN.fullmatch(manifest_sha256):
        raise DashboardAnalysisExportError("Data manifest SHA-256 非法")
    return deepcopy(source_data)


def _three_month(value, month, label):
    try: validate_three_month_operating_contract(value, month)
    except ValueError as error: raise DashboardAnalysisExportError(f"{label}：{error}") from error
    _exact(value, ("schema_version", "months"), label)
    row_keys = ("schema_version", "month", "operating_revenue", "base_rent", "property_fee", "known_occupancy_cost_total", "management_fee", "other_known_fixed_costs", "rent_to_sales_ratio", "data_cutoff", "data_source", "data_quality")
    for row in value["months"]:
        _exact(row, row_keys, f"{label}.month")
        for key in ("operating_revenue", "base_rent", "property_fee", "management_fee"):
            _exact(row[key], ("amount_yuan", "status", "source_field", "reason"), f"{label}.{key}")
        _exact(row["known_occupancy_cost_total"], ("amount_yuan", "status", "included_components", "excluded_components", "allocation_status", "source_field", "upstream_source_field"), f"{label}.known_cost")
        _exact(row["rent_to_sales_ratio"], ("value", "status", "source_field", "calculation", "value_tolerance", "numerator", "numerator_scope", "source_value", "source_value_field", "source_comparison_tolerance", "source_value_status", "source_value_mismatch", "absolute_difference", "quality_note"), f"{label}.ratio")
        _exact(row["data_cutoff"], ("complete_month", "cutoff_date"), f"{label}.cutoff")
        _exact(row["data_source"], ("operating_revenue", "occupancy_cost", "occupancy_cost_note"), f"{label}.source")
        _exact(row["data_quality"], ("monthly_gate", "operating_revenue_completeness", "operating_quality_note", "occupancy_cost_status", "completeness_status", "confidence_status"), f"{label}.quality")
        if not isinstance(row["other_known_fixed_costs"], list): raise DashboardAnalysisExportError(f"{label}.other_costs必须为数组")
        for item in row["other_known_fixed_costs"]: _exact(item, ("cost_key", "amount_yuan", "status", "source_field", "source"), f"{label}.other_cost")
    return deepcopy(value)


def _business(value, month):
    top = ("schema_version", "status", "target_month", "dashboard_write_allowed", "run_mode", "data_cutoff", "data_gate", "coverage", "ranking", "three_month_operating_contract", "candidate_count", "fixed_nine_comparison", "evidence_legend", "stores", "excluded_stores")
    _exact(value, top, "business_review")
    if value["schema_version"] != BUSINESS_REVIEW_SCHEMA_VERSION: raise DashboardAnalysisExportError("business_review schema 不支持")
    _ready(value, "business_review", month)
    _exact(value["data_cutoff"], ("operating_complete_month", "workforce_dates"), "business_review.data_cutoff")
    gate = value["data_gate"]
    _exact(gate, ("operating", "workforce", "workforce_confidence_in_participating_stores", "review_issues"), "business_review.data_gate")
    _gate(gate["operating"], "business_review.operating_gate"); _workforce_gate(gate["workforce"], "business_review.workforce_gate")
    _exact(value["coverage"], ("scope_store_count", "workforce_covered_scope_store_count", "participating_store_count", "excluded_store_count"), "business_review.coverage")
    _exact(value["ranking"], ("basis", "note"), "business_review.ranking")
    root_contract = value["three_month_operating_contract"]
    _exact(root_contract, ("schema_version", "month_count", "window_end_month", "definition", "ratio_policy", "cost_scope"), "business_review.contract")
    _exact(root_contract["ratio_policy"], ("authoritative_calculation", "value_tolerance", "source_comparison_tolerance", "source_ratio_role"), "business_review.ratio_policy")
    _exact(root_contract["cost_scope"], ("known_occupancy_cost_total_source", "base_rent_and_property_fee_split_available", "management_fee_available", "financial_profit_calculated", "excluded_components"), "business_review.cost_scope")
    _exact(value["fixed_nine_comparison"], ("historical_reference_month", "historical_reference_count", "historical_reference_rule_version", "current_month", "current_rule_version", "same_month_as_reference", "same_rule_version_as_reference", "current_candidate_freeze_applied", "input_version_check", "current_mode", "note"), "business_review.fixed_nine")
    _exact(value["evidence_legend"], ("facts", "statistical_differences", "proxy_metrics", "possible_explanations", "evidence_gaps"), "business_review.legend")
    store_keys = ("store_id", "store_name", "operating_status", "candidate_triggered", "candidate_id", "trigger_codes", "candidate_rule_check", "latest_month_facts", "recent_three_month_operating", "statistical_differences", "personnel_history", "possible_explanations", "evidence_gaps", "peer_evidence", "revenue_change_rank")
    projected = deepcopy(value)
    for index, store in enumerate(value["stores"]):
        _exact(store, store_keys, "business_review.store"); _rule(store["candidate_rule_check"])
        _exact(store["latest_month_facts"], LATEST_KEYS, "business_review.latest_facts")
        _differences(store["statistical_differences"], "business_review.differences")
        _exact(store["personnel_history"], PERSONNEL_KEYS if store["personnel_history"].get("available") is True else PERSONNEL_MISSING_KEYS, "business_review.personnel")
        _exact(store["peer_evidence"], ("used_for_candidate", "note"), "business_review.peer_evidence")
        _three_month(store["recent_three_month_operating"], month, "business_review.three_month")
        projected["stores"][index].pop("peer_evidence")
    for item in value["excluded_stores"]: _exact(item, ("store_id", "store_name", "reason"), "business_review.excluded_store")
    return projected


def _review(value, month):
    _exact(value, ("schema_version", "status", "target_month", "dashboard_write_allowed", "candidate_count", "candidate_order", "data_gate", "summary", "candidates", "next_owner"), "review")
    if value["schema_version"] != REVIEW_SCHEMA_VERSION: raise DashboardAnalysisExportError("review schema 不支持")
    _ready(value, "review", month)
    _exact(value["data_gate"], ("operating", "workforce", "issues"), "review.data_gate")
    _gate(value["data_gate"]["operating"], "review.operating_gate"); _workforce_gate(value["data_gate"]["workforce"], "review.workforce_gate")
    _exact(value["summary"], ("personnel_cross_evidence", "business_decline_without_personnel_support", "note"), "review.summary")
    result = {"schema_version": value["schema_version"], "status": value["status"], "target_month": value["target_month"], "dashboard_write_allowed": False, "candidate_count": value["candidate_count"], "candidates": []}
    candidate_keys = ("store_id", "store_name", "candidate_id", "evidence_class", "direct_facts", "personnel_indicators", "operating_facts", "proxy_metrics", "hypothesis", "evidence_limit", "remaining_field_facts", "questions_for_franchise_service", "candidate_order")
    direct_keys = ("target_month", "month_start_headcount", "month_end_headcount", "month_average_headcount", "previous_month_end_headcount", "end_headcount_delta", "recent_2m_average_headcount", "previous_3m_average_headcount", "average_headcount_change", "recent_2m_hires", "recent_2m_exits", "recent_2m_transfer_in", "recent_2m_transfer_out", "target_month_exit_and_transfer_out", "concentrated_exit_or_transfer_out", "recent_2m_support_in", "recent_2m_support_out", "recent_2m_support_in_person_days", "recent_2m_support_out_person_days", "short_term_support_observed", "target_month_net_change", "manager_change_candidate", "manager_change_candidate_count", "manager_change_first_date", "snapshot_coverage_days", "expected_snapshot_days", "confidence_level", "coverage_status", "event_coverage_status", "store_coverage_status", "cutoff_date")
    for item in value["candidates"]:
        _exact(item, candidate_keys, "review.candidate"); direct = _exact(item["direct_facts"], direct_keys, "review.direct_facts")
        _exact(item["personnel_indicators"], ("target_month_direct_signal", "five_month_personnel_signal", "target_month_event_coverage_complete", "pre_2026_07_history_role", "note"), "review.personnel_indicators")
        operating = _exact(item["operating_facts"], ("evidence", "revenue_change", "total_customer_change", "new_customer_change", "returning_customer_change", "therapist_workday_change", "therapist_productivity_change"), "review.operating_facts")
        _exact(item["proxy_metrics"], ("workdays_per_average_therapist", "headcount_and_operating_metric_direction", "note"), "review.proxy_metrics")
        result["candidates"].append({"candidate_id": item["candidate_id"], "candidate_order": item["candidate_order"], "store_id": item["store_id"], "store_name": item["store_name"], "evidence_class": item["evidence_class"], "direct_facts": {"target_month": direct["target_month"], "confidence_level": direct["confidence_level"], "cutoff_date": direct["cutoff_date"]}, "operating_facts": {"evidence": operating["evidence"]}, "hypothesis": item["hypothesis"], "evidence_limit": item["evidence_limit"], "remaining_field_facts": deepcopy(item["remaining_field_facts"]), "questions_for_franchise_service": deepcopy(item["questions_for_franchise_service"])})
    return result


def _catalog(value, run_id, month):
    try: validate_analysis_catalog(value)
    except ValueError as error: raise DashboardAnalysisExportError(f"analysis_catalog：{error}") from error
    if value.get("source_run_id") != run_id: raise DashboardAnalysisExportError("analysis_catalog run_id 不一致")
    for record in value["records"]:
        if record["analysis_period"] != {"grain": "month", "start": month, "end": month}: raise DashboardAnalysisExportError("analysis_catalog 月份不一致")
        _exact(record["confidence"], ("level", "operating_gate", "workforce_gate", "workforce_data_trust", "note"), "analysis.confidence")
        evidence = _exact(record["evidence"], ("direct_facts", "statistical_differences", "proxy_metrics", "hypotheses"), "analysis.evidence")
        direct = _exact(evidence["direct_facts"], ("latest_month", "recent_three_month_operating", "personnel_aggregate"), "analysis.direct_facts")
        latest_keys = set(LATEST_KEYS) - {"rent_ratio"}; latest_keys.update(("rent_to_sales_ratio", "source_rent_ratio_diagnostic"))
        _exact(direct["latest_month"], latest_keys, "analysis.latest_month")
        _subset(direct["personnel_aggregate"], ("available", "target_month", "confidence_level", "coverage_status", "event_coverage_status", "cutoff_date", "month_start_headcount", "month_end_headcount", "month_average_headcount"), "analysis.personnel")
        diffs = _exact(evidence["statistical_differences"], ("operating", "personnel"), "analysis.differences")
        _differences(diffs["operating"], "analysis.operating_differences")
        _subset(diffs["personnel"], ("average_headcount_previous_3m", "average_headcount_recent_2m", "average_headcount_change", "recent_2m_hires", "recent_2m_exits", "recent_2m_transfer_in", "recent_2m_transfer_out", "recent_2m_support_in", "recent_2m_support_out"), "analysis.personnel_differences")
        proxies = _exact(evidence["proxy_metrics"], ("personnel", "peer_evidence"), "analysis.proxies")
        if set(proxies["personnel"]) not in ({"availability"}, {"workdays_per_average_therapist", "manager_change_candidate", "evidence_role", "note"}): raise DashboardAnalysisExportError("analysis personnel proxy 不符合白名单")
        _exact(proxies["peer_evidence"], ("used_for_candidate", "note"), "analysis.peer_evidence")
        conclusion = _exact(record["conclusion"], ("candidate_triggered", "candidate_id", "trigger_codes", "operating_status", "revenue_change_rank", "rule_check", "interpretation"), "analysis.conclusion")
        _rule(conclusion["rule_check"])
    return deepcopy(value)


def _manifest(value, month, run_id):
    keys = ("schema_version", "run_id", "run_month", "status", "generated_at", "rule_version", "candidate_rule_version", "review_schema_version", "business_review_schema_version", "three_month_operating_schema_version", "analysis_catalog_schema_version", "analysis_record_schema_version", "workforce_contract_version", "inputs", "candidate_order", "candidate_count", "dashboard_write_allowed", "outputs")
    _exact(value, keys, "manifest")
    expected = {"schema_version": RUN_SCHEMA_VERSION, "run_id": run_id, "run_month": month, "status": "ready_for_business_review", "review_schema_version": REVIEW_SCHEMA_VERSION, "business_review_schema_version": BUSINESS_REVIEW_SCHEMA_VERSION, "three_month_operating_schema_version": THREE_MONTH_OPERATING_SCHEMA_VERSION, "analysis_catalog_schema_version": ANALYSIS_CATALOG_SCHEMA_VERSION, "analysis_record_schema_version": ANALYSIS_RECORD_SCHEMA_VERSION, "dashboard_write_allowed": False}
    for key, wanted in expected.items():
        if value[key] != wanted: raise DashboardAnalysisExportError(f"manifest {key} 不一致")
    inputs = _exact(value["inputs"], ("operating", "workforce", "candidate_freeze"), "manifest.inputs")
    _exact(inputs["operating"], ("path", "sha256", "row_count"), "manifest.operating")
    _exact(inputs["workforce"], ("path", "sha256", "row_count", "column_count", "data_version", "source_commit", "contract_path", "contract_sha256", "column_mapping"), "manifest.workforce")
    if inputs["candidate_freeze"] is not None: _exact(inputs["candidate_freeze"], ("path", "sha256", "target_month", "candidate_count"), "manifest.candidate_freeze")
    outputs = _exact(value["outputs"], ("gate", "review_json", "review_markdown", "business_review_json", "business_review_markdown", "analysis_catalog_json", "candidate_csv"), "manifest.outputs")
    for key, name in RUN_FILE_KEYS.items():
        if key != "manifest" and outputs[key] != name: raise DashboardAnalysisExportError(f"manifest 输出 {key} 非法")
    return {key: deepcopy(value[key]) for key in ("schema_version", "run_id", "run_month", "status", "generated_at", "rule_version", "candidate_rule_version", "review_schema_version", "business_review_schema_version", "three_month_operating_schema_version", "analysis_catalog_schema_version", "analysis_record_schema_version", "candidate_count", "dashboard_write_allowed")} | {"outputs": {"review_json": "review.json", "business_review_json": "business_review.json", "analysis_catalog_json": "analysis_catalog.json"}}


def _ready(value, label, month):
    if value.get("status") != "ready_for_business_review" or value.get("dashboard_write_allowed") is not False or value.get("target_month") != month:
        raise DashboardAnalysisExportError(f"{label}状态、月份或只读边界不一致")


def validate_source_bundle(source_root):
    source_root = Path(source_root); pointer = _read_json(source_root / "latest_success.json")
    _exact(pointer, ("run_id", "run_month", "status", "path"), "latest_success")
    month, run_id = pointer.get("run_month"), pointer.get("run_id")
    if not isinstance(month, str) or not MONTH_PATTERN.fullmatch(month): raise DashboardAnalysisExportError("latest_success 缺少合法月份")
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id): raise DashboardAnalysisExportError("latest_success 缺少合法 run_id")
    if pointer["status"] != "ready_for_business_review": raise DashboardAnalysisExportError("latest_success 状态未就绪")
    root = (source_root.resolve() / month / run_id).resolve()
    if source_root.resolve() not in root.parents: raise DashboardAnalysisExportError("run 路径越界")
    declared_path = Path(pointer["path"])
    if not declared_path.is_absolute():
        declared_path = source_root.resolve() / declared_path
    if declared_path.resolve() != root:
        raise DashboardAnalysisExportError("latest_success path 与运行目录不一致或越界")
    for name in RUN_FILE_KEYS.values():
        path = root / name
        if path.is_symlink() or not path.is_file() or root not in path.resolve().parents: raise DashboardAnalysisExportError(f"run 文件非法：{name}")
    projected = {
        "manifest.json": _manifest(_read_json(root / "manifest.json"), month, run_id),
        "business_review.json": _business(_read_json(root / "business_review.json"), month),
        "analysis_catalog.json": _catalog(_read_json(root / "analysis_catalog.json"), run_id, month),
        "review.json": _review(_read_json(root / "review.json"), month),
    }
    if not projected["business_review.json"]["data_gate"]["operating"]["ready"] or not projected["business_review.json"]["data_gate"]["workforce"]["ready"]: raise DashboardAnalysisExportError("数据 Gate 未通过")
    return {"run_month": month, "run_id": run_id, "projected": projected}


def _summary_bytes(path):
    try: rows = list(csv.reader(io.StringIO(Path(path).read_text(encoding="utf-8-sig"))))
    except (OSError, UnicodeError, csv.Error) as error: raise DashboardAnalysisExportError("汇总 CSV 无法读取") from error
    if not rows: raise DashboardAnalysisExportError("汇总 CSV 缺少表头")
    header = rows[0]
    if len(header) != len(set(header)): raise DashboardAnalysisExportError("汇总 CSV 存在重复列")
    if tuple(header) != SUMMARY_COLUMNS: raise DashboardAnalysisExportError("汇总 CSV 存在缺失、额外或顺序错误的列")
    if any(len(row) != len(header) for row in rows[1:]): raise DashboardAnalysisExportError("汇总 CSV 数据行列数不一致")
    buffer = io.StringIO(newline=""); csv.writer(buffer, lineterminator="\n").writerows(rows)
    return ("\ufeff" + buffer.getvalue()).encode()


def _manifest_payload(bundle, contents, summary, pointer, published_at, source_data):
    payload = {
        "schema_version": EXPORT_SCHEMA_VERSION, "published_at": published_at,
        "source_run": {"run_month": bundle["run_month"], "run_id": bundle["run_id"], "run_schema_version": RUN_SCHEMA_VERSION},
        "projection_versions": deepcopy(DTO_VERSIONS),
        "layout": {"review_root": "franchise_operating_reviews", "latest_success": "franchise_operating_reviews/latest_success.json", "run_path": f"franchise_operating_reviews/{bundle['run_month']}/{bundle['run_id']}", "export_manifest": EXPORT_MANIFEST_FILE_NAME, "required_run_files": sorted((*contents, *((SUMMARY_FILE_NAME,) if summary else ())))},
        "files": [{"path": name, "sha256": _hash_bytes(data), "bytes": len(data)} for name, data in sorted(contents.items())],
        "summary": ({"status": "published", "path": SUMMARY_FILE_NAME, "sha256": _hash_bytes(summary), "bytes": len(summary)} if summary else {"status": "not_published", "reason": "source_missing"}),
        "latest_success_sha256": _hash_bytes(pointer), "dashboard_write_allowed": False,
    }
    payload["source_data"] = deepcopy(source_data)
    return payload


def _assert_existing(root, expected):
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()} != set(expected): raise DashboardAnalysisExportError("相同 run 文件集合变化，拒绝覆盖")
    for name, data in expected.items():
        path = root / name
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data: raise DashboardAnalysisExportError(f"相同 run 内容变化：{name}")


def publish_dashboard_analysis_export(
    source_root=DEFAULT_SOURCE_ROOT,
    export_root=DEFAULT_EXPORT_ROOT,
    summary_path=DEFAULT_SUMMARY_PATH,
    source_data=None,
    now=None,
):
    source_root, export_root = Path(source_root).resolve(), Path(export_root).resolve()
    if source_root == export_root or source_root in export_root.parents or export_root in source_root.parents: raise DashboardAnalysisExportError("源与导出目录不得互相包含")
    bundle = validate_source_bundle(source_root)
    normalized_source_data = _normalize_source_data(source_data)
    contents = {name: _json_bytes(value) for name, value in bundle["projected"].items()}
    summary = None
    if summary_path:
        path = Path(summary_path).resolve()
        if path.name != SUMMARY_FILE_NAME or path.parent != source_root.parent: raise DashboardAnalysisExportError("汇总必须是 staging 固定文件")
        if path.exists():
            if path.is_symlink() or not path.is_file(): raise DashboardAnalysisExportError("汇总不是普通文件")
            summary = _summary_bytes(path)
    pointer_payload = {"schema_version": POINTER_SCHEMA_VERSION, "run_month": bundle["run_month"], "run_id": bundle["run_id"], "status": "ready_for_business_review", "export_manifest": EXPORT_MANIFEST_FILE_NAME, "dashboard_write_allowed": False}
    pointer_payload["source_data"] = deepcopy(normalized_source_data)
    pointer = _json_bytes(pointer_payload)
    review_root = export_root / "franchise_operating_reviews"; run_root = review_root / bundle["run_month"] / bundle["run_id"]
    created_run = False
    if run_root.exists():
        old_manifest = _read_json(run_root / EXPORT_MANIFEST_FILE_NAME)
        manifest = _manifest_payload(bundle, contents, summary, pointer, old_manifest.get("published_at"), normalized_source_data)
        expected = {**contents, EXPORT_MANIFEST_FILE_NAME: _json_bytes(manifest), **({SUMMARY_FILE_NAME: summary} if summary else {})}
        _assert_existing(run_root, expected)
    else:
        manifest = _manifest_payload(bundle, contents, summary, pointer, (now or datetime.now(timezone.utc)).isoformat(), normalized_source_data)
        expected = {**contents, EXPORT_MANIFEST_FILE_NAME: _json_bytes(manifest), **({SUMMARY_FILE_NAME: summary} if summary else {})}
        run_root.parent.mkdir(parents=True, exist_ok=True); stage = Path(tempfile.mkdtemp(prefix=f".{bundle['run_id']}.", dir=run_root.parent))
        try:
            for name, data in expected.items(): _atomic_bytes(stage / name, data)
            os.replace(stage, run_root)
            created_run = True
        finally:
            if stage.exists(): shutil.rmtree(stage)
    try:
        _atomic_bytes(review_root / "latest_success.json", pointer)
    except Exception:
        if created_run and run_root.is_dir() and not run_root.is_symlink():
            shutil.rmtree(run_root)
        raise
    return manifest

"""Build an idempotent monthly franchise operating review from read-only aggregate sources."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from services.franchise_operating_check import (
    RULE_VERSION as CANDIDATE_RULE_VERSION,
    build_operating_check_candidates,
    is_scope_row,
)
from services.franchise_operating_review import REVIEW_SCHEMA_VERSION, build_review, render_markdown
from services.workforce_monthly import (
    CONTRACT_VERSION as WORKFORCE_CONTRACT_VERSION,
    WorkforceContractError,
    build_workforce_gate,
    load_workforce_monthly,
    read_workforce_contract,
)


OPERATING_MONTHLY = Path("data/staging/site_performance_monthly_bi_feishu_rent.csv")
WORKFORCE_MONTHLY = Path("/opt/management-dashboard/data/canonical-snapshot/store_workforce_monthly.csv")
WORKFORCE_CONTRACT = Path("config/store_workforce_monthly.v1.contract.json")
OUTPUT_ROOT = Path("data/staging/franchise_operating_reviews")
RULE_VERSION = "franchise-operating-monthly/v0.1"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_candidate_freeze(path: str | Path | None, target_month: str | None) -> tuple[list[dict] | None, dict | None]:
    if not path:
        return None, None
    freeze_path = Path(path)
    payload = json.loads(freeze_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "franchise-operating-candidate-freeze/v0.1":
        raise ValueError("固定候选文件 schema_version 不支持")
    if target_month and payload.get("target_month") != target_month:
        raise ValueError("固定候选月份与 --month 不一致")
    rows = payload.get("candidate_order")
    if not isinstance(rows, list) or not rows:
        raise ValueError("固定候选文件缺少 candidate_order")
    store_ids = [row.get("store_id") for row in rows]
    if any(not store_id for store_id in store_ids) or len(store_ids) != len(set(store_ids)):
        raise ValueError("固定候选包含空门店编号或重复门店")
    return rows, {
        "path": str(freeze_path),
        "sha256": sha256_file(freeze_path),
        "target_month": payload.get("target_month"),
        "candidate_count": len(rows),
    }


def derived_candidate_order(operating_result, monthly_rows, target_month):
    names = {
        row.get("点位ID"): row.get("门店名称", "")
        for row in monthly_rows
        if row.get("月份") == target_month and row.get("点位ID")
    }
    result = []
    for store_id in sorted(operating_result.get("stores", {})):
        candidate = operating_result["stores"][store_id].get("candidate")
        if candidate:
            result.append({"store_id": store_id, "store_name": names.get(store_id, ""), "candidate_id": candidate["candidate_id"]})
    return result


def stable_run_id(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def write_json(path: Path, payload: dict):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_candidate_csv(path: Path, candidates: list[dict]):
    headers = [
        "candidate_order", "store_id", "store_name", "candidate_id", "evidence_class", "confidence_level",
        "month_start_headcount", "month_end_headcount", "month_average_headcount", "end_headcount_delta",
        "recent_2m_exits", "recent_2m_transfer_out", "recent_2m_support_in", "recent_2m_support_out",
        "manager_change_candidate", "hypothesis", "evidence_limit",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for candidate in candidates:
            facts = candidate["direct_facts"]
            writer.writerow(
                {
                    "candidate_order": candidate["candidate_order"],
                    "store_id": candidate["store_id"],
                    "store_name": candidate["store_name"],
                    "candidate_id": candidate["candidate_id"],
                    "evidence_class": candidate["evidence_class"],
                    "confidence_level": facts["confidence_level"],
                    "month_start_headcount": facts["month_start_headcount"],
                    "month_end_headcount": facts["month_end_headcount"],
                    "month_average_headcount": facts["month_average_headcount"],
                    "end_headcount_delta": facts["end_headcount_delta"],
                    "recent_2m_exits": facts["recent_2m_exits"],
                    "recent_2m_transfer_out": facts["recent_2m_transfer_out"],
                    "recent_2m_support_in": facts["recent_2m_support_in"],
                    "recent_2m_support_out": facts["recent_2m_support_out"],
                    "manager_change_candidate": facts["manager_change_candidate"],
                    "hypothesis": candidate["hypothesis"],
                    "evidence_limit": candidate["evidence_limit"],
                }
            )


def build(
    operating_path=OPERATING_MONTHLY,
    workforce_path=WORKFORCE_MONTHLY,
    output_root=OUTPUT_ROOT,
    target_month=None,
    candidate_freeze=None,
    workforce_contract=WORKFORCE_CONTRACT,
    today=None,
    now=None,
):
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    operating_path = Path(operating_path)
    workforce_path = Path(workforce_path)
    output_root = Path(output_root)
    if not operating_path.is_file():
        raise FileNotFoundError(f"经营月表不存在：{operating_path}")
    monthly_rows = read_csv(operating_path)
    operating_result = build_operating_check_candidates(monthly_rows, today=today, target_month=target_month)
    target_month = operating_result["global"].get("latest_month") or target_month or "unknown"
    frozen_order, freeze_manifest = load_candidate_freeze(candidate_freeze, target_month if target_month != "unknown" else None)
    candidate_order = frozen_order or derived_candidate_order(operating_result, monthly_rows, target_month)

    try:
        workforce_dataset = load_workforce_monthly(workforce_path, read_workforce_contract(workforce_contract))
    except WorkforceContractError as error:
        workforce_dataset = {
            "contract_version": WORKFORCE_CONTRACT_VERSION,
            "contract_schema_version": None,
            "contract_path": str(workforce_contract) if workforce_contract else None,
            "contract_sha256": "unavailable",
            "source_commit": None,
            "data_version": None,
            "path": str(workforce_path),
            "sha256": "unavailable",
            "headers": [],
            "column_count": 0,
            "row_count": 0,
            "column_mapping": {},
            "rows": [],
            "issues": [str(error)],
        }

    scope_store_ids = {
        row.get("点位ID") for row in monthly_rows
        if row.get("月份") == target_month and row.get("月度Gate纳入") == "是" and is_scope_row(row) and row.get("点位ID")
    }
    candidate_store_ids = [row["store_id"] for row in candidate_order]
    workforce_gate = build_workforce_gate(workforce_dataset, target_month, scope_store_ids, candidate_store_ids)
    review = build_review(monthly_rows, operating_result, workforce_dataset, workforce_gate, candidate_order)

    identity = {
        "target_month": target_month,
        "rule_version": RULE_VERSION,
        "candidate_rule_version": CANDIDATE_RULE_VERSION,
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "workforce_contract_version": workforce_dataset.get("contract_version"),
        "operating_sha256": sha256_file(operating_path),
        "workforce_sha256": workforce_dataset.get("sha256"),
        "workforce_contract_sha256": workforce_dataset.get("contract_sha256"),
        "workforce_data_version": workforce_dataset.get("data_version"),
        "workforce_source_commit": workforce_dataset.get("source_commit"),
        "workforce_column_mapping": workforce_dataset.get("column_mapping"),
        "candidate_freeze_sha256": (freeze_manifest or {}).get("sha256"),
        "candidate_order": candidate_store_ids,
    }
    run_id = stable_run_id(identity)
    run_dir = output_root / target_month / run_id
    manifest_path = run_dir / "manifest.json"
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"unchanged run_id={run_id} status={existing.get('status')} path={run_dir}")
        return existing, run_dir, True

    if run_dir.exists() and any(run_dir.iterdir()):
        raise RuntimeError(f"发现未完成的同一运行目录，请人工核对后重试：{run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "franchise-operating-run/v0.1",
        "run_id": run_id,
        "run_month": target_month,
        "status": review["status"],
        "generated_at": now.isoformat(),
        "rule_version": RULE_VERSION,
        "candidate_rule_version": CANDIDATE_RULE_VERSION,
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "workforce_contract_version": workforce_dataset.get("contract_version"),
        "inputs": {
            "operating": {"path": str(operating_path), "sha256": identity["operating_sha256"], "row_count": len(monthly_rows)},
            "workforce": {
                "path": str(workforce_path), "sha256": workforce_dataset.get("sha256"),
                "row_count": workforce_dataset.get("row_count"), "column_count": workforce_dataset.get("column_count"),
                "data_version": workforce_dataset.get("data_version"),
                "source_commit": workforce_dataset.get("source_commit"),
                "contract_path": workforce_dataset.get("contract_path"),
                "contract_sha256": workforce_dataset.get("contract_sha256"),
                "column_mapping": workforce_dataset.get("column_mapping"),
            },
            "candidate_freeze": freeze_manifest,
        },
        "candidate_order": candidate_store_ids,
        "candidate_count": review["candidate_count"],
        "dashboard_write_allowed": False,
        "outputs": {
            "gate": "data_gate.json", "review_json": "review.json", "review_markdown": "review.md",
            "candidate_csv": "candidates.csv" if review["candidates"] else None,
        },
    }
    write_json(run_dir / "data_gate.json", review["data_gate"])
    write_json(run_dir / "review.json", review)
    (run_dir / "review.md").write_text(render_markdown(review, manifest), encoding="utf-8")
    if review["candidates"]:
        write_candidate_csv(run_dir / "candidates.csv", review["candidates"])
    write_json(manifest_path, manifest)
    pointer = {"run_id": run_id, "run_month": target_month, "status": review["status"], "path": str(run_dir)}
    write_json(output_root / "last_attempt.json", pointer)
    if review["status"] == "ready_for_business_review":
        write_json(output_root / "latest_success.json", pointer)
    print(f"wrote run_id={run_id} status={review['status']} candidates={review['candidate_count']} path={run_dir}")
    return manifest, run_dir, False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operating-monthly", default=str(OPERATING_MONTHLY))
    parser.add_argument("--workforce-monthly", default=str(WORKFORCE_MONTHLY))
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    parser.add_argument("--month", help="历史回放月份 YYYY-MM；省略时只运行最新完整自然月")
    parser.add_argument("--candidate-freeze", help="固定候选与顺序文件，仅用于已确认的历史回放")
    parser.add_argument(
        "--workforce-contract", default=str(WORKFORCE_CONTRACT),
        help="JSON：精确25列表头、data_version、source commit及语义映射",
    )
    args = parser.parse_args()
    manifest, _, _ = build(
        args.operating_monthly,
        args.workforce_monthly,
        args.output_root,
        args.month,
        args.candidate_freeze,
        args.workforce_contract,
    )
    if manifest["status"] != "ready_for_business_review":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

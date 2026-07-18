import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

from config import settings


DEFAULT_BASE = "data/staging/base_table.csv"
DEFAULT_MAPPING = "config/store_site_mapping.json"
DEFAULT_RENT = "data/staging/rent_extract_feishu.csv"
DEFAULT_OPS = "data/staging/site_ops_monthly_combined.csv"
DEFAULT_OUT = "data/staging/data_contract_issues.csv"
DEFAULT_EPISODES = "config/site_identity_episodes.json"

STATUS_RANK = {"运营中": 0, "在建": 1, "待建": 2, "已终止": 9}
NAME_NOISE = re.compile(r"[\s·•\-_（）()]+")
NAME_WORDS = (
    "上海市",
    "北京市",
    "深圳市",
    "成都市",
    "杭州市",
    "武汉市",
    "上海",
    "北京",
    "深圳",
    "成都",
    "杭州",
    "武汉",
    "lann",
    "LANN",
)


@dataclass
class Issue:
    severity: str
    code: str
    entity: str
    current_value: str
    expected_or_reference: str
    detail: str


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def read_records(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return read_csv(path)


def normalize_mapping_rows(rows: list[dict]) -> list[dict]:
    output = []
    for row in rows:
        if "hanson_store_name" not in row:
            output.append(row)
            continue
        output.append(
            {
                "Hanson门店名称": row.get("hanson_store_name", ""),
                "确认点位ID": "排除" if row.get("status") == "exclude" else row.get("site_id", ""),
                "确认备注": row.get("notes", ""),
            }
        )
    return output


def normalize_name(value: str) -> str:
    text = NAME_NOISE.sub("", (value or "").strip())
    for word in NAME_WORDS:
        text = text.replace(word, "")
    if text.endswith("店"):
        text = text[:-1]
    return text.lower()


def similarity(left: str, right: str) -> float:
    left_norm = normalize_name(left)
    right_norm = normalize_name(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        return min(len(left_norm), len(right_norm)) / max(len(left_norm), len(right_norm))
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def choose_current(rows: list[dict]) -> dict:
    return sorted(rows, key=lambda row: STATUS_RANK.get(row.get("门店状态", ""), 5))[0] if rows else {}


def nonempty_base_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if any((value or "").strip() for value in row.values())]


def episode_indexes(episodes: list[dict]) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    by_record = {row.get("source_record_id", ""): row for row in episodes if row.get("source_record_id")}
    by_store = defaultdict(list)
    for row in episodes:
        if row.get("hanson_store_name") and row.get("resolution_status") != "exclude":
            by_store[row["hanson_store_name"]].append(row)
    return by_record, by_store


def validate_base(rows: list[dict], episodes: list[dict] | None = None) -> list[Issue]:
    issues = []
    episode_by_record, _ = episode_indexes(episodes or [])
    grouped = defaultdict(list)
    for row in nonempty_base_rows(rows):
        site_id = (row.get("点位ID") or "").strip()
        if not site_id:
            record_id = row.get("record_id", "")
            episode = episode_by_record.get(record_id, {})
            if not row.get("门店名称") and not row.get("地址") and not row.get("签约编号"):
                issues.append(
                    Issue("WARN", "BASE_EMPTY_SOURCE_RECORD", record_id, "无业务字段", "归档或过滤", "空源记录不进入分析。")
                )
                continue
            if episode.get("resolution_status") == "confirmed":
                continue
            if episode.get("resolution_status") == "exclude":
                issues.append(
                    Issue(
                        "WARN",
                        "BASE_SOURCE_RECORD_EXCLUDED",
                        record_id,
                        row.get("门店名称", ""),
                        episode.get("notes", "已确认不进入分析"),
                        "该源记录保留追溯，但不生成新的物理点位样本。",
                    )
                )
                continue
            if episode.get("resolution_status") == "pending":
                code = "IDENTITY_EPISODE_PENDING"
                detail = "该记录已进入身份方案，但经营期或点位归属尚未确认。"
            elif row.get("门店状态") in ("待建", "在建"):
                issues.append(
                    Issue(
                        "WARN",
                        "BASE_CANDIDATE_ID_PENDING",
                        record_id or row.get("门店名称", ""),
                        row.get("门店名称", ""),
                        "开业前分配正式点位ID",
                        "未开业候选暂不进入经营样本。",
                    )
                )
                continue
            else:
                code = "BASE_ID_BLANK"
                detail = "有效底表记录缺少点位ID，不能进入下游关联。"
            issues.append(
                Issue(
                    "ERROR",
                    code,
                    record_id or row.get("门店名称", ""),
                    row.get("门店名称", ""),
                    "点位ID",
                    detail,
                )
            )
            continue
        grouped[site_id].append(row)

    for site_id, same_id_rows in grouped.items():
        if len(same_id_rows) <= 1:
            continue
        resolutions = [episode_by_record.get(row.get("record_id", ""), {}) for row in same_id_rows]
        analysis_ids = {row.get("analysis_point_id", "") for row in resolutions}
        if all(row.get("resolution_status") == "confirmed" for row in resolutions) and len(analysis_ids) == len(same_id_rows):
            continue
        labels = [
            f"{row.get('门店名称', '')}[{row.get('门店状态', '')}|{row.get('record_id', '')}]"
            for row in same_id_rows
        ]
        issues.append(
            Issue(
                "ERROR",
                "BASE_JOIN_KEY_NOT_UNIQUE",
                site_id,
                "；".join(labels),
                "一个分析实体对应一个稳定ID",
                "同一ID对应多条合同/位置记录；必须先区分门店、物理点位和合同实体。",
            )
        )
    return issues


def current_base_index(rows: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    grouped = defaultdict(list)
    for row in rows:
        site_id = (row.get("点位ID") or "").strip()
        if site_id:
            grouped[site_id].append(row)
    current = {site_id: choose_current(group) for site_id, group in grouped.items()}
    return current, list(current.values())


def validate_mapping(mapping_rows: list[dict], base_rows: list[dict], episodes: list[dict] | None = None) -> list[Issue]:
    issues = []
    base_by_id, current_rows = current_base_index(base_rows)
    _, episodes_by_store = episode_indexes(episodes or [])

    for row in mapping_rows:
        store = (row.get("Hanson门店名称") or "").strip()
        store_episodes = episodes_by_store.get(store, [])
        if store_episodes:
            if all(episode.get("resolution_status") == "confirmed" for episode in store_episodes):
                continue
            issues.append(
                Issue(
                    "ERROR",
                    "IDENTITY_EPISODE_PENDING",
                    store,
                    "；".join(episode.get("point_name", "") for episode in store_episodes),
                    "确认每个物理点位的实际经营起止日",
                    "该经营门店跨多个物理点位，不能继续使用单一静态映射。",
                )
            )
            continue
        confirmed_id = (row.get("确认点位ID") or "").strip()
        if not confirmed_id or confirmed_id == "排除":
            continue
        target = base_by_id.get(confirmed_id)
        if not target:
            issues.append(
                Issue("ERROR", "MAPPING_TARGET_MISSING", store, confirmed_id, "当前底表中的有效点位ID", "映射目标已不存在。")
            )
            continue

        target_name = target.get("门店名称", "")
        target_score = similarity(store, target_name)
        ranked = sorted(
            (
                (similarity(store, candidate.get("门店名称", "")), candidate)
                for candidate in current_rows
                if candidate.get("点位ID") != confirmed_id
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        best_score, best = ranked[0] if ranked else (0.0, {})

        if best_score >= 0.9 and target_score < 0.7 and best_score - target_score >= 0.25:
            issues.append(
                Issue(
                    "ERROR",
                    "MAPPING_BETTER_MATCH_CHANGED_ID",
                    store,
                    f"{confirmed_id} / {target_name}",
                    f"{best.get('点位ID', '')} / {best.get('门店名称', '')}",
                    "当前确认ID指向另一家门店，存在经营、租金和门店属性串联风险。",
                )
            )

        snapshot_name = (row.get("候选底表门店名称") or "").strip()
        if snapshot_name and normalize_name(snapshot_name) != normalize_name(target_name):
            issues.append(
                Issue(
                    "WARN",
                    "MAPPING_BASE_SNAPSHOT_CHANGED",
                    store,
                    f"{confirmed_id} / {target_name}",
                    snapshot_name,
                    "映射建立时的底表名称与当前名称不同，需要确认是正常更名/换铺还是ID漂移。",
                )
            )
    return issues


def validate_foreign_ids(rows: list[dict], base_rows: list[dict], source: str) -> list[Issue]:
    valid_ids = {(row.get("点位ID") or "").strip() for row in base_rows}
    referenced = {(row.get("点位ID") or "").strip() for row in rows if (row.get("点位ID") or "").strip()}
    return [
        Issue("ERROR", "SOURCE_ID_NOT_IN_BASE", f"{source}:{site_id}", site_id, "当前底表点位ID", "下游数据引用了底表中不存在的ID。")
        for site_id in sorted(referenced - valid_ids)
    ]


def validate_ops(rows: list[dict], today: date) -> list[Issue]:
    issues = []
    keys = Counter((row.get("点位ID", ""), row.get("月份", "")) for row in rows)
    duplicates = [key for key, count in keys.items() if key[0] and key[1] and count > 1]
    for site_id, month in duplicates[:50]:
        issues.append(Issue("ERROR", "OPS_MONTH_DUPLICATE", site_id, month, "每店每月一行", "经营月表存在重复主键。"))

    months = sorted(row.get("月份", "") for row in rows if re.fullmatch(r"\d{4}-\d{2}", row.get("月份", "")))
    if months:
        latest = datetime.strptime(months[-1] + "-01", "%Y-%m-%d").date()
        age_days = (today - latest).days
        if age_days > 62:
            issues.append(
                Issue(
                    "WARN",
                    "OPS_DATA_STALE",
                    "BI经营月表",
                    months[-1],
                    "距当前不超过2个月",
                    f"最新月份距今天约{age_days}天，只适合历史归因，不适合表达当前经营状态。",
                )
            )
    return issues


def validate_file_batch(paths: dict[str, Path]) -> list[Issue]:
    existing = {name: path for name, path in paths.items() if path.exists()}
    if len(existing) < 2:
        return []
    timestamps = {name: path.stat().st_mtime for name, path in existing.items()}
    oldest = min(timestamps, key=timestamps.get)
    newest = max(timestamps, key=timestamps.get)
    gap_days = (timestamps[newest] - timestamps[oldest]) / 86400
    if gap_days <= 7:
        return []
    return [
        Issue(
            "WARN",
            "INPUT_BATCH_TIME_GAP",
            "分析输入批次",
            f"最新={newest}",
            f"最旧={oldest}",
            f"文件修改时间相差{gap_days:.1f}天；底表更新后应强制重建映射和下游结果。",
        )
    ]


def validate(
    base_path: Path,
    mapping_path: Path,
    rent_path: Path,
    ops_path: Path,
    today: date | None = None,
    episodes_path: Path | None = None,
) -> list[Issue]:
    today = today or date.today()
    base_rows = read_csv(base_path)
    mapping_rows = normalize_mapping_rows(read_records(mapping_path))
    rent_rows = read_csv(rent_path)
    ops_rows = read_csv(ops_path)
    episodes = read_records(episodes_path) if episodes_path and episodes_path.exists() else []

    issues = []
    for label, path in {"base": base_path, "mapping": mapping_path, "rent": rent_path, "ops": ops_path}.items():
        if not path.exists():
            issues.append(Issue("ERROR", "INPUT_FILE_MISSING", label, str(path), "存在且可读", "标准分析链缺少输入文件。"))
    if not base_rows:
        return issues

    issues.extend(validate_base(base_rows, episodes))
    issues.extend(validate_mapping(mapping_rows, base_rows, episodes))
    issues.extend(validate_foreign_ids(rent_rows, base_rows, "rent"))
    issues.extend(validate_foreign_ids(ops_rows, base_rows, "ops"))
    issues.extend(validate_ops(ops_rows, today))
    issues.extend(validate_file_batch({"base": base_path, "mapping": mapping_path, "rent": rent_path, "ops": ops_path}))
    return sorted(issues, key=lambda issue: ({"ERROR": 0, "WARN": 1}.get(issue.severity, 9), issue.code, issue.entity))


def write_issues(path: Path, issues: list[Issue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(asdict(Issue("", "", "", "", "", "")).keys())
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(issue) for issue in issues)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate identity and freshness contracts before rebuilding lann-site outputs.")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--mapping", default=DEFAULT_MAPPING)
    parser.add_argument("--rent", default=DEFAULT_RENT)
    parser.add_argument("--ops", default=DEFAULT_OPS)
    parser.add_argument("--episodes", default=DEFAULT_EPISODES)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    paths = {name: settings.ROOT_DIR / value for name, value in vars(args).items() if name != "out"}
    issues = validate(paths["base"], paths["mapping"], paths["rent"], paths["ops"], episodes_path=paths["episodes"])
    out_path = settings.ROOT_DIR / args.out
    write_issues(out_path, issues)
    counts = Counter(issue.severity for issue in issues)
    print(f"wrote {out_path} issues={len(issues)} errors={counts['ERROR']} warnings={counts['WARN']}")
    for issue in issues:
        print(issue.severity, issue.code, issue.entity, "->", issue.current_value, "|", issue.expected_or_reference)
    raise SystemExit(1 if counts["ERROR"] else 0)


if __name__ == "__main__":
    main()

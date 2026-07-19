import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from config import settings


DEFAULT_FILES = [
    "data/staging/base_table.csv",
    "config/store_site_mapping.json",
    "data/staging/rent_extract_feishu.csv",
    "data/staging/site_ops_monthly_bi.csv",
    "config/ops_source_policy.json",
    "data/staging/hanson_monthly_prod_amt.csv",
    "data/staging/hanson_monthly_customer_metrics.csv",
    "data/staging/hanson_revenue_trends.csv",
    "data/staging/hanson_daily_quality_issues.csv",
    "data/staging/store_2026_classification.csv",
    "data/staging/site_ops_monthly_combined.csv",
    "config/site_identity_episodes.json",
    "data/staging/base_table_analysis.csv",
    "data/staging/rent_extract_analysis.csv",
    "data/staging/site_ops_monthly_analysis.csv",
    "data/staging/site_performance_summary_bi_feishu_rent.csv",
    "data/staging/site_benchmark.csv",
    "data/staging/good_store_validation.csv",
    "data/staging/daily_ramp_analysis.csv",
    "data/staging/rent_ratio_sensitivity.csv",
    "data/staging/rent_ratio_sensitivity_summary.csv",
    "data/staging/site_performance_attribution.csv",
    "data/staging/candidate_screen_v2.csv",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_profile(path: Path) -> dict:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
    profile = {"rows": len(rows), "columns": reader.fieldnames or []}
    for field in ("月份", "统计月份起", "统计月份止"):
        values = sorted({row.get(field, "") for row in rows if row.get(field, "")})
        if values:
            profile[f"{field}_min"] = values[0]
            profile[f"{field}_max"] = values[-1]
    return profile


def describe(path: Path) -> dict:
    item = {"path": path.relative_to(settings.ROOT_DIR).as_posix(), "exists": path.exists()}
    if not path.exists():
        return item
    stat = path.stat()
    item.update(
        {
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "sha256": sha256(path),
        }
    )
    if path.suffix.lower() == ".csv":
        item.update(csv_profile(path))
    return item


def build_manifest(files: list[str]) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": [describe(settings.ROOT_DIR / name) for name in files],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Record exact lann-site input/output versions for a rebuild.")
    parser.add_argument("--file", action="append", dest="files", help="Relative project file; repeat as needed.")
    parser.add_argument("--out", default="data/staging/pipeline_manifest.json")
    args = parser.parse_args()
    manifest = build_manifest(args.files or DEFAULT_FILES)
    out_path = settings.ROOT_DIR / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path} files={len(manifest['files'])}")


if __name__ == "__main__":
    main()
